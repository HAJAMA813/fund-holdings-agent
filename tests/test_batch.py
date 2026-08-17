import json
from pathlib import Path

import pytest

from fund_holdings_agent.batch import BatchConfig, STAGES, run_batch


def _config(tmp_path: Path, **overrides):
    values = {
        "manager": "测试经理",
        "report_date": "2026-03-31",
        "output_dir": tmp_path / "run",
        "raw_cache_dir": tmp_path / "raw_cache",
        "industry_cache_dir": tmp_path / "industry_cache",
        "personnel_path": tmp_path / "people.csv",
        "history_db": tmp_path / "history.sqlite",
        "snapshot_date": "2026-08-14",
        "skip_reports": False,
    }
    values.update(overrides)
    return BatchConfig(**values)


def _handlers(config: BatchConfig, calls: list[str], error_stage: str = "", error_once: bool = False, data_error_stage: str = ""):
    attempts = {}

    def build(stage):
        def handler(_config):
            calls.append(stage)
            attempts[stage] = attempts.get(stage, 0) + 1
            if stage == error_stage and (not error_once or attempts[stage] == 1):
                raise RuntimeError("simulated failure")
            output = config.output_dir / f"{stage}.done"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(stage, encoding="utf-8")
            return {"outputs": [output], "summary": {"stage": stage}, "has_errors": stage == data_error_stage}

        return handler

    return {stage: build(stage) for stage in STAGES}


def test_completed_batch_is_fully_skipped_on_second_run(tmp_path: Path):
    config = _config(tmp_path, previous_dir=tmp_path / "previous")
    calls = []
    handlers = _handlers(config, calls)

    first = run_batch(config, handlers)
    first_calls = list(calls)
    second = run_batch(config, handlers)

    assert first["overall_status"] == "completed"
    assert first_calls == STAGES
    assert calls == STAGES
    assert second["overall_status"] == "completed"
    assert json.loads((config.output_dir / "batch_summary.json").read_text(encoding="utf-8"))["executed_stages"] == []


def test_failed_stage_resumes_from_failure_and_keeps_prior_stage_attempts(tmp_path: Path):
    config = _config(tmp_path)
    calls = []
    handlers = _handlers(config, calls, error_stage="industry", error_once=True)

    with pytest.raises(RuntimeError, match="simulated failure"):
        run_batch(config, handlers)
    manifest_after_failure = json.loads((config.output_dir / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest_after_failure["stages"]["fund_pool"]["attempts"] == 1
    assert manifest_after_failure["stages"]["industry"]["status"] == "failed"

    final = run_batch(config, handlers)

    assert calls[:4] == ["fund_pool", "holdings", "readiness", "industry"]
    assert calls[4:] == ["industry", "resources", "history", "reports"]
    assert final["stages"]["fund_pool"]["attempts"] == 1
    assert final["stages"]["industry"]["attempts"] == 2
    assert final["stages"]["comparison"]["status"] == "skipped"


def test_retry_errors_reruns_error_stage_and_downstream_only(tmp_path: Path):
    config = _config(tmp_path)
    calls = []
    handlers = _handlers(config, calls, data_error_stage="resources")
    first = run_batch(config, handlers)
    assert first["overall_status"] == "completed_with_errors"

    retry_config = _config(tmp_path, retry_errors=True)
    second = run_batch(retry_config, handlers)

    assert calls.count("fund_pool") == 1
    assert calls.count("holdings") == 1
    assert calls.count("industry") == 1
    assert calls.count("resources") == 2
    assert calls.count("history") == 2
    assert calls.count("reports") == 2
    assert second["stages"]["resources"]["attempts"] == 2


def test_waiting_gate_stops_downstream_and_resumes_same_stage(tmp_path: Path):
    config = _config(tmp_path)
    calls = []
    handlers = _handlers(config, calls)
    readiness_calls = 0

    def readiness(_config):
        nonlocal readiness_calls
        calls.append("readiness")
        readiness_calls += 1
        output = config.output_dir / "readiness.done"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("readiness", encoding="utf-8")
        waiting = readiness_calls == 1
        return {
            "outputs": [output],
            "summary": {"selected_fund_count": 2, "ready_fund_count": 1 if waiting else 2, "pending_fund_count": 1 if waiting else 0},
            "has_errors": waiting,
            "gate_waiting": waiting,
        }

    handlers["readiness"] = readiness
    first = run_batch(config, handlers)
    waiting_summary = json.loads((config.output_dir / "batch_summary.json").read_text(encoding="utf-8"))
    second = run_batch(config, handlers)

    assert first["overall_status"] == "waiting"
    assert waiting_summary["exit_code"] == 2
    assert "披露未完整（1/2）" in waiting_summary["notification_summary"]
    assert calls[:3] == ["fund_pool", "holdings", "readiness"]
    assert calls[3:] == ["readiness", "industry", "resources", "history", "reports"]
    assert second["overall_status"] == "completed"
    assert second["stages"]["readiness"]["attempts"] == 2


def test_skip_reports_notification_does_not_claim_reports_exist(tmp_path: Path):
    config = _config(tmp_path, skip_reports=True)
    calls = []

    manifest = run_batch(config, _handlers(config, calls))
    summary = json.loads((config.output_dir / "batch_summary.json").read_text(encoding="utf-8"))

    assert manifest["overall_status"] == "completed"
    assert manifest["stages"]["reports"]["status"] == "skipped"
    assert summary["notification_summary"] == "测试经理 2026-03-31：数据处理已完成；正式报告按配置未生成。"
