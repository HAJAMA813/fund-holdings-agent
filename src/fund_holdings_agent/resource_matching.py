from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .candidate_confirmations import confirmation_key
from .io import clean_text


PERSONNEL_COLUMNS = [
    "person_name",
    "organization",
    "person_type",
    "sw_level1",
    "covered_stock_codes",
    "expertise_tags",
    "region",
    "current_status",
    "contact_permission",
    "contact_info",
]
OPTIONAL_PERSONNEL_COLUMNS = [
    "job_title",
    "source_group",
    "source_date",
    "covered_sw_level2",
    "coverage_basis",
    "industry_mapping_status",
    "mapping_note",
    "status_basis",
    "source_row",
]
PERSON_TYPES = {"研究员", "专家"}
PERSON_STATUSES = {"在岗", "离岗", "暂停"}
CONTACT_PERMISSIONS = {"允许", "需审批", "不允许"}
NON_MATCHABLE_SW_LABELS = {"", "不适用", "申万不适用", "待核查"}


@dataclass
class Person:
    person_name: str
    organization: str
    person_type: str
    sw_level1: tuple[str, ...]
    covered_stock_codes: tuple[str, ...]
    expertise_tags: str
    region: str
    current_status: str
    contact_permission: str
    contact_info: str
    job_title: str = ""
    source_group: str = ""
    source_date: str = ""
    covered_sw_level2: tuple[str, ...] = ()
    coverage_basis: str = "人工维护"
    industry_mapping_status: str = "已确认"
    mapping_note: str = ""
    status_basis: str = ""
    source_row: str = ""


def _split(value: object) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part for part in re.split(r"[,，、;；]+", clean_text(value)) if part))


def read_personnel_csv(path: Path) -> tuple[list[Person], list[dict[str, str]]]:
    people: list[Person] = []
    issues: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(PERSONNEL_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"人员库缺少列：{', '.join(sorted(missing))}")
        seen: set[tuple[str, str]] = set()
        for row_no, row in enumerate(reader, start=2):
            if not any(clean_text(row.get(column)) for column in PERSONNEL_COLUMNS):
                continue
            name = clean_text(row.get("person_name"))
            organization = clean_text(row.get("organization"))
            person_type = clean_text(row.get("person_type"))
            industries = _split(row.get("sw_level1"))
            status = clean_text(row.get("current_status"))
            permission = clean_text(row.get("contact_permission"))
            key = (name, organization)
            if not name or not organization or not person_type or not status or not permission:
                issues.append(_person_issue("错误", "人员必填字段缺失", row_no, name, organization, "姓名、机构、类型、状态和联系权限均为必填"))
                continue
            if key in seen:
                issues.append(_person_issue("错误", "人员重复", row_no, name, organization, "姓名+机构重复"))
                continue
            if person_type not in PERSON_TYPES:
                issues.append(_person_issue("错误", "人员类型无效", row_no, name, organization, f"应为：{'/'.join(sorted(PERSON_TYPES))}"))
                continue
            if status not in PERSON_STATUSES:
                issues.append(_person_issue("错误", "人员状态无效", row_no, name, organization, f"应为：{'/'.join(sorted(PERSON_STATUSES))}"))
                continue
            if permission not in CONTACT_PERMISSIONS:
                issues.append(_person_issue("错误", "联系权限无效", row_no, name, organization, f"应为：{'/'.join(sorted(CONTACT_PERMISSIONS))}"))
                continue
            if not industries:
                issues.append(_person_issue("警告", "人员未映射申万行业", row_no, name, organization, "人员记录保留，但不会参与申万一级行业自动匹配"))
            seen.add(key)
            people.append(
                Person(
                    person_name=name,
                    organization=organization,
                    person_type=person_type,
                    sw_level1=industries,
                    covered_stock_codes=_split(row.get("covered_stock_codes")),
                    expertise_tags=clean_text(row.get("expertise_tags")),
                    region=clean_text(row.get("region")),
                    current_status=status,
                    contact_permission=permission,
                    contact_info=clean_text(row.get("contact_info")),
                    job_title=clean_text(row.get("job_title")),
                    source_group=clean_text(row.get("source_group")),
                    source_date=clean_text(row.get("source_date")),
                    covered_sw_level2=_split(row.get("covered_sw_level2")),
                    coverage_basis=clean_text(row.get("coverage_basis")) or "人工维护",
                    industry_mapping_status=clean_text(row.get("industry_mapping_status")) or "已确认",
                    mapping_note=clean_text(row.get("mapping_note")),
                    status_basis=clean_text(row.get("status_basis")),
                    source_row=clean_text(row.get("source_row")),
                )
            )
    return people, issues


def build_resource_matching(
    industry_data: dict[str, Any],
    people: list[Person],
    personnel_issues: list[dict[str, str]],
    candidate_confirmations: dict[tuple[str, str, str, str], dict[str, str]] | None = None,
    confirmation_issues: list[dict[str, str]] | None = None,
    confirmation_source: str = "",
) -> dict[str, Any]:
    industry_demands = _industry_demands(industry_data)
    company_demands = _company_demands(industry_data)
    excluded_demands = _excluded_company_demands(industry_data)
    matches: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    active_people = [person for person in people if person.current_status == "在岗"]
    candidate_confirmations = candidate_confirmations or {}
    confirmation_issues = confirmation_issues or []

    for demand in industry_demands:
        candidates = [_industry_match(person, demand["sw_level1"]) for person in active_people]
        candidates = [candidate for candidate in candidates if candidate is not None]
        if not candidates:
            pending.append(_pending("行业", demand["priority"], demand["sw_level1"], demand["sw_level1"], "缺少覆盖该申万一级行业的在岗人员", demand["sw_level1"]))
        for score, match_type, confirmation_status, person in sorted(candidates, key=lambda item: (-item[0], item[3].person_type != "研究员", item[3].organization, item[3].person_name)):
            matches.append(_match("行业", demand["priority"], demand["sw_level1"], demand["sw_level1"], match_type, score, person, confirmation_status=confirmation_status))

    for demand in company_demands:
        exact_candidates = [(100, "公司覆盖", "已确认", person) for person in active_people if demand["stock_code"] in person.covered_stock_codes]
        level2_candidates = [(70, "申万二级覆盖", "已确认", person) for person in active_people if demand.get("sw_level2") and demand["sw_level2"] in person.covered_sw_level2]
        if exact_candidates:
            candidates = exact_candidates
        elif level2_candidates:
            candidates = level2_candidates
        else:
            candidates = []
            for person in active_people:
                industry_match = _industry_match(person, demand["sw_level1"])
                if industry_match is not None:
                    candidates.append(industry_match)
        if not candidates:
            pending.append(_pending("公司", demand["priority"], demand["stock_code"], demand["stock_name"], f"缺少覆盖 {demand['sw_level1']} 或该公司的在岗人员", demand["sw_level1"]))
        for score, match_type, confirmation_status, person in sorted(candidates, key=lambda item: (-item[0], item[3].organization, item[3].person_name)):
            matches.append(_match("公司", demand["priority"], demand["stock_code"], demand["stock_name"], match_type, score, person, demand["sw_level1"], demand.get("sw_level2", ""), confirmation_status))

    source_candidate_count = sum(row["confirmation_status"] == "待确认" for row in matches)
    for row in matches:
        if row["confirmation_status"] != "待确认":
            continue
        confirmation = candidate_confirmations.get(confirmation_key(row))
        if confirmation is None:
            continue
        row["original_confirmation_status"] = "待确认"
        row["confirmation_status"] = "业务已确认"
        row["confirmed_by"] = confirmation["confirmed_by"]
        row["confirmed_at_beijing"] = confirmation["confirmed_at_beijing"]
        row["confirmation_registry_source"] = confirmation_source

    summary = {
        "report_date": industry_data["summary"]["report_date"],
        "personnel_count": len(people),
        "active_personnel_count": len(active_people),
        "industry_demand_count": len(industry_demands),
        "company_demand_count": len(company_demands),
        "match_count": len(matches),
        "pending_count": len(pending),
        "excluded_non_sw_company_count": len(excluded_demands),
        "personnel_error_count": sum(issue["severity"] == "错误" for issue in personnel_issues),
        "personnel_warning_count": sum(issue["severity"] == "警告" for issue in personnel_issues),
        "group_inferred_match_count": sum(row["coverage_basis"] == "研究分组映射" for row in matches),
        "source_candidate_match_count": source_candidate_count,
        "confirmed_candidate_match_count": sum(row["confirmation_status"] == "业务已确认" for row in matches),
        "candidate_match_count": sum(row["confirmation_status"] == "待确认" for row in matches),
        "confirmation_registry_count": len(candidate_confirmations),
        "confirmation_registry_error_count": sum(issue.get("severity") == "错误" for issue in confirmation_issues),
        "status": (
            "待提供内部人员库"
            if not people
            else (
                "人员库存在错误"
                if any(issue["severity"] == "错误" for issue in personnel_issues)
                else (
                    "候选确认规则库存在错误"
                    if any(issue.get("severity") == "错误" for issue in confirmation_issues)
                    else ("匹配完成（含待确认项）" if any(row["confirmation_status"] == "待确认" for row in matches) else "匹配完成")
                )
            )
        ),
    }
    return {
        "summary": summary,
        "industry_demands": industry_demands,
        "company_demands": company_demands,
        "matches": matches,
        "pending_items": pending,
        "excluded_demands": excluded_demands,
        "personnel_issues": personnel_issues,
        "confirmation_issues": confirmation_issues,
        "confirmation_registry_source": confirmation_source,
        "personnel_rows": [_person_dict(person) for person in people],
        "rules": [
            {"item": "行业需求优先级", "rule": "覆盖2只基金或重仓记录≥4为P1；记录2-3为P2；其余P3"},
            {"item": "公司需求优先级", "rule": "被2只基金共同持有或单基金净值比例≥8%为P1；≥4%为P2；其余P3"},
            {"item": "匹配顺序", "rule": "明确覆盖公司得100分且不再追加宽泛行业候选；申万二级覆盖得70分；人工维护一级行业覆盖得50分；研究分组映射得40分；宽口径候选映射得30分"},
            {"item": "非申万公司", "rule": "港股等申万不适用公司当前不进入研究资源匹配，但保留在 excluded_demands 供审计"},
            {"item": "研究分组映射", "rule": "通讯录仅能证明人员隶属研究分组，不能证明个人已覆盖具体公司；组级映射必须保留覆盖依据与确认状态"},
            {"item": "联系信息", "rule": "联系权限为‘允许’才在匹配结果显示联系方式；‘需审批/不允许’均隐藏"},
            {"item": "模型调用", "rule": "不调用DeepSeek或其他大模型，不根据标签猜测人员能力"},
            {"item": "候选确认规则库", "rule": "规则库只把已出现的同一人员－行业／公司候选标记为业务已确认；原30分和匹配方式保持不变，不提升为精确覆盖"},
        ],
    }


def _industry_demands(data: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in data["industry_summary"]:
        if row["sw_level1"] in NON_MATCHABLE_SW_LABELS:
            continue
        target = grouped.setdefault(row["sw_level1"], {"sw_level1": row["sw_level1"], "fund_codes": set(), "holding_count": 0, "market_value_10k": 0.0, "nav_ratio_sum": 0.0})
        target["fund_codes"].add(row["fund_code"])
        target["holding_count"] += row["holding_count"]
        target["market_value_10k"] += row["market_value_10k"]
        target["nav_ratio_sum"] += row["nav_ratio"]
    result = []
    for row in grouped.values():
        fund_count = len(row["fund_codes"])
        priority = "P1" if fund_count >= 2 or row["holding_count"] >= 4 else ("P2" if row["holding_count"] >= 2 else "P3")
        result.append({**row, "fund_codes": "、".join(sorted(row["fund_codes"])), "fund_count": fund_count, "priority": priority})
    return sorted(result, key=lambda row: (row["priority"], -row["fund_count"], -row["holding_count"], row["sw_level1"]))


def _company_demands(data: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in data["formal_holdings_industry"]:
        if row["sw_level1"] in NON_MATCHABLE_SW_LABELS:
            continue
        target = grouped.setdefault(row["stock_code"], {"stock_code": row["stock_code"], "stock_name": row["stock_name"], "sw_level1": row["sw_level1"], "sw_level2": row.get("sw_level2", ""), "fund_codes": set(), "holding_occurrences": 0, "market_value_10k": 0.0, "max_nav_ratio": 0.0})
        target["fund_codes"].add(row["fund_code"])
        target["holding_occurrences"] += 1
        target["market_value_10k"] += row.get("market_value_10k") or 0
        target["max_nav_ratio"] = max(target["max_nav_ratio"], row.get("nav_ratio") or 0)
    result = []
    for row in grouped.values():
        fund_count = len(row["fund_codes"])
        priority = "P1" if fund_count >= 2 or row["max_nav_ratio"] >= 0.08 else ("P2" if row["max_nav_ratio"] >= 0.04 else "P3")
        result.append({**row, "fund_codes": "、".join(sorted(row["fund_codes"])), "fund_count": fund_count, "priority": priority})
    return sorted(result, key=lambda row: (row["priority"], -row["fund_count"], -row["max_nav_ratio"], row["stock_code"]))


def _excluded_company_demands(data: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in data["formal_holdings_industry"]:
        if row["sw_level1"] not in NON_MATCHABLE_SW_LABELS:
            continue
        target = grouped.setdefault(
            row["stock_code"],
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "market": row.get("market", ""),
                "sw_level1": row["sw_level1"],
                "fund_codes": set(),
                "holding_occurrences": 0,
                "reason": "当前业务口径暂不考虑港股及其他申万不适用公司",
            },
        )
        target["fund_codes"].add(row["fund_code"])
        target["holding_occurrences"] += 1
    return sorted(
        [
            {**row, "fund_codes": "、".join(sorted(row["fund_codes"])), "fund_count": len(row["fund_codes"])}
            for row in grouped.values()
        ],
        key=lambda row: (-row["fund_count"], -row["holding_occurrences"], row["stock_code"]),
    )


def _industry_match(person: Person, sw_level1: str) -> tuple[int, str, str, Person] | None:
    if sw_level1 not in person.sw_level1:
        return None
    if person.coverage_basis == "研究分组映射":
        if person.industry_mapping_status == "候选映射":
            return 30, "研究分组候选覆盖", "待确认", person
        return 40, "研究分组覆盖", "组级推定", person
    return 50, "行业覆盖", "已确认", person


def _match(demand_type: str, priority: str, target_code: str, target_name: str, match_type: str, score: int, person: Person, sw_level1: str = "", sw_level2: str = "", confirmation_status: str = "已确认") -> dict[str, Any]:
    return {
        "demand_type": demand_type,
        "priority": priority,
        "target_code": target_code,
        "target_name": target_name,
        "sw_level1": sw_level1 or target_name,
        "sw_level2": sw_level2,
        "match_type": match_type,
        "score": score,
        "person_name": person.person_name,
        "organization": person.organization,
        "person_type": person.person_type,
        "job_title": person.job_title,
        "source_group": person.source_group,
        "expertise_tags": person.expertise_tags,
        "region": person.region,
        "coverage_basis": person.coverage_basis,
        "industry_mapping_status": person.industry_mapping_status,
        "confirmation_status": confirmation_status,
        "contact_permission": person.contact_permission,
        "contact_info": person.contact_info if person.contact_permission == "允许" else "已隐藏",
    }


def _pending(demand_type: str, priority: str, target_code: str, target_name: str, reason: str, sw_level1: str = "") -> dict[str, str]:
    return {"demand_type": demand_type, "priority": priority, "target_code": target_code, "target_name": target_name, "sw_level1": sw_level1, "reason": reason, "action": "补充人员库后重新运行匹配"}


def _person_issue(severity: str, category: str, row_no: int, name: str, organization: str, message: str) -> dict[str, str]:
    return {"severity": severity, "category": category, "row_no": str(row_no), "person_name": name, "organization": organization, "message": message, "action": "修复人员库后重跑"}


def _person_dict(person: Person) -> dict[str, str]:
    return {
        "person_name": person.person_name,
        "organization": person.organization,
        "person_type": person.person_type,
        "sw_level1": "；".join(person.sw_level1),
        "covered_stock_codes": "；".join(person.covered_stock_codes),
        "expertise_tags": person.expertise_tags,
        "region": person.region,
        "current_status": person.current_status,
        "contact_permission": person.contact_permission,
        "contact_info": person.contact_info,
        "job_title": person.job_title,
        "source_group": person.source_group,
        "source_date": person.source_date,
        "covered_sw_level2": "；".join(person.covered_sw_level2),
        "coverage_basis": person.coverage_basis,
        "industry_mapping_status": person.industry_mapping_status,
        "mapping_note": person.mapping_note,
        "status_basis": person.status_basis,
        "source_row": person.source_row,
    }


def save_resource_json(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
