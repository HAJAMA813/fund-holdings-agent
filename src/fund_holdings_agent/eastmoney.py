from __future__ import annotations

import datetime as dt
import html as html_lib
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any

from lxml import html as lxml_html

from .io import clean_text


MANAGER_URL = "https://fundf10.eastmoney.com/jjjl_{code}.html"
HOLDINGS_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10&year={year}&month={month}"


def fetch_url(url: str, retries: int = 3, timeout: int = 20, sleep_seconds: float = 0.8, referer: str = "") -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
    }
    if referer:
        headers["Referer"] = referer
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            if sleep_seconds:
                time.sleep(sleep_seconds)
            return raw.decode("utf-8", errors="ignore")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            logging.warning("公开数据请求暂时失败（第%s/%s次），正在自动重试：%s", attempt, retries, url)
            if attempt < retries:
                time.sleep(sleep_seconds + 1.5**attempt)
    raise RuntimeError(f"请求重试后仍失败: {last_error}")


def _parse_date(value: str) -> dt.date | None:
    if clean_text(value) in {"", "--", "-", "至今"}:
        return None
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    return dt.date(*map(int, match.groups())) if match else None


def _manager_names(value: str) -> tuple[str, ...]:
    parts = re.split(r"[,，、;；\s]+", clean_text(value))
    return tuple(sorted(dict.fromkeys(part for part in parts if part)))


def parse_manager_at_date(page_html: str, report_date: str) -> tuple[str, list[dict[str, str]]]:
    target = dt.date.fromisoformat(report_date)
    doc = lxml_html.fromstring(page_html)
    matched: list[dict[str, str]] = []
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        headers = [clean_text(cell.text_content()) for cell in rows[0].xpath("./th|./td")]
        if not {"起始期", "截止期", "基金经理"}.issubset(set(headers)):
            continue
        indexes = {name: headers.index(name) for name in ("起始期", "截止期", "基金经理")}
        for tr in rows[1:]:
            cells = [clean_text(cell.text_content()) for cell in tr.xpath("./td|./th")]
            if len(cells) <= max(indexes.values()):
                continue
            start = _parse_date(cells[indexes["起始期"]])
            end = _parse_date(cells[indexes["截止期"]]) or dt.date.max
            if start and start <= target <= end:
                matched.append({name: cells[index] for name, index in indexes.items()})
        break
    names: list[str] = []
    for row in matched:
        names.extend(_manager_names(row["基金经理"]))
    return ",".join(dict.fromkeys(names)), matched


def extract_content(response_text: str) -> str:
    match = re.search(r'content:"(.*)",arryear:', response_text, flags=re.S)
    if not match:
        return ""
    return html_lib.unescape(match.group(1).replace(r"\/", "/").replace(r'\"', '"'))


def parse_number(value: object) -> float | None:
    text = clean_text(value).replace(",", "").replace("%", "")
    if text in {"", "--", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def infer_stock_code(raw_code: str, href: str) -> tuple[str, str]:
    code = clean_text(raw_code)
    match = re.search(r"/r/(\d+)\.", href or "")
    market_id = match.group(1) if match else ""
    if re.search(r"[A-Za-z]", code):
        return f"{code}.US", "美股/海外"
    if re.fullmatch(r"(?:8|4|43|83|87|92)\d+", code):
        return f"{code}.BJ", "A股"
    if market_id == "0" or re.fullmatch(r"[023]\d{5}", code):
        return f"{code}.SZ", "A股"
    if market_id == "1" or re.fullmatch(r"[569]\d{5}", code):
        return f"{code}.SH", "A股"
    if re.fullmatch(r"\d{5}", code):
        return f"{code}.HK", "港股"
    return code, "美股/海外"


def parse_holdings(response_text: str, report_date: str, source_url: str) -> tuple[list[dict[str, Any]], str]:
    content = extract_content(response_text)
    if not content:
        return [], "接口未返回可解析 content"
    if "暂无" in content and "<tbody" not in content:
        return [], "接口暂无数据"
    doc = lxml_html.fromstring(content)
    tables = doc.xpath("//table[contains(@class, 'tzxq')]")
    if not tables:
        return [], "未找到股票投资明细表"
    selected = None
    available_dates: set[str] = set()
    for table in tables:
        context_nodes = table.xpath(
            "ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' boxitem ')][1]//h4[1]//text()"
        )
        if not context_nodes:
            context_nodes = table.xpath("preceding::*[self::h3 or self::h4 or self::label][1]//text()")
        context = clean_text(" ".join(context_nodes))
        table_dates: set[str] = set()
        for year, month, day in re.findall(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?", context):
            table_dates.add(dt.date(int(year), int(month), int(day)).isoformat())
        available_dates.update(table_dates)
        if report_date in table_dates:
            selected = table
            break
    if selected is None:
        available = "、".join(sorted(available_dates)) or "未标明"
        return [], f"未找到报告期 {report_date} 的股票投资明细；接口可用报告期：{available}"
    header_cells = selected.xpath(".//thead/tr[1]/th|.//thead/tr[1]/td")
    headers = [re.sub(r"\s+", "", clean_text(cell.text_content())) for cell in header_cells]
    def column_index(fragment: str) -> int | None:
        return next((index for index, header in enumerate(headers) if fragment in header), None)
    indexes = {
        "rank": column_index("序号"),
        "code": column_index("股票代码"),
        "name": column_index("股票名称"),
        "ratio": column_index("占净值比例"),
        "shares": column_index("持股数"),
        "value": column_index("持仓市值"),
    }
    if any(index is None for index in indexes.values()):
        return [], f"持仓表字段不完整：{headers}"
    parsed: list[dict[str, Any]] = []
    for tr in selected.xpath(".//tbody/tr"):
        cells = tr.xpath("./td")
        if len(cells) <= max(indexes.values()):
            continue
        rank_text = clean_text(cells[indexes["rank"]].text_content())
        if not rank_text.isdigit():
            continue
        code_cell = cells[indexes["code"]]
        anchor = code_cell.xpath(".//a")
        href = anchor[0].get("href", "") if anchor else ""
        stock_code, market = infer_stock_code(code_cell.text_content(), href)
        parsed.append({
            "rank": int(rank_text),
            "stock_code": stock_code,
            "stock_name": clean_text(cells[indexes["name"]].text_content()),
            "nav_ratio": None if parse_number(cells[indexes["ratio"]].text_content()) is None else parse_number(cells[indexes["ratio"]].text_content()) / 100,
            "shares_10k": parse_number(cells[indexes["shares"]].text_content()),
            "market_value_10k": parse_number(cells[indexes["value"]].text_content()),
            "market": market,
            "source_url": source_url,
        })
    return sorted(parsed, key=lambda row: row["rank"])[:10], "" if parsed else "表格存在但未解析到持仓行"
