import json
from pathlib import Path

from fund_holdings_agent.company_compare import build_company_comparison


def _industry(manager: str, report_date: str, shares: float) -> dict:
    return {
        "summary": {"manager": manager, "report_date": report_date, "error_count": 0},
        "industry_quality": {"snapshot_date": "2026-08-14", "historical_point_in_time": False, "error_count": 0},
        "formal_holdings_industry": [
            {
                "fund_code": "000001", "fund_name": "测试基金A", "manager": manager,
                "report_date": report_date, "rank": 1, "stock_code": "600000.SH", "stock_name": "浦发银行",
                "shares_10k": shares, "market_value_10k": shares * 10, "nav_ratio": 0.05,
                "market": "A股", "representative": "是", "sw_level1": "银行",
            }
        ],
        "stock_industry_mapping": [
            {"stock_code": "600000.SH", "stock_name": "浦发银行", "sw_level1": "银行", "sw_level2": "股份制银行Ⅱ", "sw_level2_code": "801783.SI"}
        ],
    }


def _write_period(root: Path, quarter: str, report_date: str, shares: float) -> Path:
    results = []
    for manager in ["甲", "乙"]:
        output = root / f"{manager}_{quarter}"
        output.mkdir(parents=True)
        (output / "industry_analysis_data.json").write_text(
            json.dumps(_industry(manager, report_date, shares), ensure_ascii=False), encoding="utf-8"
        )
        results.append({"company": "测试基金管理有限公司", "manager": manager, "output_dir": str(output)})
    summary = {"report_date": report_date, "manager_results": results}
    path = root / f"portfolio_summary_{quarter}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return path


def test_company_comparison_deduplicates_jointly_managed_fund(tmp_path: Path):
    previous = _write_period(tmp_path / "previous", "2026Q1", "2026-03-31", 10.0)
    current = _write_period(tmp_path / "current", "2026Q2", "2026-06-30", 12.0)

    result = build_company_comparison(previous, current, "测试基金管理有限公司")

    assert result["summary"]["previous_holding_rows"] == 1
    assert result["summary"]["current_holding_rows"] == 1
    assert result["summary"]["previous_duplicate_rows_removed"] == 1
    assert result["summary"]["current_duplicate_rows_removed"] == 1
    assert result["summary"]["dedup_conflict_count"] == 0
    assert result["company_changes"][0]["shares_change_10k"] == 2.0
    assert result["company_changes"][0]["change_type"] == "增持"
