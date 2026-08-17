from pathlib import Path

import pytest

from fund_holdings_agent.portfolio import (
    aggregate_portfolio_metrics,
    aggregate_portfolio_status,
    company_directory_name,
    portfolio_notification,
    portfolio_run_receipt,
    read_manager_roster,
)


def test_manager_roster_reads_active_rows_and_validates_ids(tmp_path: Path):
    path = tmp_path / "managers.csv"
    path.write_text(
        "company,manager,manager_id,active\n长安基金,甲,123,yes\n长安基金,乙,456,no\n",
        encoding="utf-8",
    )

    entries = read_manager_roster(path)

    assert [(row.manager, row.manager_id) for row in entries] == [("甲", "123")]


def test_duplicate_manager_is_rejected(tmp_path: Path):
    path = tmp_path / "managers.csv"
    path.write_text(
        "company,manager,manager_id,active\n长安基金,甲,123,yes\n长安基金,甲,456,yes\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="重复"):
        read_manager_roster(path)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["completed", "completed"], ("completed", 0)),
        (["completed", "waiting"], ("waiting", 2)),
        (["waiting", "completed_with_errors"], ("completed_with_errors", 3)),
        (["completed", "failed"], ("failed", 1)),
    ],
)
def test_portfolio_status_priority(statuses, expected):
    assert aggregate_portfolio_status([{"overall_status": value} for value in statuses]) == expected


def test_notification_summarizes_all_managers():
    results = [
        {"manager": "甲", "overall_status": "completed"},
        {"manager": "乙", "overall_status": "waiting"},
    ]

    text = portfolio_notification("长安基金", "2026-06-30", results)

    assert "完成 1" in text
    assert "等待披露 1" in text
    assert "甲=completed" in text


def test_portfolio_receipt_is_local_and_actionable():
    payload = {
        "timezone": "Asia/Shanghai",
        "generated_at_beijing": "2026-08-15T09:30:00+08:00",
        "as_of": "2026-08-15",
        "report_date": "2026-06-30",
        "overall_status": "waiting",
        "exit_code": 2,
        "notification_summary": "长安基金：等待披露 1",
        "metrics": {"formal_product_count": 17, "formal_holding_rows": 170, "pipeline_error_count": 0, "global_a_industry_coverage": 1.0},
        "manager_results": [
            {"company": "长安基金", "manager": "甲", "overall_status": "waiting", "notification_summary": "等待目标季度披露"}
        ],
        "company_reports": [],
    }

    receipt = portfolio_run_receipt(payload)

    assert "运行时区：Asia/Shanghai" in receipt
    assert "行业映射覆盖率：100.00%" in receipt
    assert "下一检查窗口自动刷新" in receipt
    assert "未调用 DeepSeek" in receipt


def test_company_directory_is_stable_and_short():
    assert company_directory_name("广发基金管理有限公司") == "广发基金"
    assert company_directory_name("长安基金管理有限公司") == "长安基金"


def test_same_manager_name_in_different_companies_is_allowed(tmp_path: Path):
    path = tmp_path / "managers.csv"
    path.write_text(
        "company,manager,manager_id,active\n甲基金,王浩,123,yes\n乙基金,王浩,456,yes\n",
        encoding="utf-8",
    )

    assert len(read_manager_roster(path)) == 2


def test_portfolio_metrics_support_manager_without_applicable_products(tmp_path: Path):
    output = tmp_path / "经理_2026Q2"
    output.mkdir()
    (output / "manager_fund_pool_data.json").write_text(
        '{"summary":{"manager":"固收经理","historical_share_count":2,"active_share_count":2,"selected_share_count":0,"product_count":0},"all_tenures":[]}',
        encoding="utf-8",
    )
    (output / "pipeline_data.json").write_text(
        '{"summary":{"successful_funds":0,"formal_funds":0,"raw_holding_rows":0,"formal_holding_rows":0,"error_count":0,"warning_count":0}}',
        encoding="utf-8",
    )
    (output / "industry_analysis_data.json").write_text(
        '{"industry_quality":{"error_count":0,"warning_count":1},"stock_industry_mapping":[]}',
        encoding="utf-8",
    )

    metrics = aggregate_portfolio_metrics([{"manager": "固收经理", "output_dir": str(output)}])

    assert metrics["loaded_manager_count"] == 1
    assert metrics["managers_without_applicable_products"] == ["固收经理"]
    assert metrics["global_a_industry_coverage"] == 1.0
