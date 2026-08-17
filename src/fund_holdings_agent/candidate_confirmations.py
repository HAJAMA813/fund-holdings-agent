from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .io import clean_text


CONFIRMATION_COLUMNS = [
    "demand_type",
    "target_code",
    "target_name",
    "person_name",
    "organization",
    "decision",
    "confirmed_by",
    "confirmed_at_beijing",
    "source_report_date",
    "source_companies",
    "source_managers",
    "source_candidate_snapshot_sha256",
    "original_score",
    "match_type",
]


def confirmation_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        clean_text(row.get("demand_type")),
        clean_text(row.get("target_code")),
        clean_text(row.get("person_name")),
        clean_text(row.get("organization")),
    )


def read_candidate_confirmation_csv(path: Path | None) -> tuple[dict[tuple[str, str, str, str], dict[str, str]], list[dict[str, str]]]:
    if path is None or not path.exists():
        return {}, []
    records: dict[tuple[str, str, str, str], dict[str, str]] = {}
    issues: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(CONFIRMATION_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"候选确认规则库缺少列：{', '.join(sorted(missing))}")
        for row_no, raw in enumerate(reader, start=2):
            row = {column: clean_text(raw.get(column)) for column in CONFIRMATION_COLUMNS}
            if not any(row.values()):
                continue
            key = confirmation_key(row)
            if not all(key):
                issues.append({"severity": "错误", "row_no": str(row_no), "category": "确认主键缺失", "message": "需求类型、目标代码、人员姓名和机构均为必填"})
                continue
            if row["decision"] != "已确认":
                issues.append({"severity": "错误", "row_no": str(row_no), "category": "确认结论无效", "message": "decision 当前只允许‘已确认’"})
                continue
            if key in records:
                issues.append({"severity": "错误", "row_no": str(row_no), "category": "确认关系重复", "message": "同一需求、目标、人员和机构只能出现一次"})
                continue
            records[key] = row
    return records, issues


def build_candidate_confirmation_registry(input_paths: list[Path], output_path: Path) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    source_files: list[dict[str, str]] = []
    for input_path in input_paths:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        company = clean_text(summary.get("company"))
        report_date = clean_text(summary.get("report_date"))
        confirmation = data.get("candidate_confirmation", {})
        snapshot_sha = clean_text(confirmation.get("candidate_snapshot_sha256"))
        source_files.append({"path": str(input_path.resolve()), "sha256": _sha256(input_path), "company": company})
        for row in data.get("confirmed_candidate_items", []):
            if row.get("confirmation_status") != "业务已确认":
                continue
            key = confirmation_key(row)
            target = grouped.setdefault(
                key,
                {
                    "demand_type": key[0],
                    "target_code": key[1],
                    "target_name": clean_text(row.get("target_name")),
                    "person_name": key[2],
                    "organization": key[3],
                    "decision": "已确认",
                    "confirmed_by": clean_text(row.get("confirmed_by")) or clean_text(confirmation.get("confirmed_by")),
                    "confirmed_at_beijing": clean_text(row.get("confirmed_at_beijing")) or clean_text(confirmation.get("confirmed_at_beijing")),
                    "source_report_date": report_date,
                    "source_companies": set(),
                    "source_managers": set(),
                    "source_candidate_snapshot_sha256": set(),
                    "original_score": str(row.get("score", "")),
                    "match_type": clean_text(row.get("match_type")),
                },
            )
            target["source_companies"].add(company)
            target["source_managers"].add(clean_text(row.get("manager")))
            if snapshot_sha:
                target["source_candidate_snapshot_sha256"].add(snapshot_sha)

    rows = []
    for row in grouped.values():
        rows.append(
            {
                **row,
                "source_companies": "；".join(sorted(row["source_companies"])),
                "source_managers": "；".join(sorted(value for value in row["source_managers"] if value)),
                "source_candidate_snapshot_sha256": "；".join(sorted(row["source_candidate_snapshot_sha256"])),
            }
        )
    rows.sort(key=lambda row: (row["demand_type"], row["target_code"], row["person_name"], row["organization"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONFIRMATION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output_path)
    return {
        "output_file": str(output_path.resolve()),
        "output_sha256": _sha256(output_path),
        "input_file_count": len(input_paths),
        "confirmed_relation_count": len(rows),
        "industry_relation_count": sum(row["demand_type"] == "行业" for row in rows),
        "company_relation_count": sum(row["demand_type"] == "公司" for row in rows),
        "person_count": len({(row["person_name"], row["organization"]) for row in rows}),
        "source_files": source_files,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
