from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .quarterly_cli import previous_quarter, quarter_label


SCHEMA_VERSION = 2
QUARTER_COUNT = 3


@dataclass(frozen=True)
class QuarterInput:
    report_date: dt.date
    directory: Path

    @property
    def label(self) -> str:
        return quarter_label(self.report_date)

    @property
    def fund_pool_path(self) -> Path:
        return self.directory / "manager_fund_pool_data.json"

    @property
    def industry_path(self) -> Path:
        return self.directory / "industry_analysis_data.json"


def three_quarter_dates(end_report_date: dt.date) -> list[dt.date]:
    _validate_quarter_end(end_report_date)
    values = [end_report_date]
    while len(values) < QUARTER_COUNT:
        values.append(previous_quarter(values[-1]))
    return list(reversed(values))


def discover_quarter_inputs(manager_root: Path, manager: str, end_report_date: dt.date) -> list[QuarterInput]:
    return [
        QuarterInput(value, manager_root / f"{manager}_{quarter_label(value)}")
        for value in three_quarter_dates(end_report_date)
    ]


def build_three_quarter_dataset(inputs: Iterable[QuarterInput]) -> dict[str, Any]:
    quarter_inputs = sorted(list(inputs), key=lambda item: item.report_date)
    if len(quarter_inputs) != QUARTER_COUNT:
        raise ValueError(f"三季度简报必须提供 {QUARTER_COUNT} 个季度输入")
    expected = three_quarter_dates(quarter_inputs[-1].report_date)
    actual = [item.report_date for item in quarter_inputs]
    if actual != expected:
        raise ValueError("季度输入必须是截至目标报告期的连续三个自然季度")

    missing = [
        str(path)
        for item in quarter_inputs
        for path in (item.fund_pool_path, item.industry_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("缺少单季度标准结果：" + "；".join(missing))

    manager = ""
    company = ""
    quarter_runs: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    products_by_quarter: dict[str, list[str]] = {}
    holdings_by_quarter: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    product_codes: dict[str, set[str]] = {}
    total_a_rows = 0
    total_non_a_rows = 0

    for item in quarter_inputs:
        pool = _read_json(item.fund_pool_path)
        industry = _read_json(item.industry_path)
        pool_summary = pool.get("summary", {})
        industry_summary = industry.get("summary", {})
        quarter_manager = str(pool_summary.get("manager") or industry_summary.get("manager") or "").strip()
        quarter_company = str(pool_summary.get("company") or industry_summary.get("company") or "").strip()
        if manager and quarter_manager != manager:
            raise ValueError(f"季度输入的基金经理不一致：{manager} / {quarter_manager}")
        if company and quarter_company != company:
            raise ValueError(f"季度输入的基金公司不一致：{company} / {quarter_company}")
        manager = manager or quarter_manager
        company = company or quarter_company
        source_report_date = str(industry_summary.get("report_date") or pool_summary.get("report_date") or "")
        if source_report_date != item.report_date.isoformat():
            raise ValueError(f"{item.label} 输入报告期不一致：{source_report_date}")

        code_to_product: dict[str, str] = {}
        ordered_products: list[str] = []
        for fund in pool.get("selected_funds", []):
            if not fund.get("selected", True):
                continue
            product = str(fund.get("product_base_name") or _base_product_name(fund.get("fund_name", ""))).strip()
            code = str(fund.get("fund_code", "")).zfill(6)
            if not product:
                continue
            code_to_product[code] = product
            product_codes.setdefault(product, set()).add(code)
            if product not in ordered_products:
                ordered_products.append(product)
        products_by_quarter[item.label] = ordered_products

        quarter_holdings: dict[tuple[str, int], dict[str, Any]] = {}
        quarter_a_rows = 0
        quarter_non_a_rows = 0
        for row in industry.get("formal_holdings_industry", []):
            code = str(row.get("fund_code", "")).zfill(6)
            product = code_to_product.get(code) or _base_product_name(row.get("fund_name", ""))
            if not product:
                issues.append(_issue(item.label, "warning", "基础产品识别失败", row, "无法将持仓映射到基础产品"))
                continue
            product_codes.setdefault(product, set()).add(code)
            market = str(row.get("market", ""))
            if market != "A股":
                quarter_non_a_rows += 1
                continue
            try:
                rank = int(row.get("rank"))
            except (TypeError, ValueError):
                issues.append(_issue(item.label, "warning", "持仓排名无效", row, "持仓排名不是有效整数"))
                continue
            if not 1 <= rank <= 10:
                issues.append(_issue(item.label, "warning", "持仓排名超范围", row, f"排名 {rank} 不在 1—10"))
                continue
            key = (product, rank)
            if key in quarter_holdings:
                issues.append(_issue(item.label, "warning", "基础产品排名重复", row, f"{product} 排名 {rank} 出现多条正式记录"))
                continue
            quarter_holdings[key] = {
                "fund_code": code,
                "fund_name": row.get("fund_name", ""),
                "stock_code": row.get("stock_code", ""),
                "stock_name": row.get("stock_name", ""),
                "sw_level1": row.get("sw_level1", "") or "待核查",
                "market": market,
                "shares_10k": _number(row.get("shares_10k")),
                "market_value_10k": _number(row.get("market_value_10k")),
                "nav_ratio": _number(row.get("nav_ratio")),
                "source_url": row.get("source_url", ""),
                "industry_source_url": row.get("industry_source_url", ""),
                "industry_snapshot_date": row.get("industry_snapshot_date", ""),
            }
            quarter_a_rows += 1
        holdings_by_quarter[item.label] = quarter_holdings
        total_a_rows += quarter_a_rows
        total_non_a_rows += quarter_non_a_rows

        for row in industry.get("issues", []):
            issues.append(_copy_source_issue(item.label, "持仓", row))
        for row in industry.get("industry_issues", []):
            issues.append(_copy_source_issue(item.label, "行业", row))
        quality = industry.get("industry_quality", {})
        quarter_runs.append(
            {
                "quarter": item.label,
                "report_date": item.report_date.isoformat(),
                "selected_share_count": pool_summary.get("selected_share_count", 0),
                "base_product_count": len(ordered_products),
                "formal_holding_rows": industry_summary.get("formal_holding_rows", 0),
                "a_share_rows_in_brief": quarter_a_rows,
                "non_a_rows_excluded": quarter_non_a_rows,
                "industry_coverage": quality.get("holding_coverage", 0),
                "industry_snapshot_date": quality.get("snapshot_date", ""),
                "source_directory": str(item.directory.resolve()),
            }
        )

    # Latest-quarter products are most relevant; retain older discontinued products afterwards.
    product_order: list[str] = []
    for label in reversed([item.label for item in quarter_inputs]):
        for product in products_by_quarter[label]:
            if product not in product_order:
                product_order.append(product)
    for label in [item.label for item in quarter_inputs]:
        for product, _ in holdings_by_quarter[label]:
            if product not in product_order:
                product_order.append(product)

    quarter_labels = [item.label for item in quarter_inputs]
    rows: list[dict[str, Any]] = []
    for product in product_order:
        for rank in range(1, 11):
            values = {label: holdings_by_quarter[label].get((product, rank), {}) for label in quarter_labels}
            rows.append(
                {
                    "manager": manager,
                    "product_name": product,
                    "product_fund_codes": sorted(product_codes.get(product, set())),
                    "rank": rank,
                    "quarters": values,
                }
            )

    empty_cells = sum(not row["quarters"][label] for row in rows for label in quarter_labels)
    analytics = _build_analytics(quarter_labels, rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "manager": manager,
            "company": company,
            "start_report_date": quarter_inputs[0].report_date.isoformat(),
            "end_report_date": quarter_inputs[-1].report_date.isoformat(),
            "quarters": quarter_labels,
            "product_count": len(product_order),
            "display_row_count": len(rows),
            "a_share_holding_rows": total_a_rows,
            "non_a_holding_rows_excluded": total_non_a_rows,
            "empty_quarter_rank_cells": empty_cells,
            "issue_count": len(issues),
            "industry_rule": "申万一级行业；沿用各单季结果中的分类快照",
            "market_rule": "简报版只展示A股；港股和其他市场不递补",
            "share_class_rule": "同一基础产品A/C/E等份额仅展示正式代表份额",
            "deepseek_used": False,
        },
        "quarter_runs": quarter_runs,
        "rows": rows,
        "analytics": analytics,
        "issues": issues,
        "sources": [
            {
                "source_id": "S01",
                "name": "东方财富基金季度持仓公开披露",
                "usage": "每只基础产品季度前十大持仓",
                "url": "https://fundf10.eastmoney.com/FundArchivesDatas.aspx",
            },
            {
                "source_id": "S02",
                "name": "天天基金基金经理档案",
                "usage": "报告期任职基金池与A/C/E份额识别",
                "url": "https://fund.eastmoney.com/manager/",
            },
            {
                "source_id": "R01",
                "name": "简报版业务口径",
                "usage": "连续三季度、A股、不递补、每产品固定排名1—10、未调用DeepSeek",
                "url": "",
            },
        ],
    }


def save_three_quarter_dataset(data: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)
    return output_path


def _validate_quarter_end(value: dt.date) -> None:
    if (value.month, value.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        raise ValueError("报告期必须是自然季度末")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_product_name(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return re.sub(r"(?:人民币|美元)?(?:A|B|C|D|E|H|I|Y|Z)类?$", "", text, flags=re.IGNORECASE)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _build_analytics(quarter_labels: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    stock_by_quarter: dict[str, list[dict[str, Any]]] = {}
    industry_by_quarter: dict[str, list[dict[str, Any]]] = {}

    for label in quarter_labels:
        stocks: dict[str, dict[str, Any]] = {}
        industries: dict[str, dict[str, Any]] = {}
        for row in rows:
            holding = row["quarters"].get(label) or {}
            if not holding:
                continue
            stock_name = str(holding.get("stock_name") or "待核查")
            stock_code = str(holding.get("stock_code") or stock_name)
            industry = str(holding.get("sw_level1") or "待核查")
            stock = stocks.setdefault(
                stock_code,
                {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "sw_level1": industry,
                    "product_names": set(),
                    "record_count": 0,
                    "market_value_10k_sum": 0.0,
                    "nav_ratio_sum": 0.0,
                    "best_rank": 10,
                },
            )
            stock["product_names"].add(row["product_name"])
            stock["record_count"] += 1
            stock["market_value_10k_sum"] += _number(holding.get("market_value_10k"))
            stock["nav_ratio_sum"] += _number(holding.get("nav_ratio"))
            stock["best_rank"] = min(stock["best_rank"], int(row["rank"]))

            industry_row = industries.setdefault(
                industry,
                {
                    "sw_level1": industry,
                    "stock_codes": set(),
                    "product_names": set(),
                    "record_count": 0,
                    "market_value_10k_sum": 0.0,
                    "nav_ratio_sum": 0.0,
                },
            )
            industry_row["stock_codes"].add(stock_code)
            industry_row["product_names"].add(row["product_name"])
            industry_row["record_count"] += 1
            industry_row["market_value_10k_sum"] += _number(holding.get("market_value_10k"))
            industry_row["nav_ratio_sum"] += _number(holding.get("nav_ratio"))

        stock_rows = []
        for item in stocks.values():
            product_names = sorted(item.pop("product_names"))
            item["product_names"] = product_names
            item["product_count"] = len(product_names)
            item["market_value_10k_sum"] = round(item["market_value_10k_sum"], 4)
            item["nav_ratio_sum"] = round(item["nav_ratio_sum"], 8)
            stock_rows.append(item)
        stock_rows.sort(
            key=lambda item: (
                -item["market_value_10k_sum"],
                -item["nav_ratio_sum"],
                -item["product_count"],
                item["best_rank"],
                item["stock_code"],
            )
        )
        stock_by_quarter[label] = stock_rows

        industry_rows = []
        for item in industries.values():
            stock_codes = sorted(item.pop("stock_codes"))
            product_names = sorted(item.pop("product_names"))
            item["stock_count"] = len(stock_codes)
            item["product_count"] = len(product_names)
            item["market_value_10k_sum"] = round(item["market_value_10k_sum"], 4)
            item["nav_ratio_sum"] = round(item["nav_ratio_sum"], 8)
            industry_rows.append(item)
        industry_rows.sort(
            key=lambda item: (
                -item["market_value_10k_sum"],
                -item["nav_ratio_sum"],
                -item["record_count"],
                item["sw_level1"],
            )
        )
        industry_by_quarter[label] = industry_rows

    first_label, last_label = quarter_labels[0], quarter_labels[-1]
    first = {item["stock_code"]: item for item in stock_by_quarter[first_label]}
    last = {item["stock_code"]: item for item in stock_by_quarter[last_label]}

    def select(codes: set[str], source: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "stock_code": code,
                "stock_name": source[code]["stock_name"],
                "sw_level1": source[code]["sw_level1"],
            }
            for code in sorted(codes, key=lambda code: (source[code]["stock_name"], code))
        ]

    new_codes = set(last) - set(first)
    exited_codes = set(first) - set(last)
    continuing_codes = set(first) & set(last)
    return {
        "aggregation_note": "市值和净值比例为该经理各基础产品披露值的算术汇总，不代表统一组合的加权配置比例。",
        "stock_summary_by_quarter": stock_by_quarter,
        "industry_summary_by_quarter": industry_by_quarter,
        "stock_changes": {
            "from_quarter": first_label,
            "to_quarter": last_label,
            "new_count": len(new_codes),
            "exited_count": len(exited_codes),
            "continuing_count": len(continuing_codes),
            "new": select(new_codes, last),
            "exited": select(exited_codes, first),
            "continuing": select(continuing_codes, last),
        },
    }


def _issue(quarter: str, severity: str, category: str, row: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "quarter": quarter,
        "severity": severity,
        "category": category,
        "code": row.get("fund_code") or row.get("stock_code") or "",
        "name": row.get("fund_name") or row.get("stock_name") or "",
        "message": message,
        "action": "查看单季度底稿并人工核查",
        "source_url": row.get("source_url", ""),
    }


def _copy_source_issue(quarter: str, source: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "quarter": quarter,
        "severity": row.get("severity", "warning"),
        "category": f"{source}：{row.get('category', '未分类')}",
        "code": row.get("fund_code") or row.get("stock_code") or "",
        "name": row.get("fund_name") or row.get("stock_name") or "",
        "message": row.get("message", ""),
        "action": row.get("action", "查看单季度底稿"),
        "source_url": row.get("source_url", ""),
    }
