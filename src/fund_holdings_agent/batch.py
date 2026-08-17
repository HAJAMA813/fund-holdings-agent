from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .candidate_confirmations import read_candidate_confirmation_csv
from .disclosure import assess_disclosure, save_disclosure_json
from .excel_reports import build_holdings_report, build_manager_fund_pool_report, build_quarter_comparison_report, build_resource_report
from .industry import IndustryFetcher, enrich_industries, save_industry_json
from .history import ingest_comparison, ingest_quarter
from .manager_funds import CachedFetcher, get_manager_funds
from .pipeline import run_pipeline, save_json_outputs
from .quarter_compare import compare_quarters, save_comparison_json
from .resource_matching import build_resource_matching, read_personnel_csv, save_resource_json


STAGES = ["fund_pool", "holdings", "readiness", "industry", "resources", "history", "comparison", "reports"]
ORCHESTRATOR_VERSION = 2


@dataclass
class BatchConfig:
    manager: str
    report_date: str
    output_dir: Path
    raw_cache_dir: Path
    industry_cache_dir: Path
    personnel_path: Path
    history_db: Path
    snapshot_date: str
    candidate_confirmation_path: Path | None = None
    previous_dir: Path | None = None
    manager_id: str = ""
    workers: int = 4
    retries: int = 3
    timeout: int = 20
    sleep_seconds: float = 0.3
    refresh: bool = False
    skip_reports: bool = False
    retry_errors: bool = False
    force_stage: str = ""
    require_complete_disclosure: bool = True


StageHandler = Callable[[BatchConfig], dict[str, Any]]
ProgressCallback = Callable[[str, str], None]


def run_batch(
    config: BatchConfig,
    stage_handlers: dict[str, StageHandler] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / "batch_manifest.json"
    manifest = _load_or_create_manifest(manifest_path, config)
    handlers = stage_handlers or _default_handlers()
    rerun_index = _rerun_start_index(manifest, config)

    if rerun_index is None:
        manifest["overall_status"] = _overall_status(manifest)
        manifest["updated_at"] = _now()
        _atomic_write_json(manifest_path, manifest)
        _write_batch_summary(config.output_dir, manifest, [])
        return manifest

    executed: list[str] = []
    for index, stage in enumerate(STAGES):
        record = manifest["stages"][stage]
        if index < rerun_index:
            continue
        if stage == "comparison" and config.previous_dir is None:
            record.update({"status": "skipped", "reason": "未提供 previous_dir", "updated_at": _now()})
            if progress:
                progress(stage, "skipped")
            continue
        if stage == "reports" and config.skip_reports:
            record.update({"status": "skipped", "reason": "skip_reports=true", "updated_at": _now()})
            if progress:
                progress(stage, "skipped")
            continue

        if progress:
            progress(stage, "running")
        record["status"] = "running"
        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["started_at"] = _now()
        record["finished_at"] = ""
        record["error"] = ""
        record["reason"] = ""
        manifest["overall_status"] = "running"
        manifest["updated_at"] = _now()
        _atomic_write_json(manifest_path, manifest)
        try:
            result = handlers[stage](config)
            outputs = [str(Path(value).resolve()) for value in result.get("outputs", [])]
            record.update(
                {
                    "status": "completed_with_errors" if result.get("has_errors") else "completed",
                    "finished_at": _now(),
                    "outputs": outputs,
                    "summary": result.get("summary", {}),
                    "error": "",
                }
            )
            executed.append(stage)
            if progress:
                progress(stage, record["status"])
            if result.get("gate_waiting"):
                record["status"] = "waiting"
                record["reason"] = result.get("reason", "等待目标报告期披露完整")
                manifest["overall_status"] = "waiting"
                manifest["updated_at"] = _now()
                _atomic_write_json(manifest_path, manifest)
                _write_batch_summary(config.output_dir, manifest, executed)
                return manifest
        except Exception as exc:
            record.update({"status": "failed", "finished_at": _now(), "error": f"{type(exc).__name__}: {exc}"})
            if progress:
                progress(stage, "failed")
            manifest["overall_status"] = "failed"
            manifest["updated_at"] = _now()
            _atomic_write_json(manifest_path, manifest)
            _write_batch_summary(config.output_dir, manifest, executed)
            raise
        manifest["updated_at"] = _now()
        _atomic_write_json(manifest_path, manifest)

    manifest["overall_status"] = _overall_status(manifest)
    manifest["updated_at"] = _now()
    _atomic_write_json(manifest_path, manifest)
    _write_batch_summary(config.output_dir, manifest, executed)
    return manifest


def _default_handlers() -> dict[str, StageHandler]:
    return {
        "fund_pool": _stage_fund_pool,
        "holdings": _stage_holdings,
        "readiness": _stage_readiness,
        "industry": _stage_industry,
        "resources": _stage_resources,
        "history": _stage_history,
        "comparison": _stage_comparison,
        "reports": _stage_reports,
    }


def _stage_fund_pool(config: BatchConfig) -> dict[str, Any]:
    fetcher = CachedFetcher(
        config.raw_cache_dir,
        refresh=config.refresh,
        retries=config.retries,
        timeout=config.timeout,
        sleep_seconds=config.sleep_seconds,
    )
    data = get_manager_funds(config.manager, config.report_date, fetcher, config.manager_id)
    output = config.output_dir / "manager_fund_pool_data.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = data["summary"]
    return {"outputs": [output], "summary": summary, "has_errors": summary.get("error_count", 0) > 0}


def _stage_holdings(config: BatchConfig) -> dict[str, Any]:
    fetcher = CachedFetcher(
        config.raw_cache_dir,
        refresh=config.refresh,
        retries=config.retries,
        timeout=config.timeout,
        sleep_seconds=config.sleep_seconds,
    )
    data = run_pipeline(
        config.output_dir / "manager_fund_pool_data.json",
        config.report_date,
        config.retries,
        config.timeout,
        config.sleep_seconds,
        fetcher,
    )
    data_path, summary_path = save_json_outputs(data, config.output_dir)
    summary = data["summary"]
    return {"outputs": [data_path, summary_path], "summary": summary, "has_errors": summary.get("error_count", 0) > 0}


def _stage_readiness(config: BatchConfig) -> dict[str, Any]:
    data = assess_disclosure(_read_json(config.output_dir / "pipeline_data.json"))
    output = save_disclosure_json(data, config.output_dir / "disclosure_readiness.json")
    is_ready = data["summary"]["is_ready"]
    return {
        "outputs": [output],
        "summary": data["summary"],
        "has_errors": not is_ready,
        "gate_waiting": not is_ready and config.require_complete_disclosure,
        "reason": "目标报告期披露尚未完整；正式分析和入库已暂停",
    }


def _stage_industry(config: BatchConfig) -> dict[str, Any]:
    pipeline = _read_json(config.output_dir / "pipeline_data.json")
    fetcher = IndustryFetcher(
        config.industry_cache_dir,
        refresh=config.refresh,
        retries=config.retries,
        timeout=config.timeout,
        sleep_seconds=config.sleep_seconds,
    )
    data = enrich_industries(pipeline, config.snapshot_date, fetcher, max_workers=config.workers)
    output = save_industry_json(data, config.output_dir / "industry_analysis_data.json")
    quality = data["industry_quality"]
    return {"outputs": [output], "summary": quality, "has_errors": quality.get("error_count", 0) > 0}


def _stage_resources(config: BatchConfig) -> dict[str, Any]:
    industry = _read_json(config.output_dir / "industry_analysis_data.json")
    people, issues = read_personnel_csv(config.personnel_path)
    confirmations, confirmation_issues = read_candidate_confirmation_csv(config.candidate_confirmation_path)
    data = build_resource_matching(
        industry,
        people,
        issues,
        confirmations,
        confirmation_issues,
        str(config.candidate_confirmation_path.resolve()) if config.candidate_confirmation_path and config.candidate_confirmation_path.exists() else "",
    )
    output = save_resource_json(data, config.output_dir / "resource_matching_data.json")
    summary = data["summary"]
    return {
        "outputs": [output],
        "summary": summary,
        "has_errors": summary.get("personnel_error_count", 0) > 0 or summary.get("confirmation_registry_error_count", 0) > 0,
    }


def _stage_history(config: BatchConfig) -> dict[str, Any]:
    outputs = [config.history_db]
    previous_result = None
    if config.previous_dir:
        previous_pipeline_path = config.previous_dir / "pipeline_data.json"
        previous_industry_path = config.previous_dir / "industry_analysis_data.json"
        previous_result = ingest_quarter(
            config.history_db,
            _read_json(previous_pipeline_path),
            _read_json(previous_industry_path),
            previous_pipeline_path,
            previous_industry_path,
        )
    current_pipeline_path = config.output_dir / "pipeline_data.json"
    current_industry_path = config.output_dir / "industry_analysis_data.json"
    current_result = ingest_quarter(
        config.history_db,
        _read_json(current_pipeline_path),
        _read_json(current_industry_path),
        current_pipeline_path,
        current_industry_path,
    )
    return {"outputs": outputs, "summary": {"previous": previous_result, "current": current_result}, "has_errors": False}


def _stage_comparison(config: BatchConfig) -> dict[str, Any]:
    assert config.previous_dir is not None
    previous_pipeline_path = config.previous_dir / "pipeline_data.json"
    previous_industry_path = config.previous_dir / "industry_analysis_data.json"
    current_pipeline_path = config.output_dir / "pipeline_data.json"
    current_industry_path = config.output_dir / "industry_analysis_data.json"
    data = compare_quarters(
        _read_json(previous_pipeline_path),
        _read_json(current_pipeline_path),
        _read_json(previous_industry_path),
        _read_json(current_industry_path),
    )
    data["sources"] = [
        {"item": "上期持仓输入", "path": str(previous_pipeline_path), "report_date": data["summary"]["previous_report_date"]},
        {"item": "本期持仓输入", "path": str(current_pipeline_path), "report_date": data["summary"]["current_report_date"]},
        {"item": "上期行业输入", "path": str(previous_industry_path), "report_date": data["summary"]["previous_report_date"]},
        {"item": "本期行业输入", "path": str(current_industry_path), "report_date": data["summary"]["current_report_date"]},
    ]
    output = save_comparison_json(data, config.output_dir / "quarter_comparison_data.json")
    ingest_result = ingest_comparison(config.history_db, data, output)
    return {"outputs": [output, config.history_db], "summary": {**data["summary"], "history": ingest_result}, "has_errors": data["summary"]["status"] == "存在需核查项"}


def _stage_reports(config: BatchConfig) -> dict[str, Any]:
    quarter = _quarter_label(config.report_date)
    outputs = [
        config.output_dir / f"基金经理基金池_{config.manager}_{config.report_date}.xlsx",
        config.output_dir / f"{config.manager}_{quarter}_基金持仓与行业.xlsx",
        config.output_dir / f"{config.manager}_{quarter}_研究资源对接.xlsx",
    ]
    builders: list[tuple[Callable[[Path, Path], Path], Path, Path]] = [
        (build_manager_fund_pool_report, config.output_dir / "manager_fund_pool_data.json", outputs[0]),
        (build_holdings_report, config.output_dir / "industry_analysis_data.json", outputs[1]),
        (build_resource_report, config.output_dir / "resource_matching_data.json", outputs[2]),
    ]
    comparison_path = config.output_dir / "quarter_comparison_data.json"
    if comparison_path.exists():
        comparison = _read_json(comparison_path)["summary"]
        comparison_output = config.output_dir / f"{config.manager}_{_quarter_label(comparison['previous_report_date'])}至{quarter}_持仓变化分析.xlsx"
        outputs.append(comparison_output)
        builders.append((build_quarter_comparison_report, comparison_path, comparison_output))
    for builder, input_path, output_path in builders:
        builder(input_path, output_path)
    return {"outputs": outputs, "summary": {"report_count": len(outputs)}, "has_errors": False}


def _load_or_create_manifest(path: Path, config: BatchConfig) -> dict[str, Any]:
    if path.exists():
        manifest = _read_json(path)
        if manifest.get("manager") != config.manager or manifest.get("report_date") != config.report_date:
            raise ValueError("现有 batch_manifest.json 的基金经理或报告期与本次参数不一致")
        for stage in STAGES:
            manifest.setdefault("stages", {}).setdefault(stage, _empty_stage())
        manifest["orchestrator_version"] = ORCHESTRATOR_VERSION
        manifest["config"] = _public_config(config)
        return manifest
    now = _now()
    return {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "run_key": f"{config.manager}|{config.report_date}",
        "manager": config.manager,
        "report_date": config.report_date,
        "overall_status": "pending",
        "created_at": now,
        "updated_at": now,
        "config": _public_config(config),
        "stages": {stage: _empty_stage() for stage in STAGES},
    }


def _rerun_start_index(manifest: dict[str, Any], config: BatchConfig) -> int | None:
    if config.force_stage:
        if config.force_stage not in STAGES:
            raise ValueError(f"未知阶段：{config.force_stage}")
        return STAGES.index(config.force_stage)
    for index, stage in enumerate(STAGES):
        record = manifest["stages"][stage]
        status = record.get("status", "pending")
        if stage == "comparison" and config.previous_dir is None:
            continue
        if stage == "reports" and config.skip_reports:
            continue
        if status in {"pending", "running", "failed"}:
            return index
        if status == "waiting":
            return index
        if status == "completed_with_errors" and config.retry_errors:
            return index
        if status == "completed" and not _outputs_exist(record.get("outputs", [])):
            return index
        if status == "skipped":
            return index
    return None


def _outputs_exist(outputs: list[str]) -> bool:
    return bool(outputs) and all(Path(path).exists() for path in outputs)


def _overall_status(manifest: dict[str, Any]) -> str:
    statuses = [record.get("status") for record in manifest["stages"].values()]
    if "failed" in statuses:
        return "failed"
    if "waiting" in statuses:
        return "waiting"
    if "running" in statuses or "pending" in statuses:
        return "running"
    if "completed_with_errors" in statuses:
        return "completed_with_errors"
    return "completed"


def _write_batch_summary(output_dir: Path, manifest: dict[str, Any], executed: list[str]) -> None:
    overall_status = manifest["overall_status"]
    summary = {
        "run_key": manifest["run_key"],
        "overall_status": manifest["overall_status"],
        "executed_stages": executed,
        "stage_statuses": {stage: record["status"] for stage, record in manifest["stages"].items()},
        "report_files": manifest["stages"]["reports"].get("outputs", []),
        "manifest": str((output_dir / "batch_manifest.json").resolve()),
        "exit_code": {"completed": 0, "waiting": 2, "completed_with_errors": 3, "failed": 1}.get(overall_status, 1),
        "next_action": _next_action(manifest),
        "notification_summary": _notification_summary(manifest),
    }
    _atomic_write_json(output_dir / "batch_summary.json", summary)


def _public_config(config: BatchConfig) -> dict[str, Any]:
    values = asdict(config)
    for key, value in list(values.items()):
        if isinstance(value, Path):
            values[key] = str(value.resolve())
    if config.previous_dir is not None:
        values["previous_dir"] = str(config.previous_dir.resolve())
    return values


def _empty_stage() -> dict[str, Any]:
    return {"status": "pending", "attempts": 0, "started_at": "", "finished_at": "", "outputs": [], "summary": {}, "error": "", "reason": ""}


def _next_action(manifest: dict[str, Any]) -> str:
    status = manifest["overall_status"]
    if status == "waiting":
        return "在下一检查窗口使用 --refresh --force-stage holdings 重试；确认产品不适用后才可使用 --allow-incomplete-disclosure"
    if status == "failed":
        return "修复失败原因后原样重跑，任务会从失败阶段继续"
    if status == "completed_with_errors":
        return "查看异常清单；可使用 --retry-errors 重跑首个带错误阶段"
    if status == "completed":
        return "无需处理；等待下一季度任务"
    return "继续执行当前任务"


def _notification_summary(manifest: dict[str, Any]) -> str:
    prefix = f"{manifest['manager']} {manifest['report_date']}"
    status = manifest["overall_status"]
    if status == "waiting":
        readiness = manifest["stages"]["readiness"].get("summary", {})
        return (
            f"{prefix}：披露未完整（{readiness.get('ready_fund_count', 0)}/"
            f"{readiness.get('selected_fund_count', 0)}），已暂停正式分析；"
            f"待处理 {readiness.get('pending_fund_count', 0)} 只。"
        )
    if status == "completed":
        reports = manifest["stages"]["reports"]
        if reports.get("status") == "skipped" and reports.get("reason") == "skip_reports=true":
            return f"{prefix}：数据处理已完成；正式报告按配置未生成。"
        return f"{prefix}：季度任务已完成，正式报告已生成。"
    if status == "completed_with_errors":
        return f"{prefix}：季度任务已完成但存在异常，请查看异常清单。"
    if status == "failed":
        failed = next((name for name, row in manifest["stages"].items() if row.get("status") == "failed"), "未知")
        return f"{prefix}：任务在 {failed} 阶段失败，需要处理后续跑。"
    return f"{prefix}：季度任务进行中。"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _quarter_label(report_date: str) -> str:
    date = dt.date.fromisoformat(report_date)
    return f"{date.year}Q{date.month // 3}"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
