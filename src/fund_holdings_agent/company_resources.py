from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .portfolio import ManagerEntry, atomic_write_json, company_directory_name, read_manager_roster
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now, quarter_label


PRIORITY_ORDER = {"P1": 1, "P2": 2, "P3": 3}


def _load_business_notes(personnel_path: Path | None) -> dict[str, Any]:
    if personnel_path is None:
        return {}
    notes_path = personnel_path.parent / "internal_business_notes.json"
    if not notes_path.exists():
        return {}
    try:
        payload = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_company_resource_packages(
    roster_path: Path,
    input_root: Path,
    report_date: str,
    output_root: Path,
    personnel_path: Path | None = None,
    confirm_all_candidates: bool = False,
    confirmed_by: str = "项目用户",
) -> dict[str, Any]:
    report_date_value = dt.date.fromisoformat(report_date)
    if (report_date_value.month, report_date_value.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        raise ValueError("report_date 必须是自然季度末")
    quarter = quarter_label(report_date_value)
    entries = read_manager_roster(roster_path)
    business_notes = _load_business_notes(personnel_path)
    grouped: dict[str, list[ManagerEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.company].append(entry)

    companies: list[dict[str, Any]] = []
    for company, company_entries in sorted(grouped.items()):
        confirmed_at = beijing_now().isoformat(timespec="seconds") if confirm_all_candidates else ""
        payload = _aggregate_company(
            company,
            company_entries,
            input_root,
            report_date,
            quarter,
            confirm_all_candidates=confirm_all_candidates,
            confirmed_by=confirmed_by,
            confirmed_at_beijing=confirmed_at,
            business_notes=business_notes,
        )
        payload.update(
            {
                "timezone": BEIJING_TIMEZONE,
                "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
                "roster_file": str(roster_path.resolve()),
                "personnel_file": str(personnel_path.resolve()) if personnel_path else "",
                "personnel_sha256": _sha256(personnel_path) if personnel_path else "",
            }
        )
        company_dir = output_root / company_directory_name(company)
        data_path = company_dir / f"{company_directory_name(company)}_{quarter}_研究资源汇总_data.json"
        atomic_write_json(data_path, payload)
        companies.append(
            {
                "company": company,
                "status": payload["summary"]["status"],
                "data_path": str(data_path.resolve()),
                "summary": payload["summary"],
            }
        )

    completed = sum(row["status"] in {"completed", "completed_with_errors"} for row in companies)
    overall_status = (
        "completed"
        if all(row["status"] == "completed" for row in companies)
        else ("failed" if all(row["status"] == "failed" for row in companies) else "completed_with_errors")
    )
    result = {
        "report_date": report_date,
        "quarter": quarter,
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "company_count": len(companies),
        "completed_company_count": completed,
        "failed_company_count": len(companies) - completed,
        "companies": companies,
        "overall_status": overall_status,
        "exit_code": 0 if overall_status == "completed" else 3,
    }
    summary_path = output_root / f"company_resource_summary_{quarter}.json"
    atomic_write_json(summary_path, result)
    result["summary_file"] = str(summary_path.resolve())
    return result


def _aggregate_company(
    company: str,
    entries: list[ManagerEntry],
    input_root: Path,
    report_date: str,
    quarter: str,
    *,
    confirm_all_candidates: bool = False,
    confirmed_by: str = "",
    confirmed_at_beijing: str = "",
    business_notes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manager_overview: list[dict[str, Any]] = []
    loaded: list[tuple[ManagerEntry, dict[str, Any], Path]] = []
    source_files: list[dict[str, Any]] = []
    for entry in entries:
        path = input_root / company_directory_name(company) / f"{entry.manager}_{quarter}" / "resource_matching_data.json"
        if not path.exists():
            manager_overview.append(
                {
                    "manager": entry.manager,
                    "manager_id": entry.manager_id,
                    "status": "failed",
                    "industry_demand_count": 0,
                    "company_demand_count": 0,
                    "match_count": 0,
                    "candidate_match_count": 0,
                    "pending_count": 0,
                    "excluded_non_sw_company_count": 0,
                    "error": "缺少 resource_matching_data.json",
                }
            )
            source_files.append({"manager": entry.manager, "path": str(path.resolve()), "status": "missing", "sha256": ""})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("summary", {}).get("report_date") != report_date:
                raise ValueError("报告期与汇总目标不一致")
            summary = data["summary"]
            manager_overview.append(
                {
                    "manager": entry.manager,
                    "manager_id": entry.manager_id,
                    "status": "completed",
                    "industry_demand_count": int(summary.get("industry_demand_count", 0)),
                    "company_demand_count": int(summary.get("company_demand_count", 0)),
                    "match_count": int(summary.get("match_count", 0)),
                    "candidate_match_count": int(summary.get("candidate_match_count", 0)),
                    "source_candidate_match_count": int(summary.get("source_candidate_match_count", summary.get("candidate_match_count", 0))),
                    "confirmed_candidate_match_count": int(summary.get("confirmed_candidate_match_count", 0)),
                    "pending_count": int(summary.get("pending_count", 0)),
                    "excluded_non_sw_company_count": int(summary.get("excluded_non_sw_company_count", 0)),
                    "error": "",
                }
            )
            loaded.append((entry, data, path))
            source_files.append({"manager": entry.manager, "path": str(path.resolve()), "status": "loaded", "sha256": _sha256(path)})
        except Exception as exc:
            manager_overview.append(
                {
                    "manager": entry.manager,
                    "manager_id": entry.manager_id,
                    "status": "failed",
                    "industry_demand_count": 0,
                    "company_demand_count": 0,
                    "match_count": 0,
                    "candidate_match_count": 0,
                    "pending_count": 0,
                    "excluded_non_sw_company_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            source_files.append({"manager": entry.manager, "path": str(path.resolve()), "status": "invalid", "sha256": _sha256(path)})

    industry_rollup = _industry_rollup(loaded)
    company_rollup = _company_rollup(loaded)
    match_details = _match_details(loaded)
    original_candidate_items = [
        row
        for row in match_details
        if row["confirmation_status"] == "待确认" or row.get("original_confirmation_status") == "待确认"
    ]
    candidate_snapshot_sha256 = _candidate_snapshot_sha256(original_candidate_items)
    if confirm_all_candidates:
        for row in original_candidate_items:
            row["original_confirmation_status"] = "待确认"
            row["confirmation_status"] = "业务已确认"
            row["confirmed_by"] = confirmed_by
            row["confirmed_at_beijing"] = confirmed_at_beijing
    confirmed_candidate_items = [
        row for row in match_details if row.get("original_confirmation_status") == "待确认" and row["confirmation_status"] == "业务已确认"
    ]
    confirmation_registry_files = []
    for registry_path in sorted(
        {
            str(data.get("confirmation_registry_source", "")).strip()
            for _, data, _ in loaded
            if str(data.get("confirmation_registry_source", "")).strip()
        }
    ):
        path = Path(registry_path)
        confirmation_registry_files.append(
            {
                "path": str(path.resolve()),
                "sha256": _sha256(path) if path.exists() else "",
                "status": "loaded" if path.exists() else "missing",
            }
        )
    candidate_items = [row for row in match_details if row["confirmation_status"] == "待确认"]
    confirmed_by_manager: dict[str, int] = defaultdict(int)
    for row in confirmed_candidate_items:
        confirmed_by_manager[row["manager"]] += 1
    for row in manager_overview:
        source_count = row.get("source_candidate_match_count", row["candidate_match_count"])
        confirmed_count = max(row.get("confirmed_candidate_match_count", 0), confirmed_by_manager.get(row["manager"], 0))
        row["source_candidate_match_count"] = source_count
        row["confirmed_candidate_match_count"] = confirmed_count
        row["candidate_match_count"] = max(0, source_count - confirmed_count)
    confirmed_company_codes = {
        row["target_code"] for row in confirmed_candidate_items if row.get("demand_type") == "公司"
    }
    for row in company_rollup:
        if row["stock_code"] in confirmed_company_codes and row["match_status"] == "候选待确认":
            row["match_status"] = "候选已确认"
    person_rollup = _person_rollup(match_details)
    pending_items = [
        {"manager": entry.manager, **row}
        for entry, data, _ in loaded
        for row in data.get("pending_items", [])
    ]
    excluded_rollup = _excluded_rollup(loaded)
    completed_count = len(loaded)
    failed_count = len(entries) - completed_count
    status = "completed" if failed_count == 0 else ("failed" if completed_count == 0 else "completed_with_errors")
    expected = {
        "manager_count": len(entries),
        "completed_manager_count": completed_count,
        "industry_demand_count_sum": sum(row["industry_demand_count"] for row in manager_overview),
        "company_demand_count_sum": sum(row["company_demand_count"] for row in manager_overview),
        "match_count_sum": sum(row["match_count"] for row in manager_overview),
        "source_candidate_match_count_sum": sum(row["source_candidate_match_count"] for row in manager_overview),
        "confirmed_candidate_match_count_sum": sum(row["confirmed_candidate_match_count"] for row in manager_overview),
        "candidate_match_count_sum": sum(row["candidate_match_count"] for row in manager_overview),
        "pending_count_sum": sum(row["pending_count"] for row in manager_overview),
        "excluded_non_sw_company_count_sum": sum(row["excluded_non_sw_company_count"] for row in manager_overview),
    }
    return {
        "summary": {
            "company": company,
            "report_date": report_date,
            "quarter": quarter,
            **expected,
            "failed_manager_count": failed_count,
            "unique_industry_count": len(industry_rollup),
            "unique_company_count": len(company_rollup),
            "matched_person_count": len(person_rollup),
            "unique_excluded_company_count": len(excluded_rollup),
            "status": status,
        },
        "manager_overview": manager_overview,
        "industry_rollup": industry_rollup,
        "company_rollup": company_rollup,
        "person_rollup": person_rollup,
        "match_details": match_details,
        "candidate_items": candidate_items,
        "confirmed_candidate_items": confirmed_candidate_items,
        "pending_items": pending_items,
        "excluded_rollup": excluded_rollup,
        "checks_expected": expected,
        "source_files": source_files,
        "candidate_confirmation": {
            "scope": "本次公司级报告中的全部原始待确认候选" if confirmed_candidate_items else "未执行候选确认",
            "decision": "全部确认" if original_candidate_items and not candidate_items else ("部分确认" if confirmed_candidate_items else "未确认"),
            "confirmed_by": confirmed_by if confirm_all_candidates else _single_or_multiple(row.get("confirmed_by", "") for row in confirmed_candidate_items),
            "confirmed_at_beijing": confirmed_at_beijing if confirm_all_candidates else _single_or_multiple(row.get("confirmed_at_beijing", "") for row in confirmed_candidate_items),
            "source_candidate_count": len(original_candidate_items),
            "confirmed_candidate_count": len(confirmed_candidate_items),
            "remaining_candidate_count": len(candidate_items),
            "candidate_snapshot_sha256": candidate_snapshot_sha256,
            "registry_files": confirmation_registry_files,
        },
        "rules": [
            {"item": "公司范围", "rule": "只汇总同一基金公司、同一报告期的基金经理资源匹配结果"},
            {"item": "经理维度", "rule": "需求次数、匹配数和排除数按逐基金经理结果算术合计"},
            {"item": "共同管理", "rule": "共同管理基金可能在不同经理结果中重复；市值与净值比例合计不代表公司统一组合"},
            {"item": "匹配顺序", "rule": "具体公司100分；申万二级70分；人工确认一级50分；研究分组40分；候选30分"},
            *(
                [{"item": "石油石化", "rule": business_notes["petroleum_rule"]}]
                if (business_notes or {}).get("petroleum_rule")
                else []
            ),
            *(
                [{"item": "煤炭", "rule": business_notes["coal_rule"]}]
                if (business_notes or {}).get("coal_rule")
                else []
            ),
            {"item": "港股", "rule": "当前不生成港股研究资源需求；持仓保留在排除审计中"},
            {"item": "隐私", "rule": "需审批或不允许的联系方式一律隐藏"},
            {"item": "模型", "rule": "不调用DeepSeek或其他大模型，不让模型修改事实、行业和匹配结果"},
            {"item": "业务确认", "rule": "业务确认只改变确认状态，不提高原始匹配分，也不将候选映射伪装成公司或行业精确覆盖"},
        ],
    }


def _industry_rollup(loaded: list[tuple[ManagerEntry, dict[str, Any], Path]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for entry, data, _ in loaded:
        for row in data.get("industry_demands", []):
            key = row["sw_level1"]
            target = grouped.setdefault(
                key,
                {
                    "sw_level1": key,
                    "priorities": [],
                    "managers": set(),
                    "p1_managers": set(),
                    "fund_codes": set(),
                    "demand_occurrences": 0,
                    "holding_count_sum": 0,
                    "market_value_10k_sum": 0.0,
                    "nav_ratio_sum": 0.0,
                },
            )
            target["priorities"].append(row["priority"])
            target["managers"].add(entry.manager)
            if row["priority"] == "P1":
                target["p1_managers"].add(entry.manager)
            target["fund_codes"].update(_split_codes(row.get("fund_codes", "")))
            target["demand_occurrences"] += 1
            target["holding_count_sum"] += int(row.get("holding_count", 0))
            target["market_value_10k_sum"] += float(row.get("market_value_10k", 0.0))
            target["nav_ratio_sum"] += float(row.get("nav_ratio_sum", 0.0))
    result = []
    for row in grouped.values():
        result.append(
            {
                "priority": min(row["priorities"], key=lambda value: PRIORITY_ORDER.get(value, 99)),
                "sw_level1": row["sw_level1"],
                "manager_count": len(row["managers"]),
                "managers": "、".join(sorted(row["managers"])),
                "p1_manager_count": len(row["p1_managers"]),
                "demand_occurrences": row["demand_occurrences"],
                "unique_fund_count": len(row["fund_codes"]),
                "fund_codes": "、".join(sorted(row["fund_codes"])),
                "holding_count_sum": row["holding_count_sum"],
                "market_value_10k_sum": round(row["market_value_10k_sum"], 2),
                "nav_ratio_sum": round(row["nav_ratio_sum"], 10),
            }
        )
    return sorted(result, key=lambda row: (PRIORITY_ORDER.get(row["priority"], 99), -row["manager_count"], row["sw_level1"]))


def _company_rollup(loaded: list[tuple[ManagerEntry, dict[str, Any], Path]]) -> list[dict[str, Any]]:
    match_people: dict[str, set[str]] = defaultdict(set)
    best_scores: dict[str, int] = defaultdict(int)
    for _, data, _ in loaded:
        for match in data.get("matches", []):
            if match.get("demand_type") != "公司":
                continue
            code = str(match.get("target_code", ""))
            match_people[code].add(str(match.get("person_name", "")))
            best_scores[code] = max(best_scores[code], int(match.get("score", 0)))
    grouped: dict[str, dict[str, Any]] = {}
    for entry, data, _ in loaded:
        for row in data.get("company_demands", []):
            key = row["stock_code"]
            target = grouped.setdefault(
                key,
                {
                    "stock_code": key,
                    "stock_name": row.get("stock_name", ""),
                    "sw_level1": row.get("sw_level1", ""),
                    "sw_level2": row.get("sw_level2", ""),
                    "priorities": [],
                    "managers": set(),
                    "p1_managers": set(),
                    "fund_codes": set(),
                    "demand_occurrences": 0,
                    "holding_occurrences_sum": 0,
                    "market_value_10k_sum": 0.0,
                    "max_nav_ratio": 0.0,
                },
            )
            target["priorities"].append(row["priority"])
            target["managers"].add(entry.manager)
            if row["priority"] == "P1":
                target["p1_managers"].add(entry.manager)
            target["fund_codes"].update(_split_codes(row.get("fund_codes", "")))
            target["demand_occurrences"] += 1
            target["holding_occurrences_sum"] += int(row.get("holding_occurrences", 0))
            target["market_value_10k_sum"] += float(row.get("market_value_10k", 0.0))
            target["max_nav_ratio"] = max(target["max_nav_ratio"], float(row.get("max_nav_ratio", 0.0)))
    result = []
    for row in grouped.values():
        score = best_scores.get(row["stock_code"], 0)
        result.append(
            {
                "priority": min(row["priorities"], key=lambda value: PRIORITY_ORDER.get(value, 99)),
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "sw_level1": row["sw_level1"],
                "sw_level2": row["sw_level2"],
                "manager_count": len(row["managers"]),
                "managers": "、".join(sorted(row["managers"])),
                "p1_manager_count": len(row["p1_managers"]),
                "demand_occurrences": row["demand_occurrences"],
                "unique_fund_count": len(row["fund_codes"]),
                "fund_codes": "、".join(sorted(row["fund_codes"])),
                "holding_occurrences_sum": row["holding_occurrences_sum"],
                "market_value_10k_sum": round(row["market_value_10k_sum"], 2),
                "max_nav_ratio": row["max_nav_ratio"],
                "best_match_score": score,
                "match_status": _match_status(score),
                "matched_people": "、".join(sorted(name for name in match_people.get(row["stock_code"], set()) if name)),
            }
        )
    return sorted(result, key=lambda row: (PRIORITY_ORDER.get(row["priority"], 99), -row["manager_count"], -row["market_value_10k_sum"], row["stock_code"]))


def _person_rollup(match_details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in match_details:
        manager = row["manager"]
        key = (row.get("person_name", ""), row.get("organization", ""))
        target = grouped.setdefault(
            key,
            {
                "person_name": key[0],
                "organization": key[1],
                "job_title": row.get("job_title", ""),
                "source_group": row.get("source_group", ""),
                "expertise_tags": row.get("expertise_tags", ""),
                "region": row.get("region", ""),
                "managers": set(),
                "industry_targets": set(),
                "company_targets": set(),
                "exact_company_targets": set(),
                "level2_targets": set(),
                "candidate_targets": set(),
                "confirmed_candidate_targets": set(),
                "match_types": set(),
                "max_score": 0,
                "contact_permission": row.get("contact_permission", ""),
                "contact_info": row.get("contact_info", ""),
            },
        )
        target["managers"].add(manager)
        identity = f"{manager}:{row.get('target_code', '')}"
        if row.get("demand_type") == "行业":
            target["industry_targets"].add(row.get("target_code", ""))
        else:
            target["company_targets"].add(row.get("target_code", ""))
        if row.get("match_type") == "公司覆盖":
            target["exact_company_targets"].add(identity)
        if row.get("match_type") == "申万二级覆盖":
            target["level2_targets"].add(identity)
        if row.get("confirmation_status") == "待确认":
            target["candidate_targets"].add(identity)
        if row.get("original_confirmation_status") == "待确认" and row.get("confirmation_status") == "业务已确认":
            target["confirmed_candidate_targets"].add(identity)
        target["match_types"].add(row.get("match_type", ""))
        target["max_score"] = max(target["max_score"], int(row.get("score", 0)))
    result = []
    for row in grouped.values():
        result.append(
            {
                "person_name": row["person_name"],
                "organization": row["organization"],
                "job_title": row["job_title"],
                "source_group": row["source_group"],
                "expertise_tags": row["expertise_tags"],
                "region": row["region"],
                "manager_count": len(row["managers"]),
                "managers": "、".join(sorted(row["managers"])),
                "industry_target_count": len(row["industry_targets"]),
                "company_target_count": len(row["company_targets"]),
                "exact_company_match_count": len(row["exact_company_targets"]),
                "level2_match_count": len(row["level2_targets"]),
                "candidate_match_count": len(row["candidate_targets"]),
                "confirmed_candidate_match_count": len(row["confirmed_candidate_targets"]),
                "max_score": row["max_score"],
                "match_types": "、".join(sorted(value for value in row["match_types"] if value)),
                "contact_permission": row["contact_permission"],
                "contact_info": row["contact_info"],
            }
        )
    return sorted(result, key=lambda row: (-row["exact_company_match_count"], -row["level2_match_count"], -row["manager_count"], row["person_name"]))


def _match_details(loaded: list[tuple[ManagerEntry, dict[str, Any], Path]]) -> list[dict[str, Any]]:
    rows = [{"manager": entry.manager, **row} for entry, data, _ in loaded for row in data.get("matches", [])]
    return sorted(
        rows,
        key=lambda row: (
            PRIORITY_ORDER.get(row.get("priority", ""), 99),
            row.get("manager", ""),
            row.get("demand_type", ""),
            row.get("target_code", ""),
            -int(row.get("score", 0)),
            row.get("person_name", ""),
        ),
    )


def _excluded_rollup(loaded: list[tuple[ManagerEntry, dict[str, Any], Path]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for entry, data, _ in loaded:
        for row in data.get("excluded_demands", []):
            key = row["stock_code"]
            target = grouped.setdefault(
                key,
                {
                    "stock_code": key,
                    "stock_name": row.get("stock_name", ""),
                    "market": row.get("market", ""),
                    "sw_level1": row.get("sw_level1", ""),
                    "reason": row.get("reason", ""),
                    "managers": set(),
                    "fund_codes": set(),
                    "holding_occurrences_sum": 0,
                },
            )
            target["managers"].add(entry.manager)
            target["fund_codes"].update(_split_codes(row.get("fund_codes", "")))
            target["holding_occurrences_sum"] += int(row.get("holding_occurrences", 0))
    result = []
    for row in grouped.values():
        result.append(
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "market": row["market"],
                "sw_level1": row["sw_level1"],
                "manager_count": len(row["managers"]),
                "managers": "、".join(sorted(row["managers"])),
                "unique_fund_count": len(row["fund_codes"]),
                "fund_codes": "、".join(sorted(row["fund_codes"])),
                "holding_occurrences_sum": row["holding_occurrences_sum"],
                "reason": row["reason"],
            }
        )
    return sorted(result, key=lambda row: (-row["manager_count"], -row["holding_occurrences_sum"], row["stock_code"]))


def _split_codes(value: object) -> set[str]:
    return {part for part in str(value or "").replace("；", "、").replace(",", "、").split("、") if part}


def _match_status(score: int) -> str:
    if score >= 100:
        return "公司精确匹配"
    if score >= 70:
        return "二级行业精确匹配"
    if score >= 50:
        return "人工确认一级行业"
    if score >= 40:
        return "组级推定"
    if score > 0:
        return "候选待确认"
    return "待补充人员"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _candidate_snapshot_sha256(rows: list[dict[str, Any]]) -> str:
    keys = [
        {
            "manager": row.get("manager", ""),
            "demand_type": row.get("demand_type", ""),
            "target_code": row.get("target_code", ""),
            "person_name": row.get("person_name", ""),
            "organization": row.get("organization", ""),
            "score": row.get("score", 0),
        }
        for row in rows
    ]
    encoded = json.dumps(keys, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _single_or_multiple(values: Any) -> str:
    unique = sorted({str(value) for value in values if value})
    if not unique:
        return ""
    return unique[0] if len(unique) == 1 else "多项记录"
