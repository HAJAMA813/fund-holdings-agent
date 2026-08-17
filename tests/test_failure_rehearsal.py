from pathlib import Path

from fund_holdings_agent.failure_rehearsal import run_failure_rehearsal


def test_failure_rehearsal_passes_all_offline_scenarios(tmp_path: Path):
    result = run_failure_rehearsal(tmp_path / "failure_rehearsal")

    assert result["overall_status"] == "passed"
    assert result["passed_check_count"] == 9
    assert result["failed_check_count"] == 0
    assert result["network_used"] is False
    assert result["deepseek_used"] is False
    assert Path(result["outputs"]["summary"]).exists()
    assert Path(result["outputs"]["playbook"]).exists()
