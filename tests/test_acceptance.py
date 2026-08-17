import json
import zipfile
from pathlib import Path

from fund_holdings_agent.acceptance import EXPECTED_RESOURCE_SHEETS, build_phase1_acceptance


def _write_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sorted(EXPECTED_RESOURCE_SHEETS), start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')


def test_phase1_acceptance_reconciles_sources_and_workbook(tmp_path: Path):
    (tmp_path / "src" / "fund_holdings_agent").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    for relative in ("pyproject.toml", "README.md", "需求文档.md", "docs/phase1_audit.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("验收测试", encoding="utf-8")
    roster = tmp_path / "data" / "managers_portfolio.csv"
    roster.parent.mkdir()
    roster.write_text("company,manager,manager_id,active\n甲基金管理有限公司,经理甲,101,yes\n", encoding="utf-8")
    registry = tmp_path / "data" / "resource_candidate_confirmations.csv"
    registry.write_text("demand_type,target_code,person_name,organization\n公司,000001.SZ,研究员甲,研究所\n", encoding="utf-8-sig")

    company_dir = tmp_path / "reports" / "甲基金"
    company_data_path = company_dir / "甲基金_2026Q2_研究资源汇总_data.json"
    company_dir.mkdir(parents=True)
    candidate = {
        "match_type": "研究分组候选覆盖",
        "score": 30,
        "confirmation_status": "业务已确认",
        "original_confirmation_status": "待确认",
        "contact_permission": "需审批",
        "contact_info": "已隐藏",
    }
    company_data = {
        "summary": {
            "quarter": "2026Q2",
            "manager_count": 1,
            "completed_manager_count": 1,
            "industry_demand_count_sum": 1,
            "company_demand_count_sum": 1,
            "match_count_sum": 1,
            "source_candidate_match_count_sum": 1,
            "confirmed_candidate_match_count_sum": 1,
            "candidate_match_count_sum": 0,
            "pending_count_sum": 0,
        },
        "confirmed_candidate_items": [candidate],
        "match_details": [candidate],
    }
    company_data_path.write_text(json.dumps(company_data, ensure_ascii=False), encoding="utf-8")
    workbook_path = company_dir / "甲基金_2026Q2_研究资源对接汇总.xlsx"
    _write_workbook(workbook_path)

    backfill = {
        "report_date": "2026-06-30",
        "quarter": "2026Q2",
        "manager_count": 1,
        "completed_manager_count": 1,
        "failed_manager_count": 0,
        "candidate_confirmation_relation_count": 1,
        "candidate_confirmation_sha256": __import__("hashlib").sha256(registry.read_bytes()).hexdigest(),
        "candidate_confirmation_error_count": 0,
        "confirmed_candidate_match_count_sum": 1,
        "candidate_match_count_sum": 0,
        "pending_count_sum": 0,
        "industry_demand_count_sum": 1,
        "company_demand_count_sum": 1,
        "match_count_sum": 1,
        "excluded_non_sw_company_count_sum": 0,
        "company_metrics": [
            {
                "company": "甲基金管理有限公司",
                "manager_count": 1,
                "completed_manager_count": 1,
                "industry_demand_count_sum": 1,
                "company_demand_count_sum": 1,
                "match_count_sum": 1,
                "source_candidate_match_count_sum": 1,
                "confirmed_candidate_match_count_sum": 1,
                "candidate_match_count_sum": 0,
                "pending_count_sum": 0,
            }
        ],
    }
    backfill_path = tmp_path / "backfill.json"
    backfill_path.write_text(json.dumps(backfill, ensure_ascii=False), encoding="utf-8")
    company_summary_path = tmp_path / "company_summary.json"
    company_summary_path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "company": "甲基金管理有限公司",
                        "data_path": str(company_data_path),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_phase1_acceptance(
        tmp_path,
        roster,
        backfill_path,
        company_summary_path,
        registry,
        tmp_path / "acceptance.json",
        {"passed": True, "summary": "1 passed"},
    )

    assert result["overall_status"] == "accepted_with_caveats"
    assert result["failed_check_count"] == 0
    assert result["metrics"]["confirmed_candidate_match_count_sum"] == 1
    assert result["workbooks"][0]["valid"] is True
