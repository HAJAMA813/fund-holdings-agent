import json
from pathlib import Path

from fund_holdings_agent.preproduction_replay import build_preproduction_replay


def test_preproduction_replay_uses_local_results_and_reconciles_company_dedup(tmp_path: Path):
    # Reuse the focused company-comparison test fixture logic through a minimal local portfolio.
    from test_company_compare import _write_period

    project = tmp_path / "project"
    portfolio = project / "outputs" / "portfolio"
    previous = _write_period(portfolio, "2026Q1", "2026-03-31", 10.0)
    current = _write_period(portfolio, "2026Q2", "2026-06-30", 12.0)
    previous_data = json.loads(previous.read_text(encoding="utf-8"))
    current_data = json.loads(current.read_text(encoding="utf-8"))
    for summary, quarter, report_date in [(previous_data, "2026Q1", "2026-03-31"), (current_data, "2026Q2", "2026-06-30")]:
        summary.update(
            {
                "overall_status": "completed",
                "exit_code": 0,
                "metrics": {"formal_holding_rows": 2, "global_a_industry_coverage": 1.0},
            }
        )
        for row in summary["manager_results"]:
            row["overall_status"] = "completed"
            output = Path(row["output_dir"])
            industry = json.loads((output / "industry_analysis_data.json").read_text(encoding="utf-8"))
            (output / "pipeline_data.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "report_date": report_date,
                            "formal_funds": 1,
                            "formal_holding_rows": 1,
                            "error_count": 0,
                            "warning_count": 0,
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            industry["industry_quality"].update({"error_count": 0, "warning_count": 1})
            (output / "industry_analysis_data.json").write_text(json.dumps(industry, ensure_ascii=False), encoding="utf-8")
            (output / "quarter_comparison_data.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "new_company_count": 0,
                            "exited_company_count": 0,
                            "increased_company_count": 1,
                            "decreased_company_count": 0,
                            "unchanged_company_count": 0,
                            "status": "通过（行业时点有限制）",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        (portfolio / f"portfolio_summary_{quarter}.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    roster = project / "data" / "managers_portfolio.csv"
    roster.parent.mkdir(parents=True)
    roster.write_text("company,manager,manager_id,active\n测试基金管理有限公司,甲,1001,yes\n测试基金管理有限公司,乙,1002,yes\n", encoding="utf-8")

    result = build_preproduction_replay(project, portfolio, roster, project / "outputs" / "replay")

    assert result["network_used"] is False
    assert result["deepseek_used"] is False
    assert result["metrics"]["previous_joint_management_duplicate_rows_removed"] == 1
    assert result["metrics"]["current_joint_management_duplicate_rows_removed"] == 1
    assert result["checks"][7]["status"] == "OK"
    assert Path(result["outputs"]["summary_json"]).exists()
