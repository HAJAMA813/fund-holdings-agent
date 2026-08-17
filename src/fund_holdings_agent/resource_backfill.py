from __future__ import annotations

import hashlib
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .candidate_confirmations import read_candidate_confirmation_csv
from .portfolio import atomic_write_json, company_directory_name, read_manager_roster
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now, quarter_label
from .resource_matching import NON_MATCHABLE_SW_LABELS, build_resource_matching, read_personnel_csv, save_resource_json


def backfill_portfolio_resources(
    roster_path: Path,
    output_root: Path,
    report_date: str,
    personnel_path: Path,
    summary_path: Path | None = None,
    candidate_confirmation_path: Path | None = None,
) -> dict[str, Any]:
    people, personnel_issues = read_personnel_csv(personnel_path)
    confirmations, confirmation_issues = read_candidate_confirmation_csv(candidate_confirmation_path)
    entries = read_manager_roster(roster_path)
    report_date_value = dt.date.fromisoformat(report_date)
    if (report_date_value.month, report_date_value.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        raise ValueError("report_date 必须是自然季度末")
    quarter = quarter_label(report_date_value)
    manager_results: list[dict[str, Any]] = []
    pending_records: list[dict[str, Any]] = []
    excluded_records: list[dict[str, Any]] = []

    for entry in entries:
        manager_dir = output_root / company_directory_name(entry.company) / f"{entry.manager}_{quarter}"
        industry_path = manager_dir / "industry_analysis_data.json"
        output_path = manager_dir / "resource_matching_data.json"
        result: dict[str, Any] = {
            "company": entry.company,
            "manager": entry.manager,
            "manager_id": entry.manager_id,
            "industry_input": str(industry_path.resolve()),
            "resource_output": str(output_path.resolve()),
        }
        if not industry_path.exists():
            result.update({"status": "failed", "error": "缺少 industry_analysis_data.json"})
            manager_results.append(result)
            continue
        try:
            industry_data = json.loads(industry_path.read_text(encoding="utf-8"))
            data = build_resource_matching(
                industry_data,
                people,
                personnel_issues,
                confirmations,
                confirmation_issues,
                str(candidate_confirmation_path.resolve()) if candidate_confirmation_path and candidate_confirmation_path.exists() else "",
            )
            save_resource_json(data, output_path)
            pending_records.extend({"company": entry.company, "manager": entry.manager, **item} for item in data["pending_items"])
            excluded_records.extend({"company": entry.company, "manager": entry.manager, **item} for item in data["excluded_demands"])
            result.update({"status": "completed", "summary": data["summary"]})
        except Exception as exc:
            result.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        manager_results.append(result)

    company_metrics = _company_metrics(manager_results)
    completed_count = sum(row["status"] == "completed" for row in manager_results)
    failed_count = len(manager_results) - completed_count
    completed_summaries = [row["summary"] for row in manager_results if row["status"] == "completed"]
    overall_status = "completed" if failed_count == 0 else ("failed" if completed_count == 0 else "completed_with_errors")
    payload: dict[str, Any] = {
        "report_date": report_date,
        "quarter": quarter,
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "roster_file": str(roster_path.resolve()),
        "personnel_file": str(personnel_path.resolve()),
        "personnel_sha256": _sha256(personnel_path),
        "personnel_count": len(people),
        "personnel_error_count": sum(issue["severity"] == "错误" for issue in personnel_issues),
        "personnel_warning_count": sum(issue["severity"] == "警告" for issue in personnel_issues),
        "candidate_confirmation_file": str(candidate_confirmation_path.resolve()) if candidate_confirmation_path and candidate_confirmation_path.exists() else "",
        "candidate_confirmation_sha256": _sha256(candidate_confirmation_path) if candidate_confirmation_path and candidate_confirmation_path.exists() else "",
        "candidate_confirmation_relation_count": len(confirmations),
        "candidate_confirmation_error_count": sum(issue.get("severity") == "错误" for issue in confirmation_issues),
        "manager_count": len(manager_results),
        "completed_manager_count": completed_count,
        "failed_manager_count": failed_count,
        "industry_demand_count_sum": sum(int(summary["industry_demand_count"]) for summary in completed_summaries),
        "company_demand_count_sum": sum(int(summary["company_demand_count"]) for summary in completed_summaries),
        "match_count_sum": sum(int(summary["match_count"]) for summary in completed_summaries),
        "candidate_match_count_sum": sum(int(summary.get("candidate_match_count", 0)) for summary in completed_summaries),
        "confirmed_candidate_match_count_sum": sum(int(summary.get("confirmed_candidate_match_count", 0)) for summary in completed_summaries),
        "pending_count_sum": sum(int(summary["pending_count"]) for summary in completed_summaries),
        "pending_industry_count": sum(row["demand_type"] == "行业" for row in pending_records),
        "pending_company_count": sum(row["demand_type"] == "公司" for row in pending_records),
        "non_sw_company_pending_count": sum(row["demand_type"] == "公司" and row.get("sw_level1", "") in NON_MATCHABLE_SW_LABELS for row in pending_records),
        "excluded_non_sw_company_count_sum": len(excluded_records),
        "excluded_non_sw_unique_company_count": len({row["stock_code"] for row in excluded_records}),
        "excluded_non_sw_manager_count": len({row["manager"] for row in excluded_records}),
        "excluded_non_sw_companies": _excluded_rollup(excluded_records),
        "uncovered_sw_industries": sorted({row.get("sw_level1", "") for row in pending_records if row.get("sw_level1", "") not in NON_MATCHABLE_SW_LABELS}),
        "pending_rollup": _pending_rollup(pending_records),
        "managers_without_demands": [
            row["manager"]
            for row in manager_results
            if row["status"] == "completed"
            and int(row["summary"]["industry_demand_count"]) == 0
            and int(row["summary"]["company_demand_count"]) == 0
        ],
        "company_metrics": company_metrics,
        "manager_results": manager_results,
        "overall_status": overall_status,
        "exit_code": 0 if overall_status == "completed" else 3,
        "aggregation_note": "需求数和匹配数为逐基金经理结果的算术合计，可能包含共同管理基金的重复，不代表公司层唯一持仓或唯一人员覆盖。",
        "privacy_note": "回填使用联系权限控制；需审批或不允许的联系方式在匹配结果中均显示为已隐藏。",
        "network_note": "本流程只读取已有 industry_analysis_data.json，不执行基金持仓或行业联网抓取。",
    }
    final_path = summary_path or output_root / f"resource_backfill_summary_{quarter}.json"
    atomic_write_json(final_path, payload)
    payload["summary_file"] = str(final_path.resolve())
    return payload


def _company_metrics(manager_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manager_results:
        grouped[row["company"]].append(row)
    result = []
    for company, rows in sorted(grouped.items()):
        summaries = [row["summary"] for row in rows if row["status"] == "completed"]
        result.append(
            {
                "company": company,
                "manager_count": len(rows),
                "completed_manager_count": len(summaries),
                "failed_manager_count": len(rows) - len(summaries),
                "industry_demand_count_sum": sum(int(summary["industry_demand_count"]) for summary in summaries),
                "company_demand_count_sum": sum(int(summary["company_demand_count"]) for summary in summaries),
                "match_count_sum": sum(int(summary["match_count"]) for summary in summaries),
                "source_candidate_match_count_sum": sum(int(summary.get("source_candidate_match_count", summary.get("candidate_match_count", 0))) for summary in summaries),
                "confirmed_candidate_match_count_sum": sum(int(summary.get("confirmed_candidate_match_count", 0)) for summary in summaries),
                "candidate_match_count_sum": sum(int(summary.get("candidate_match_count", 0)) for summary in summaries),
                "pending_count_sum": sum(int(summary["pending_count"]) for summary in summaries),
                "excluded_non_sw_company_count_sum": sum(int(summary.get("excluded_non_sw_company_count", 0)) for summary in summaries),
            }
        )
    return result


def _pending_rollup(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        key = (row["demand_type"], row.get("sw_level1", ""))
        target = grouped.setdefault(
            key,
            {
                "demand_type": row["demand_type"],
                "sw_level1": row.get("sw_level1", ""),
                "item_count": 0,
                "managers": set(),
                "targets": set(),
            },
        )
        target["item_count"] += 1
        target["managers"].add(row["manager"])
        target["targets"].add(f"{row['target_code']} {row['target_name']}")
    result = []
    for row in grouped.values():
        result.append(
            {
                "demand_type": row["demand_type"],
                "sw_level1": row["sw_level1"],
                "item_count": row["item_count"],
                "manager_count": len(row["managers"]),
                "managers": sorted(row["managers"]),
                "unique_target_count": len(row["targets"]),
                "targets": sorted(row["targets"]),
                "sample_targets": sorted(row["targets"])[:10],
            }
        )
    return sorted(result, key=lambda row: (row["demand_type"], -row["item_count"], row["sw_level1"]))


def _excluded_rollup(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        key = (row["stock_code"], row["stock_name"])
        target = grouped.setdefault(
            key,
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "sw_level1": row.get("sw_level1", ""),
                "reason": row.get("reason", ""),
                "item_count": 0,
                "managers": set(),
            },
        )
        target["item_count"] += 1
        target["managers"].add(row["manager"])
    return sorted(
        (
            {
                **{key: value for key, value in row.items() if key != "managers"},
                "manager_count": len(row["managers"]),
                "managers": sorted(row["managers"]),
            }
            for row in grouped.values()
        ),
        key=lambda row: (-row["item_count"], row["stock_code"]),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
