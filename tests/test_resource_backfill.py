import json
from pathlib import Path

from fund_holdings_agent.resource_backfill import backfill_portfolio_resources


def _industry_data(report_date: str = "2026-06-30") -> dict:
    return {
        "summary": {"report_date": report_date},
        "industry_summary": [
            {
                "fund_code": "000001",
                "sw_level1": "电子",
                "holding_count": 1,
                "market_value_10k": 100.0,
                "nav_ratio": 0.05,
            }
        ],
        "formal_holdings_industry": [
            {
                "fund_code": "000001",
                "stock_code": "688001.SH",
                "stock_name": "测试公司",
                "sw_level1": "电子",
                "market_value_10k": 100.0,
                "nav_ratio": 0.05,
            }
        ],
    }


def _personnel(path: Path) -> None:
    path.write_text(
        "person_name,organization,person_type,sw_level1,covered_stock_codes,expertise_tags,region,current_status,contact_permission,contact_info\n"
        "甲,研究所,研究员,电子,,,上海,在岗,需审批,secret\n",
        encoding="utf-8-sig",
    )


def test_backfill_updates_all_existing_manager_resource_outputs(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n"
        "甲基金管理有限公司,经理甲,101,yes\n"
        "乙基金管理有限公司,经理乙,202,yes\n",
        encoding="utf-8",
    )
    personnel = tmp_path / "people.csv"
    _personnel(personnel)
    output_root = tmp_path / "portfolio"
    for company_dir, manager in (("甲基金", "经理甲"), ("乙基金", "经理乙")):
        manager_dir = output_root / company_dir / f"{manager}_2026Q2"
        manager_dir.mkdir(parents=True)
        (manager_dir / "industry_analysis_data.json").write_text(
            json.dumps(_industry_data(), ensure_ascii=False),
            encoding="utf-8",
        )

    result = backfill_portfolio_resources(roster, output_root, "2026-06-30", personnel)

    assert result["overall_status"] == "completed"
    assert result["completed_manager_count"] == 2
    assert result["match_count_sum"] == 4
    assert len(result["company_metrics"]) == 2
    assert result["company_metrics"][0]["confirmed_candidate_match_count_sum"] == 0
    for company_dir, manager in (("甲基金", "经理甲"), ("乙基金", "经理乙")):
        data = json.loads((output_root / company_dir / f"{manager}_2026Q2" / "resource_matching_data.json").read_text(encoding="utf-8"))
        assert data["summary"]["match_count"] == 2
        assert all(row["contact_info"] == "已隐藏" for row in data["matches"])


def test_backfill_continues_when_one_manager_input_is_missing(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n"
        "甲基金管理有限公司,经理甲,101,yes\n"
        "甲基金管理有限公司,经理乙,202,yes\n",
        encoding="utf-8",
    )
    personnel = tmp_path / "people.csv"
    _personnel(personnel)
    manager_dir = tmp_path / "portfolio" / "甲基金" / "经理甲_2026Q2"
    manager_dir.mkdir(parents=True)
    (manager_dir / "industry_analysis_data.json").write_text(json.dumps(_industry_data()), encoding="utf-8")

    result = backfill_portfolio_resources(roster, tmp_path / "portfolio", "2026-06-30", personnel)

    assert result["overall_status"] == "completed_with_errors"
    assert result["completed_manager_count"] == 1
    assert result["failed_manager_count"] == 1
    assert result["manager_results"][1]["error"] == "缺少 industry_analysis_data.json"


def test_backfill_aggregates_excluded_non_sw_company_demands(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text("company,manager,manager_id,active\n甲基金管理有限公司,经理甲,101,yes\n", encoding="utf-8")
    personnel = tmp_path / "people.csv"
    _personnel(personnel)
    manager_dir = tmp_path / "portfolio" / "甲基金" / "经理甲_2026Q2"
    manager_dir.mkdir(parents=True)
    data = _industry_data()
    data["formal_holdings_industry"].append(
        {
            "fund_code": "000001",
            "stock_code": "00700.HK",
            "stock_name": "腾讯控股",
            "sw_level1": "不适用",
            "market_value_10k": 50.0,
            "nav_ratio": 0.02,
        }
    )
    (manager_dir / "industry_analysis_data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = backfill_portfolio_resources(roster, tmp_path / "portfolio", "2026-06-30", personnel)

    assert result["excluded_non_sw_company_count_sum"] == 1
    assert result["excluded_non_sw_unique_company_count"] == 1
    assert result["excluded_non_sw_manager_count"] == 1
    assert result["excluded_non_sw_companies"][0]["stock_code"] == "00700.HK"
    assert result["non_sw_company_pending_count"] == 0
