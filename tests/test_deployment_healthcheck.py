from fund_holdings_agent.deployment_healthcheck import derive_readiness, render_deployment_todo, render_healthcheck_markdown


def test_derive_readiness_distinguishes_blockers_and_warnings() -> None:
    passed = {"severity": "阻断", "status": "PASS"}
    warning = {"severity": "警告", "status": "WARN"}
    blocker = {"severity": "阻断", "status": "FAIL"}

    assert derive_readiness([passed]) == "READY"
    assert derive_readiness([passed, warning]) == "READY_WITH_WARNINGS"
    assert derive_readiness([passed, blocker]) == "BLOCKED"


def test_healthcheck_reports_keep_manual_and_automation_status_separate() -> None:
    result = {
        "generated_at_beijing": "2026-08-15T17:00:00+08:00",
        "report_date": "2026-06-30",
        "quarter": "2026Q2",
        "manual_run_readiness": "READY_WITH_WARNINGS",
        "automation_deployment_status": "NOT_DEPLOYED",
        "passed_check_count": 1,
        "warning_or_skipped_count": 1,
        "blocking_failure_count": 0,
        "checks": [
            {
                "id": "HC-X",
                "group": "部署",
                "name": "调度",
                "severity": "警告",
                "status": "WARN",
                "evidence": "未配置",
                "action": "配置调度",
            }
        ],
    }

    report = render_healthcheck_markdown(result)
    todo = render_deployment_todo(result)
    assert "READY_WITH_WARNINGS" in report
    assert "NOT_DEPLOYED" in report
    assert "配置调度" in todo
