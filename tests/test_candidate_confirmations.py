import csv
import json
from pathlib import Path

from fund_holdings_agent.candidate_confirmations import (
    build_candidate_confirmation_registry,
    read_candidate_confirmation_csv,
)


def _company_payload(company: str, manager: str) -> dict:
    return {
        "summary": {"company": company, "report_date": "2026-06-30"},
        "candidate_confirmation": {
            "confirmed_by": "业务用户",
            "confirmed_at_beijing": "2026-08-15T15:13:10+08:00",
            "candidate_snapshot_sha256": "a" * 64,
        },
        "confirmed_candidate_items": [
            {
                "manager": manager,
                "demand_type": "公司",
                "target_code": "000001.SZ",
                "target_name": "示例公司",
                "person_name": "研究员甲",
                "organization": "研究所",
                "confirmation_status": "业务已确认",
                "confirmed_by": "业务用户",
                "confirmed_at_beijing": "2026-08-15T15:13:10+08:00",
                "score": 30,
                "match_type": "研究分组候选覆盖",
            }
        ],
    }


def test_registry_deduplicates_confirmed_relationships_and_preserves_sources(tmp_path: Path):
    inputs = []
    for company, manager in (("甲基金", "经理甲"), ("乙基金", "经理乙")):
        path = tmp_path / f"{company}.json"
        path.write_text(json.dumps(_company_payload(company, manager), ensure_ascii=False), encoding="utf-8")
        inputs.append(path)
    output = tmp_path / "confirmations.csv"

    summary = build_candidate_confirmation_registry(inputs, output)
    records, issues = read_candidate_confirmation_csv(output)

    assert summary["confirmed_relation_count"] == 1
    assert summary["company_relation_count"] == 1
    assert issues == []
    record = next(iter(records.values()))
    assert record["source_companies"] == "乙基金；甲基金"
    assert record["source_managers"] == "经理乙；经理甲"
    assert record["original_score"] == "30"


def test_registry_reports_duplicate_manual_rows(tmp_path: Path):
    path = tmp_path / "confirmations.csv"
    headers = [
        "demand_type", "target_code", "target_name", "person_name", "organization", "decision",
        "confirmed_by", "confirmed_at_beijing", "source_report_date", "source_companies",
        "source_managers", "source_candidate_snapshot_sha256", "original_score", "match_type",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        row = {
            "demand_type": "行业", "target_code": "电子", "target_name": "电子", "person_name": "研究员甲",
            "organization": "研究所", "decision": "已确认", "confirmed_by": "业务用户",
            "confirmed_at_beijing": "2026-08-15T15:13:10+08:00", "source_report_date": "2026-06-30",
            "source_companies": "甲基金", "source_managers": "经理甲", "source_candidate_snapshot_sha256": "a" * 64,
            "original_score": "30", "match_type": "研究分组候选覆盖",
        }
        writer.writerow(row)
        writer.writerow(row)

    records, issues = read_candidate_confirmation_csv(path)

    assert len(records) == 1
    assert issues[0]["category"] == "确认关系重复"
