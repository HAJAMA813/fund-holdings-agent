import sqlite3
from pathlib import Path

from fund_holdings_agent.history import history_status, ingest_comparison, ingest_quarter


def _pipeline(report_date: str, shares: float):
    holding = {
        "fund_code": "000001",
        "fund_name": "测试基金A",
        "manager": "测试经理",
        "report_date": report_date,
        "rank": 1,
        "stock_code": "600000.SH",
        "stock_name": "浦发银行",
        "shares_10k": shares,
        "market_value_10k": shares * 10,
        "nav_ratio": 0.05,
        "market": "A股",
        "source_url": "https://example.test/holding",
        "duplicate_group": "",
        "representative": "是",
    }
    return {
        "summary": {
            "report_date": report_date,
            "input_funds": 1,
            "selected_funds": 1,
            "successful_funds": 1,
            "formal_funds": 1,
            "raw_holding_rows": 1,
            "formal_holding_rows": 1,
            "issue_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "success_rate": 1.0,
            "duplicate_product_count": 0,
        },
        "funds": [
            {
                "manager": "测试经理",
                "fund_code": "000001",
                "fund_name": "测试基金A",
                "fund_type": "混合型",
                "inception_date": "2020-01-01",
                "selected": True,
                "selection_reason": "纳入",
                "verified_manager": "测试经理",
                "manager_status": "一致",
                "manager_source_url": "https://example.test/manager",
                "fetch_status": "已抓取",
            }
        ],
        "all_holdings": [holding],
        "formal_holdings": [holding],
        "issues": [],
        "sources": [{"item": "持仓", "url": "https://example.test", "note": "测试"}],
    }


def _industry(report_date: str):
    return {
        "industry_quality": {
            "snapshot_date": "2026-08-14",
            "standard": "申万行业分类标准2021",
            "holding_coverage": 1.0,
            "historical_point_in_time": False,
        },
        "stock_industry_mapping": [
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "market": "A股",
                "sw_level1": "银行",
                "sw_level2": "股份制银行Ⅱ",
                "sw_level2_code": "801783.SI",
                "classification_status": "当前快照已匹配",
                "source_url": "https://example.test/industry",
                "industry_source_id": "IND001",
                "industry_snapshot_date": "2026-08-14",
            }
        ],
        "all_holdings_industry": [
            {
                "fund_code": "000001",
                "rank": 1,
                "stock_code": "600000.SH",
                "representative": "是",
                "sw_level1": "银行",
                "sw_level2": "股份制银行Ⅱ",
                "sw_level2_code": "801783.SI",
                "industry_snapshot_date": "2026-08-14",
                "industry_status": "当前快照已匹配",
                "industry_source_id": "IND001",
                "industry_source_url": "https://example.test/industry",
            }
        ],
        "industry_summary": [
            {
                "fund_code": "000001",
                "fund_name": "测试基金A",
                "sw_level1": "银行",
                "holding_count": 1,
                "market_value_10k": 100.0,
                "nav_ratio": 0.05,
            }
        ],
        "industry_issues": [],
        "industry_sources": [{"item": "行业", "url": "https://example.test/industry", "note": "测试"}],
    }


def _comparison():
    return {
        "summary": {
            "manager": "测试经理",
            "previous_report_date": "2025-12-31",
            "current_report_date": "2026-03-31",
            "status": "通过（行业时点有限制）",
            "company_union_count": 1,
            "new_company_count": 0,
            "exited_company_count": 0,
            "increased_company_count": 1,
            "decreased_company_count": 0,
            "unchanged_company_count": 0,
            "fund_stock_change_count": 1,
            "industry_union_count": 1,
            "new_industry_count": 0,
            "exited_industry_count": 0,
            "increased_industry_count": 1,
            "decreased_industry_count": 0,
            "industry_snapshot_date": "2026-08-14",
            "historical_industry_point_in_time": False,
        },
        "company_changes": [
            {
                "change_type": "增持", "stock_code": "600000.SH", "stock_name": "浦发银行", "market": "A股", "sw_level1": "银行",
                "previous_fund_count": 1, "current_fund_count": 1, "previous_fund_codes": "000001", "current_fund_codes": "000001",
                "previous_shares_10k": 10.0, "current_shares_10k": 12.0, "shares_change_10k": 2.0, "shares_change_pct": 0.2,
                "previous_market_value_10k": 100.0, "current_market_value_10k": 120.0, "market_value_change_10k": 20.0,
                "market_value_change_pct": 0.2, "previous_nav_ratio_sum": 0.05, "current_nav_ratio_sum": 0.06,
                "nav_ratio_change": 0.01, "previous_best_rank": 2, "current_best_rank": 1, "rank_improvement": 1,
            }
        ],
        "fund_stock_changes": [
            {
                "change_type": "增持", "fund_code": "000001", "fund_name": "测试基金A", "stock_code": "600000.SH",
                "stock_name": "浦发银行", "sw_level1": "银行", "previous_rank": 2, "current_rank": 1, "rank_improvement": 1,
                "previous_shares_10k": 10.0, "current_shares_10k": 12.0, "shares_change_10k": 2.0, "shares_change_pct": 0.2,
                "previous_market_value_10k": 100.0, "current_market_value_10k": 120.0, "market_value_change_10k": 20.0,
                "previous_nav_ratio": 0.05, "current_nav_ratio": 0.06, "nav_ratio_change": 0.01,
            }
        ],
        "industry_changes": [
            {
                "change_type": "上升", "sw_level1": "银行", "previous_fund_count": 1, "current_fund_count": 1,
                "previous_fund_codes": "000001", "current_fund_codes": "000001", "previous_holding_count": 1,
                "current_holding_count": 1, "holding_count_change": 0, "previous_market_value_10k": 100.0,
                "current_market_value_10k": 120.0, "market_value_change_10k": 20.0, "previous_nav_ratio_sum": 0.05,
                "current_nav_ratio_sum": 0.06, "nav_ratio_change": 0.01,
            }
        ],
        "checks": [{"item": "相邻季度", "actual": "是", "expected": "是", "status": "OK", "note": "测试"}],
        "rules": [{"item": "比较", "rule": "确定性"}],
        "sources": [{"item": "输入", "path": "test.json", "report_date": "2026-03-31"}],
    }


def test_quarter_ingestion_is_idempotent(tmp_path: Path):
    db = tmp_path / "history.sqlite"
    first = ingest_quarter(db, _pipeline("2025-12-31", 10.0), _industry("2025-12-31"))
    second = ingest_quarter(db, _pipeline("2025-12-31", 10.0), _industry("2025-12-31"))
    status = history_status(db)

    assert first["action"] == "inserted"
    assert second["action"] == "updated"
    assert first["run_id"] == second["run_id"]
    assert status["integrity_check"] == "ok"
    assert status["counts"]["quarter_runs"] == 1
    assert status["counts"]["holdings"] == 1
    assert status["counts"]["stock_industry"] == 1


def test_empty_applicable_fund_set_uses_summary_manager(tmp_path: Path):
    pipeline = {
        "summary": {
            "manager": "纯固收经理",
            "report_date": "2026-06-30",
            "input_funds": 0,
            "selected_funds": 0,
            "successful_funds": 0,
            "formal_funds": 0,
            "raw_holding_rows": 0,
            "formal_holding_rows": 0,
            "issue_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "success_rate": 0,
            "duplicate_product_count": 0,
        },
        "funds": [],
        "all_holdings": [],
        "formal_holdings": [],
        "issues": [],
        "sources": [],
    }
    result = ingest_quarter(tmp_path / "empty.sqlite", pipeline)

    assert result["manager"] == "纯固收经理"
    assert result["fund_count"] == 0


def test_comparison_ingestion_requires_and_links_both_quarters(tmp_path: Path):
    db = tmp_path / "history.sqlite"
    ingest_quarter(db, _pipeline("2025-12-31", 10.0), _industry("2025-12-31"))
    ingest_quarter(db, _pipeline("2026-03-31", 12.0), _industry("2026-03-31"))
    first = ingest_comparison(db, _comparison())
    second = ingest_comparison(db, _comparison())
    status = history_status(db)

    assert first["action"] == "inserted"
    assert second["action"] == "updated"
    assert first["comparison_id"] == second["comparison_id"]
    assert status["counts"]["quarter_runs"] == 2
    assert status["counts"]["comparisons"] == 1
    assert status["counts"]["company_changes"] == 1
    assert status["counts"]["fund_stock_changes"] == 1
    assert status["counts"]["industry_changes"] == 1

    connection = sqlite3.connect(db)
    try:
        fund_code = connection.execute("SELECT fund_code FROM v_formal_holdings LIMIT 1").fetchone()[0]
        change_type = connection.execute("SELECT change_type FROM v_company_changes").fetchone()[0]
    finally:
        connection.close()
    assert fund_code == "000001"
    assert change_type == "增持"
