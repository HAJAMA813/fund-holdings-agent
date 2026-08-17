import json
import sys
from pathlib import Path

import pytest

from fund_holdings_agent import portfolio_cli


def test_portfolio_cli_builds_one_company_report_per_company(tmp_path: Path, monkeypatch):
    roster = tmp_path / "managers.csv"
    roster.write_text(
        "company,manager,manager_id,active\n"
        "甲基金管理有限公司,甲经理,101,yes\n"
        "乙基金管理有限公司,乙经理,202,yes\n",
        encoding="utf-8",
    )
    output_root = tmp_path / "output"
    report_root = tmp_path / "reports"
    reports: list[tuple[Path, Path]] = []

    def fake_run_batch(config, progress=None):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "batch_summary.json").write_text(
            json.dumps({"exit_code": 0, "notification_summary": "完成"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (config.output_dir / "manager_fund_pool_data.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "manager": config.manager,
                        "historical_share_count": 0,
                        "active_share_count": 0,
                        "selected_share_count": 0,
                        "product_count": 0,
                    },
                    "all_tenures": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (config.output_dir / "pipeline_data.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "successful_funds": 0,
                        "formal_funds": 0,
                        "raw_holding_rows": 0,
                        "formal_holding_rows": 0,
                        "error_count": 0,
                        "warning_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        (config.output_dir / "industry_analysis_data.json").write_text(
            json.dumps({"industry_quality": {"error_count": 0, "warning_count": 0}, "stock_industry_mapping": []}),
            encoding="utf-8",
        )
        return {"overall_status": "completed"}

    def fake_build_company_report(input_path, output_path):
        reports.append((Path(input_path), Path(output_path)))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).touch()

    monkeypatch.setattr(portfolio_cli, "run_batch", fake_run_batch)
    monkeypatch.setattr(portfolio_cli, "build_company_portfolio_report", fake_build_company_report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fund-portfolio",
            "--roster",
            str(roster),
            "--output-root",
            str(output_root),
            "--company-report-output-root",
            str(report_root),
            "--report-date",
            "2026-06-30",
            "--as-of",
            "2026-08-14",
            "--skip-reports",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        portfolio_cli.main()

    assert exc.value.code == 0
    assert len(reports) == 2
    assert {output.name for _, output in reports} == {
        "甲基金_甲经理_2026Q2_基金经理持仓分析.xlsx",
        "乙基金_乙经理_2026Q2_基金经理持仓分析.xlsx",
    }
    assert all(output.is_relative_to(report_root) for _, output in reports)
    summary = json.loads((output_root / "portfolio_summary_2026Q2.json").read_text(encoding="utf-8"))
    assert summary["overall_status"] == "completed"
    assert summary["timezone"] == "Asia/Shanghai"
    assert [row["status"] for row in summary["company_reports"]] == ["completed", "completed"]
    receipt = (output_root / "portfolio_notification_2026Q2.txt").read_text(encoding="utf-8")
    assert "运行时区：Asia/Shanghai" in receipt
    assert "总体状态：completed" in receipt
    assert "未调用 DeepSeek" in receipt
