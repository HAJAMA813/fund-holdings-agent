from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .quarter_compare import compare_quarters, save_comparison_json


def build_company_comparison(
    previous_summary_path: Path,
    current_summary_path: Path,
    company: str,
) -> dict[str, Any]:
    previous_summary = _read_json(previous_summary_path)
    current_summary = _read_json(current_summary_path)
    previous_pipeline, previous_industry, previous_meta = _company_period(previous_summary, company)
    current_pipeline, current_industry, current_meta = _company_period(current_summary, company)

    data = compare_quarters(previous_pipeline, current_pipeline, previous_industry, current_industry)
    previous_funds = {row["fund_code"] for row in previous_pipeline["formal_holdings"]}
    current_funds = {row["fund_code"] for row in current_pipeline["formal_holdings"]}
    summary = data["summary"]
    summary.update(
        {
            "company": company,
            "manager": company,
            "analysis_type": "company_portfolio",
            "previous_manager_count": previous_meta["manager_count"],
            "current_manager_count": current_meta["manager_count"],
            "previous_duplicate_rows_removed": previous_meta["duplicate_rows_removed"],
            "current_duplicate_rows_removed": current_meta["duplicate_rows_removed"],
            "formal_fund_scope_same": previous_funds == current_funds,
            "dedup_conflict_count": previous_meta["conflict_count"] + current_meta["conflict_count"],
        }
    )
    conflict_count = summary["dedup_conflict_count"]
    data["checks"].append(
        {
            "item": "共同管理基金去重一致性",
            "actual": conflict_count,
            "expected": 0,
            "status": "OK" if conflict_count == 0 else "CHECK",
            "note": "按基金代码+股票代码去重；重复披露的排名、股数、市值和净值比例必须一致",
        }
    )
    if conflict_count:
        summary["status"] = "存在需核查项"
    data["rules"].insert(
        1,
        {
            "item": "公司级共同管理去重",
            "rule": "同一基金由名单内多位经理共同管理时，按基金代码+股票代码只计一次；重复披露核心数值不一致则标记需核查",
        },
    )
    data["sources"] = [
        {"item": "上期公司批次摘要", "path": str(previous_summary_path.resolve()), "report_date": summary["previous_report_date"]},
        {"item": "本期公司批次摘要", "path": str(current_summary_path.resolve()), "report_date": summary["current_report_date"]},
        *previous_meta["sources"],
        *current_meta["sources"],
    ]
    data["dedup_conflicts"] = [*previous_meta["conflicts"], *current_meta["conflicts"]]
    return data


def save_company_comparison(data: dict[str, Any], path: Path) -> Path:
    return save_comparison_json(data, path)


def _company_period(summary: dict[str, Any], company: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    results = [row for row in summary.get("manager_results", []) if row.get("company") == company]
    if not results:
        raise ValueError(f"批次摘要中没有公司：{company}")

    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    stock_mapping: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    snapshots: set[str] = set()
    historical_flags: list[bool] = []
    error_count = 0
    raw_row_count = 0

    for result in sorted(results, key=lambda row: str(row.get("manager", ""))):
        output_dir = Path(str(result["output_dir"]))
        path = output_dir / "industry_analysis_data.json"
        data = _read_json(path)
        report_date = str(data["summary"]["report_date"])
        sources.append({"item": f"{result['manager']}持仓与行业", "path": str(path.resolve()), "report_date": report_date})
        quality = data["industry_quality"]
        snapshots.add(str(quality.get("snapshot_date", "")))
        historical_flags.append(bool(quality.get("historical_point_in_time")))
        error_count += int(data["summary"].get("error_count", 0)) + int(quality.get("error_count", 0))

        for mapping in data.get("stock_industry_mapping", []):
            code = str(mapping["stock_code"])
            existing = stock_mapping.get(code)
            if existing and _mapping_signature(existing) != _mapping_signature(mapping):
                conflicts.append({"report_date": report_date, "type": "industry_mapping", "stock_code": code})
            else:
                stock_mapping.setdefault(code, dict(mapping))

        for row in data.get("formal_holdings_industry", []):
            raw_row_count += 1
            key = (str(row["fund_code"]), str(row["stock_code"]))
            owners[key].add(str(result["manager"]))
            existing = dedup.get(key)
            if existing and _holding_signature(existing) != _holding_signature(row):
                conflicts.append(
                    {
                        "report_date": report_date,
                        "type": "holding",
                        "fund_code": key[0],
                        "stock_code": key[1],
                        "managers": "、".join(sorted(owners[key])),
                    }
                )
            else:
                dedup.setdefault(key, dict(row))

    rows = []
    for key in sorted(dedup):
        row = dict(dedup[key])
        row["manager"] = "、".join(sorted(owners[key]))
        rows.append(row)

    report_date = str(summary["report_date"])
    company_pipeline = {
        "summary": {"manager": company, "report_date": report_date, "error_count": error_count},
        "formal_holdings": rows,
    }
    industry_summary = _industry_summary(rows)
    company_industry = {
        "industry_quality": {
            "snapshot_date": _single_value(snapshots, "行业快照日期"),
            "historical_point_in_time": bool(historical_flags) and all(historical_flags),
        },
        "stock_industry_mapping": list(sorted(stock_mapping.values(), key=lambda row: str(row["stock_code"]))),
        "industry_summary": industry_summary,
    }
    meta = {
        "manager_count": len(results),
        "duplicate_rows_removed": raw_row_count - len(rows),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "sources": sources,
    }
    return company_pipeline, company_industry, meta


def _industry_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["fund_code"]), str(row.get("sw_level1") or "待核查"))
        target = grouped.setdefault(
            key,
            {
                "fund_code": key[0],
                "fund_name": row.get("fund_name", ""),
                "sw_level1": key[1],
                "holding_count": 0,
                "market_value_10k": 0.0,
                "nav_ratio": 0.0,
            },
        )
        target["holding_count"] += 1
        target["market_value_10k"] += float(row.get("market_value_10k") or 0.0)
        target["nav_ratio"] += float(row.get("nav_ratio") or 0.0)
    return [grouped[key] for key in sorted(grouped)]


def _holding_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("fund_name"),
        row.get("stock_name"),
        int(row.get("rank") or 0),
        float(row.get("shares_10k") or 0.0),
        float(row.get("market_value_10k") or 0.0),
        float(row.get("nav_ratio") or 0.0),
        row.get("sw_level1"),
    )


def _mapping_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("stock_name"), row.get("sw_level1"), row.get("sw_level2"), row.get("sw_level2_code"))


def _single_value(values: set[str], label: str) -> str:
    clean = {value for value in values if value}
    if len(clean) != 1:
        raise ValueError(f"{label}必须唯一，实际为：{sorted(clean)}")
    return next(iter(clean))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
