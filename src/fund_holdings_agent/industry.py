from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import html as lxml_html

from .cache_utils import atomic_write_cache, read_cache_text
from .io import clean_text


SW_OVERVIEW_URL = "https://legulegu.com/stockdata/sw-industry-overview"
STOCK_INDUSTRY_URL = "https://basic.10jqka.com.cn/{code}/index.html"
SW_STANDARD_URL = "https://wxweb.swsresearch.com/swsreport/2021_08/328340.pdf"
TUSHARE_HISTORY_DOC_URL = "https://tushare.pro/document/2?doc_id=335"


class IndustryFetcher:
    def __init__(self, cache_dir: Path, refresh: bool = False, retries: int = 3, timeout: int = 25, sleep_seconds: float = 0.2):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.retries = retries
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        cache_dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, url: str, encoding: str = "utf-8") -> str:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cached = self.cache_dir / f"{key}.html"
        if cached.exists() and not self.refresh:
            text = read_cache_text(cached)
            if text is not None:
                return text
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "identity",
            },
        )
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                text = raw.decode(encoding, errors="ignore")
                atomic_write_cache(cached, text)
                if self.sleep_seconds:
                    time.sleep(self.sleep_seconds)
                return text
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                logging.warning("行业数据请求暂时失败（第%s/%s次），正在自动重试：%s", attempt, self.retries, url)
                if attempt < self.retries:
                    time.sleep(self.sleep_seconds + 1.5**attempt)
        raise RuntimeError(f"行业数据请求重试后仍失败: {last_error}")


def parse_sw_level2_map(page_html: str) -> dict[str, dict[str, str]]:
    doc = lxml_html.fromstring(page_html)
    code_nodes = doc.xpath("//div[@id='level2Items']//div[contains(@class,'lg-industries-item-chinese-title')]")
    name_nodes = doc.xpath("//div[@id='level2Items']//div[contains(@class,'lg-industries-item-number')]")
    result: dict[str, dict[str, str]] = {}
    for code_node, name_node in zip(code_nodes, name_nodes):
        code = clean_text(code_node.text_content())
        text = clean_text(name_node.text_content())
        match = re.match(r"(.+?)\(\d+\)\[(.+?)\]", text)
        if match:
            result[match.group(1)] = {"sw_level1": match.group(2), "sw_level2_code": code}
    return result


def parse_stock_sw_industry(page_html: str) -> str:
    match = re.search(r"所属申万行业[：:]</span>\s*<span[^>]*>([^<]+)", page_html, flags=re.S)
    if match:
        return clean_text(match.group(1))
    doc = lxml_html.fromstring(page_html)
    for node in doc.xpath("//*[contains(normalize-space(.),'所属申万行业')]"):
        text = clean_text(node.text_content())
        match = re.search(r"所属申万行业[：:]?\s*([^\s]+)", text)
        if match:
            return match.group(1)
    return ""


def enrich_industries(
    pipeline_data: dict[str, Any],
    snapshot_date: str,
    fetcher: IndustryFetcher,
    max_workers: int = 4,
) -> dict[str, Any]:
    level2_map = parse_sw_level2_map(fetcher(SW_OVERVIEW_URL, "utf-8"))
    if len(level2_map) < 100:
        raise ValueError(f"申万二级行业表解析异常，仅得到 {len(level2_map)} 个分类")

    formal = pipeline_data.get("formal_holdings", [])
    unique_stocks = {
        row["stock_code"]: {"stock_code": row["stock_code"], "stock_name": row["stock_name"], "market": row.get("market", "")}
        for row in formal
    }
    mapping: dict[str, dict[str, str]] = {}
    issues: list[dict[str, str]] = []

    def fetch_stock(item: tuple[str, dict[str, str]]) -> tuple[str, dict[str, str]]:
        stock_code, stock = item
        source_url = STOCK_INDUSTRY_URL.format(code=stock_code.split(".")[0])
        if stock["market"] != "A股":
            return stock_code, {
                **stock,
                "sw_level1": "不适用",
                "sw_level2": "不适用",
                "sw_level2_code": "",
                "classification_status": "非A股不适用",
                "source_url": source_url,
            }
        page = fetcher(source_url, "gbk")
        sw_level2 = parse_stock_sw_industry(page)
        parent = level2_map.get(sw_level2)
        return stock_code, {
            **stock,
            "sw_level1": parent["sw_level1"] if parent else "未匹配",
            "sw_level2": sw_level2 or "未匹配",
            "sw_level2_code": parent["sw_level2_code"] if parent else "",
            "classification_status": "当前快照已匹配" if parent else "未匹配",
            "source_url": source_url,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_stock, item): item[0] for item in unique_stocks.items()}
        for future in concurrent.futures.as_completed(futures):
            stock_code = futures[future]
            try:
                code, row = future.result()
                mapping[code] = row
            except Exception as exc:
                stock = unique_stocks[stock_code]
                mapping[stock_code] = {
                    **stock,
                    "sw_level1": "未匹配",
                    "sw_level2": "未匹配",
                    "sw_level2_code": "",
                    "classification_status": "请求失败",
                    "source_url": STOCK_INDUSTRY_URL.format(code=stock_code.split(".")[0]),
                }
                issues.append(_industry_issue("错误", "行业页面请求失败", stock_code, stock["stock_name"], str(exc), mapping[stock_code]["source_url"]))

    for stock_code, row in mapping.items():
        if row["market"] == "A股" and row["classification_status"] == "未匹配":
            issues.append(_industry_issue("警告", "申万行业未匹配", stock_code, row["stock_name"], f"页面行业={row['sw_level2']}", row["source_url"]))

    for index, stock_code in enumerate(sorted(mapping), start=1):
        mapping[stock_code]["industry_source_id"] = f"IND{index:03d}"

    issues.append({
        "severity": "警告",
        "category": "行业历史时点限制",
        "stock_code": "",
        "stock_name": "",
        "message": f"申万行业使用 {snapshot_date} 当前公开快照，不能证明与报告期 {pipeline_data['summary']['report_date']} 完全一致",
        "source_url": SW_OVERVIEW_URL,
        "action": "生产历史口径需配置 Tushare index_member_all 或内部带纳入/剔除日期的申万行业表",
    })

    def enrich(row: dict[str, Any]) -> dict[str, Any]:
        industry = mapping.get(row["stock_code"], {})
        return row | {
            "sw_level1": industry.get("sw_level1", "未匹配"),
            "sw_level2": industry.get("sw_level2", "未匹配"),
            "sw_level2_code": industry.get("sw_level2_code", ""),
            "industry_snapshot_date": snapshot_date,
            "industry_status": industry.get("classification_status", "未匹配"),
            "industry_source_id": industry.get("industry_source_id", ""),
            "industry_source_url": industry.get("source_url", ""),
        }

    formal_enriched = [enrich(row) for row in formal]
    all_enriched = [enrich(row) for row in pipeline_data.get("all_holdings", [])]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in formal_enriched:
        groups[(row["fund_code"], row["fund_name"], row["sw_level1"])].append(row)
    industry_summary = []
    for (fund_code, fund_name, sw_level1), rows in groups.items():
        industry_summary.append({
            "fund_code": fund_code,
            "fund_name": fund_name,
            "sw_level1": sw_level1,
            "holding_count": len(rows),
            "market_value_10k": sum(row.get("market_value_10k") or 0 for row in rows),
            "nav_ratio": sum(row.get("nav_ratio") or 0 for row in rows),
        })
    industry_summary.sort(key=lambda row: (row["fund_code"], -row["market_value_10k"], row["sw_level1"]))

    eligible = [row for row in formal_enriched if row.get("market") == "A股"]
    mapped = [row for row in eligible if row["industry_status"] == "当前快照已匹配"]
    unique_mapped = [row for row in mapping.values() if row.get("market") == "A股" and row["classification_status"] == "当前快照已匹配"]
    result = dict(pipeline_data)
    result.update({
        "formal_holdings_industry": formal_enriched,
        "all_holdings_industry": all_enriched,
        "stock_industry_mapping": [mapping[key] | {"industry_snapshot_date": snapshot_date} for key in sorted(mapping)],
        "industry_summary": industry_summary,
        "industry_issues": issues,
        "industry_quality": {
            "snapshot_date": snapshot_date,
            "standard": "申万行业分类标准2021",
            "eligible_holding_rows": len(eligible),
            "mapped_holding_rows": len(mapped),
            "holding_coverage": len(mapped) / len(eligible) if eligible else 0,
            "unique_stock_count": len(unique_stocks),
            "unique_stock_mapped": len(unique_mapped),
            "unique_stock_coverage": len(unique_mapped) / len(unique_stocks) if unique_stocks else 0,
            "level1_count": len({row["sw_level1"] for row in mapped}),
            "historical_point_in_time": False,
            "error_count": sum(row["severity"] == "错误" for row in issues),
            "warning_count": sum(row["severity"] == "警告" for row in issues),
        },
        "industry_sources": [
            {"item": "申万分类标准", "url": SW_STANDARD_URL, "note": "申万行业分类标准2021；一级行业共31个"},
            {"item": "一级/二级映射", "url": SW_OVERVIEW_URL, "note": f"公开申万行业当前快照；抓取日期 {snapshot_date}"},
            {"item": "股票申万行业", "url": "https://basic.10jqka.com.cn/{股票代码}/index.html", "note": "页面明确标注所属申万行业；用于二级行业识别"},
            {"item": "历史化推荐接口", "url": TUSHARE_HISTORY_DOC_URL, "note": "index_member_all 提供纳入/剔除日期；当前环境未配置 Token，本次未调用"},
        ],
    })
    return result


def save_industry_json(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _industry_issue(severity: str, category: str, stock_code: str, stock_name: str, message: str, source_url: str) -> dict[str, str]:
    return {
        "severity": severity,
        "category": category,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "message": message,
        "source_url": source_url,
        "action": "人工核查分类来源并补充映射",
    }
