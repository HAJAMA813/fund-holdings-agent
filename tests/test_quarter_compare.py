import pytest

from fund_holdings_agent.quarter_compare import compare_quarters


def _holding(fund_code, stock_code, stock_name, shares, nav, rank=1):
    return {
        "fund_code": fund_code,
        "fund_name": f"基金{fund_code}",
        "manager": "测试经理",
        "report_date": "2026-03-31",
        "rank": rank,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "shares_10k": shares,
        "market_value_10k": shares * 10,
        "nav_ratio": nav,
        "market": "A股",
        "representative": "是",
    }


def _pipeline(report_date, rows, manager="测试经理"):
    return {
        "summary": {"manager": manager, "report_date": report_date, "error_count": 0},
        "formal_holdings": rows,
    }


def _industry(report_date, rows):
    codes = {row["stock_code"] for row in rows}
    return {
        "industry_quality": {
            "snapshot_date": "2026-08-14",
            "historical_point_in_time": False,
        },
        "stock_industry_mapping": [
            {"stock_code": code, "sw_level1": "电子" if code != "CCC.SH" else "计算机"}
            for code in codes
        ],
        "industry_summary": [
            {
                "fund_code": "000001",
                "fund_name": "基金000001",
                "sw_level1": "电子",
                "holding_count": sum(row["stock_code"] != "CCC.SH" for row in rows),
                "market_value_10k": sum(row["market_value_10k"] for row in rows if row["stock_code"] != "CCC.SH"),
                "nav_ratio": sum(row["nav_ratio"] for row in rows if row["stock_code"] != "CCC.SH"),
            },
            *(
                [
                    {
                        "fund_code": "000001",
                        "fund_name": "基金000001",
                        "sw_level1": "计算机",
                        "holding_count": sum(row["stock_code"] == "CCC.SH" for row in rows),
                        "market_value_10k": sum(row["market_value_10k"] for row in rows if row["stock_code"] == "CCC.SH"),
                        "nav_ratio": sum(row["nav_ratio"] for row in rows if row["stock_code"] == "CCC.SH"),
                    }
                ]
                if any(row["stock_code"] == "CCC.SH" for row in rows)
                else []
            ),
        ],
    }


def test_compare_classifies_new_exit_increase_and_decrease():
    previous_rows = [
        _holding("000001", "AAA.SH", "甲", 10, 0.10),
        _holding("000001", "BBB.SH", "乙", 10, 0.08),
        _holding("000001", "DDD.SH", "丁", 10, 0.06),
    ]
    current_rows = [
        _holding("000001", "AAA.SH", "甲", 12, 0.11),
        _holding("000001", "CCC.SH", "丙", 5, 0.07),
        _holding("000001", "DDD.SH", "丁", 8, 0.04),
    ]

    result = compare_quarters(
        _pipeline("2025-12-31", previous_rows),
        _pipeline("2026-03-31", current_rows),
        _industry("2025-12-31", previous_rows),
        _industry("2026-03-31", current_rows),
    )
    status = {row["stock_code"]: row["change_type"] for row in result["company_changes"]}

    assert status == {"AAA.SH": "增持", "BBB.SH": "退出", "CCC.SH": "新进", "DDD.SH": "减持"}
    assert result["summary"]["new_company_count"] == 1
    assert result["summary"]["exited_company_count"] == 1


def test_company_level_aggregates_funds_before_comparing():
    previous_rows = [
        _holding("000001", "AAA.SH", "甲", 10, 0.10),
        _holding("000002", "AAA.SH", "甲", 5, 0.05),
    ]
    current_rows = [
        _holding("000001", "AAA.SH", "甲", 11, 0.11),
        _holding("000002", "AAA.SH", "甲", 7, 0.06),
    ]

    result = compare_quarters(
        _pipeline("2025-12-31", previous_rows),
        _pipeline("2026-03-31", current_rows),
        _industry("2025-12-31", previous_rows),
        _industry("2026-03-31", current_rows),
    )
    row = result["company_changes"][0]

    assert row["previous_shares_10k"] == 15
    assert row["current_shares_10k"] == 18
    assert row["current_fund_count"] == 2
    assert row["change_type"] == "增持"


def test_industry_change_uses_nav_ratio_direction():
    previous_rows = [_holding("000001", "AAA.SH", "甲", 10, 0.10)]
    current_rows = [_holding("000001", "AAA.SH", "甲", 9, 0.07), _holding("000001", "CCC.SH", "丙", 2, 0.03)]

    result = compare_quarters(
        _pipeline("2025-12-31", previous_rows),
        _pipeline("2026-03-31", current_rows),
        _industry("2025-12-31", previous_rows),
        _industry("2026-03-31", current_rows),
    )
    status = {row["sw_level1"]: row["change_type"] for row in result["industry_changes"]}

    assert status["电子"] == "下降"
    assert status["计算机"] == "新进入前十行业"


def test_non_consecutive_quarters_are_rejected():
    rows = [_holding("000001", "AAA.SH", "甲", 10, 0.10)]
    with pytest.raises(ValueError, match="季度必须相邻"):
        compare_quarters(
            _pipeline("2025-09-30", rows),
            _pipeline("2026-03-31", rows),
            _industry("2025-09-30", rows),
            _industry("2026-03-31", rows),
        )


def test_comparison_uses_requested_manager_instead_of_disclosure_co_managers():
    rows = [_holding("000001", "AAA.SH", "甲", 10, 0.10)]
    rows[0]["manager"] = "测试经理、共同经理"

    result = compare_quarters(
        _pipeline("2025-12-31", rows, manager="测试经理"),
        _pipeline("2026-03-31", rows, manager="测试经理"),
        _industry("2025-12-31", rows),
        _industry("2026-03-31", rows),
    )

    assert result["summary"]["manager"] == "测试经理"
