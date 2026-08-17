import json
from pathlib import Path

from fund_holdings_agent.company_resources import build_company_resource_packages


def _resource(manager: str, *, excluded: bool = False) -> dict:
    return {
        "summary": {
            "report_date": "2026-06-30",
            "industry_demand_count": 1,
            "company_demand_count": 1,
            "match_count": 2,
            "candidate_match_count": 0,
            "pending_count": 0,
            "excluded_non_sw_company_count": 1 if excluded else 0,
        },
        "industry_demands": [
            {"sw_level1": "石油石化", "fund_codes": "000001", "holding_count": 1, "market_value_10k": 100.0, "nav_ratio_sum": 0.05, "priority": "P3"}
        ],
        "company_demands": [
            {"stock_code": "601857.SH", "stock_name": "中国石油", "sw_level1": "石油石化", "sw_level2": "炼化及贸易", "fund_codes": "000001", "holding_occurrences": 1, "market_value_10k": 100.0, "max_nav_ratio": 0.05, "priority": "P3"}
        ],
        "matches": [
            {"demand_type": "行业", "priority": "P3", "target_code": "石油石化", "target_name": "石油石化", "sw_level1": "石油石化", "sw_level2": "", "match_type": "行业覆盖", "score": 50, "person_name": "示例研究员", "organization": "研究所", "job_title": "", "source_group": "石油", "expertise_tags": "石油", "region": "", "confirmation_status": "已确认", "contact_permission": "需审批", "contact_info": "已隐藏"},
            {"demand_type": "公司", "priority": "P3", "target_code": "601857.SH", "target_name": "中国石油", "sw_level1": "石油石化", "sw_level2": "炼化及贸易", "match_type": "公司覆盖", "score": 100, "person_name": "示例研究员", "organization": "研究所", "job_title": "", "source_group": "石油", "expertise_tags": "石油", "region": "", "confirmation_status": "已确认", "contact_permission": "需审批", "contact_info": "已隐藏"},
        ],
        "pending_items": [],
        "excluded_demands": [
            {"stock_code": "00700.HK", "stock_name": "腾讯控股", "market": "港股", "sw_level1": "不适用", "fund_codes": "000001", "holding_occurrences": 1, "reason": "当前不考虑港股"}
        ] if excluded else [],
    }


def test_company_resource_aggregation_groups_managers_and_preserves_audit(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n甲基金管理有限公司,经理甲,101,yes\n甲基金管理有限公司,经理乙,202,yes\n",
        encoding="utf-8",
    )
    input_root = tmp_path / "portfolio"
    for manager, excluded in (("经理甲", True), ("经理乙", False)):
        directory = input_root / "甲基金" / f"{manager}_2026Q2"
        directory.mkdir(parents=True)
        (directory / "resource_matching_data.json").write_text(json.dumps(_resource(manager, excluded=excluded), ensure_ascii=False), encoding="utf-8")

    result = build_company_resource_packages(roster, input_root, "2026-06-30", tmp_path / "reports")
    data = json.loads(Path(result["companies"][0]["data_path"]).read_text(encoding="utf-8"))

    assert result["overall_status"] == "completed"
    assert data["summary"]["manager_count"] == 2
    assert data["summary"]["company_demand_count_sum"] == 2
    assert data["summary"]["unique_company_count"] == 1
    assert data["company_rollup"][0]["manager_count"] == 2
    assert data["company_rollup"][0]["matched_people"] == "示例研究员"
    assert data["company_rollup"][0]["match_status"] == "公司精确匹配"
    assert data["person_rollup"][0]["exact_company_match_count"] == 2
    assert data["excluded_rollup"][0]["stock_code"] == "00700.HK"


def test_company_resource_aggregation_reports_missing_manager_input(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n甲基金管理有限公司,经理甲,101,yes\n甲基金管理有限公司,经理乙,202,yes\n",
        encoding="utf-8",
    )
    directory = tmp_path / "portfolio" / "甲基金" / "经理甲_2026Q2"
    directory.mkdir(parents=True)
    (directory / "resource_matching_data.json").write_text(json.dumps(_resource("经理甲"), ensure_ascii=False), encoding="utf-8")

    result = build_company_resource_packages(roster, tmp_path / "portfolio", "2026-06-30", tmp_path / "reports")
    data = json.loads(Path(result["companies"][0]["data_path"]).read_text(encoding="utf-8"))

    assert result["overall_status"] == "completed_with_errors"
    assert data["summary"]["completed_manager_count"] == 1
    assert data["summary"]["failed_manager_count"] == 1
    assert data["manager_overview"][1]["status"] == "failed"


def test_company_resource_aggregation_can_confirm_candidate_snapshot(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n甲基金管理有限公司,经理甲,101,yes\n",
        encoding="utf-8",
    )
    resource = _resource("经理甲")
    resource["summary"]["candidate_match_count"] = 1
    resource["matches"][0]["score"] = 30
    resource["matches"][0]["match_type"] = "研究分组候选覆盖"
    resource["matches"][0]["confirmation_status"] = "待确认"
    directory = tmp_path / "portfolio" / "甲基金" / "经理甲_2026Q2"
    directory.mkdir(parents=True)
    (directory / "resource_matching_data.json").write_text(json.dumps(resource, ensure_ascii=False), encoding="utf-8")

    result = build_company_resource_packages(
        roster,
        tmp_path / "portfolio",
        "2026-06-30",
        tmp_path / "reports",
        confirm_all_candidates=True,
        confirmed_by="业务用户",
    )
    data = json.loads(Path(result["companies"][0]["data_path"]).read_text(encoding="utf-8"))

    assert data["summary"]["source_candidate_match_count_sum"] == 1
    assert data["summary"]["confirmed_candidate_match_count_sum"] == 1
    assert data["summary"]["candidate_match_count_sum"] == 0
    assert data["candidate_items"] == []
    assert data["confirmed_candidate_items"][0]["confirmation_status"] == "业务已确认"
    assert data["confirmed_candidate_items"][0]["score"] == 30
    assert data["candidate_confirmation"]["confirmed_by"] == "业务用户"
    assert len(data["candidate_confirmation"]["candidate_snapshot_sha256"]) == 64


def test_company_resource_aggregation_records_confirmation_registry_hash(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n甲基金管理有限公司,经理甲,101,yes\n",
        encoding="utf-8",
    )
    registry = tmp_path / "candidate_confirmations.csv"
    registry.write_text("demand_type,target_code\n行业,电子\n", encoding="utf-8")
    resource = _resource("经理甲")
    resource["confirmation_registry_source"] = str(registry)
    directory = tmp_path / "portfolio" / "甲基金" / "经理甲_2026Q2"
    directory.mkdir(parents=True)
    (directory / "resource_matching_data.json").write_text(json.dumps(resource, ensure_ascii=False), encoding="utf-8")

    result = build_company_resource_packages(roster, tmp_path / "portfolio", "2026-06-30", tmp_path / "reports")
    data = json.loads(Path(result["companies"][0]["data_path"]).read_text(encoding="utf-8"))

    registry_file = data["candidate_confirmation"]["registry_files"][0]
    assert registry_file["path"] == str(registry.resolve())
    assert registry_file["status"] == "loaded"
    assert len(registry_file["sha256"]) == 64
