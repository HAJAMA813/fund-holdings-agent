from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .batch import BatchConfig, STAGES, run_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="一条命令运行基金持仓季度确定性全流程")
    parser.add_argument("--manager", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--raw-cache-dir", type=Path)
    parser.add_argument("--industry-cache-dir", type=Path)
    parser.add_argument("--personnel", type=Path, default=Path("data/personnel_template.csv"))
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--history-db", type=Path)
    parser.add_argument("--previous-dir", type=Path)
    parser.add_argument("--snapshot-date", default=dt.date.today().isoformat())
    parser.add_argument("--manager-id", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retry-errors", action="store_true", help="重跑首个 completed_with_errors 阶段及其下游；成功请求继续复用缓存")
    parser.add_argument("--force-stage", choices=STAGES, default="", help="从指定阶段开始强制重跑并刷新下游结果")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument(
        "--allow-incomplete-disclosure",
        action="store_true",
        help="人工确认后允许在披露不完整时继续；默认会以 waiting 状态暂停",
    )
    args = parser.parse_args()

    config = BatchConfig(
        manager=args.manager,
        report_date=args.report_date,
        output_dir=args.output_dir,
        raw_cache_dir=args.raw_cache_dir or args.output_dir / "raw_cache",
        industry_cache_dir=args.industry_cache_dir or args.output_dir / "industry_cache",
        personnel_path=args.personnel,
        candidate_confirmation_path=args.candidate_confirmations,
        history_db=args.history_db or args.output_dir / "fund_holdings_history.sqlite",
        snapshot_date=args.snapshot_date,
        previous_dir=args.previous_dir,
        manager_id=args.manager_id,
        workers=args.workers,
        retries=args.retries,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
        refresh=args.refresh,
        retry_errors=args.retry_errors,
        force_stage=args.force_stage,
        skip_reports=args.skip_reports,
        require_complete_disclosure=not args.allow_incomplete_disclosure,
    )
    manifest = run_batch(config)
    batch_summary = json.loads((args.output_dir / "batch_summary.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "run_key": manifest["run_key"],
        "overall_status": manifest["overall_status"],
        "exit_code": batch_summary["exit_code"],
        "stage_statuses": {stage: record["status"] for stage, record in manifest["stages"].items()},
        "notification_summary": batch_summary["notification_summary"],
        "next_action": batch_summary["next_action"],
        "manifest": str((args.output_dir / "batch_manifest.json").resolve()),
    }, ensure_ascii=False, indent=2))
    if manifest["overall_status"] == "waiting":
        raise SystemExit(2)
    if manifest["overall_status"] == "completed_with_errors":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
