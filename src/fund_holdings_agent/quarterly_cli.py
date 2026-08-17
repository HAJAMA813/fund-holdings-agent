from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .batch import BatchConfig, STAGES, run_batch


BEIJING_TIMEZONE = "Asia/Shanghai"


def beijing_now(now: dt.datetime | None = None) -> dt.datetime:
    timezone = ZoneInfo(BEIJING_TIMEZONE)
    if now is None:
        return dt.datetime.now(timezone)
    if now.tzinfo is None:
        raise ValueError("now 必须包含时区信息")
    return now.astimezone(timezone)


def beijing_today(now: dt.datetime | None = None) -> dt.date:
    return beijing_now(now).date()


def latest_closed_quarter(as_of: dt.date) -> dt.date:
    if as_of.month <= 3:
        return dt.date(as_of.year - 1, 12, 31)
    if as_of.month <= 6:
        return dt.date(as_of.year, 3, 31)
    if as_of.month <= 9:
        return dt.date(as_of.year, 6, 30)
    return dt.date(as_of.year, 9, 30)


def previous_quarter(report_date: dt.date) -> dt.date:
    if report_date.month == 3:
        return dt.date(report_date.year - 1, 12, 31)
    if report_date.month == 6:
        return dt.date(report_date.year, 3, 31)
    if report_date.month == 9:
        return dt.date(report_date.year, 6, 30)
    if report_date.month == 12:
        return dt.date(report_date.year, 9, 30)
    raise ValueError("report-date 必须是自然季度末")


def quarter_label(value: dt.date) -> str:
    return f"{value.year}Q{value.month // 3}"


def main() -> None:
    parser = argparse.ArgumentParser(description="供定时器重复调用的季度基金持仓任务入口")
    parser.add_argument("--manager", required=True)
    parser.add_argument("--manager-id", default="")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--as-of", help="调度检查日；不指定时使用北京时间当天")
    parser.add_argument("--report-date", help="可选；不指定时自动选择最近结束的自然季度")
    parser.add_argument("--previous-dir", type=Path, help="可选；默认按输出目录命名规则自动寻找上季度")
    parser.add_argument("--personnel", type=Path, default=Path("data/personnel_template.csv"))
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--raw-cache-dir", type=Path, help="可选；默认使用 output-root/_cache/raw")
    parser.add_argument("--industry-cache-dir", type=Path, help="可选；默认使用 output-root/_cache/industry")
    parser.add_argument("--history-db", type=Path, help="可选；默认使用 output-root/fund_holdings_history.sqlite")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--force-stage", choices=STAGES, default="")
    parser.add_argument("--allow-incomplete-disclosure", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    args = parser.parse_args()

    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else beijing_today()
    report_date = dt.date.fromisoformat(args.report_date) if args.report_date else latest_closed_quarter(as_of)
    previous_date = previous_quarter(report_date)
    output_dir = args.output_root / f"{args.manager}_{quarter_label(report_date)}"
    default_previous = args.output_root / f"{args.manager}_{quarter_label(previous_date)}"
    previous_dir = args.previous_dir or (default_previous if default_previous.exists() else None)

    manifest_path = output_dir / "batch_manifest.json"
    previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    was_waiting = previous_manifest.get("overall_status") == "waiting"
    refresh = args.refresh or was_waiting
    force_stage = args.force_stage or ("holdings" if was_waiting else "")

    config = BatchConfig(
        manager=args.manager,
        manager_id=args.manager_id,
        report_date=report_date.isoformat(),
        output_dir=output_dir,
        raw_cache_dir=args.raw_cache_dir or args.output_root / "_cache" / "raw",
        industry_cache_dir=args.industry_cache_dir or args.output_root / "_cache" / "industry",
        personnel_path=args.personnel,
        candidate_confirmation_path=args.candidate_confirmations,
        history_db=args.history_db or args.output_root / "fund_holdings_history.sqlite",
        snapshot_date=as_of.isoformat(),
        previous_dir=previous_dir,
        workers=args.workers,
        retries=args.retries,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
        refresh=refresh,
        retry_errors=args.retry_errors,
        force_stage=force_stage,
        require_complete_disclosure=not args.allow_incomplete_disclosure,
        skip_reports=args.skip_reports,
    )
    manifest = run_batch(config)
    summary = json.loads((output_dir / "batch_summary.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "manager": args.manager,
                "report_date": report_date.isoformat(),
                "output_dir": str(output_dir.resolve()),
                "auto_refreshed_waiting_run": was_waiting,
                "overall_status": manifest["overall_status"],
                "exit_code": summary["exit_code"],
                "notification_summary": summary["notification_summary"],
                "next_action": summary["next_action"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(summary["exit_code"])


if __name__ == "__main__":
    main()
