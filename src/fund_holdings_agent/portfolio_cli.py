from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path

from .batch import BatchConfig, STAGES, run_batch
from .excel_reports import build_company_portfolio_report
from .portfolio import (
    aggregate_portfolio_metrics,
    aggregate_portfolio_status,
    atomic_write_json,
    atomic_write_text,
    company_directory_name,
    portfolio_notification,
    portfolio_run_receipt,
    read_manager_roster,
)
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now, beijing_today, latest_closed_quarter, previous_quarter, quarter_label


def main() -> None:
    parser = argparse.ArgumentParser(description="批量运行基金公司经理季度持仓任务")
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--company-report-output-root", type=Path)
    parser.add_argument("--as-of", help="调度检查日；不指定时使用北京时间当天")
    parser.add_argument("--report-date")
    parser.add_argument("--personnel", type=Path, default=Path("data/personnel_template.csv"))
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--force-stage", choices=STAGES, default="")
    parser.add_argument("--allow-incomplete-disclosure", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument("--skip-company-report", action="store_true")
    parser.add_argument("--friendly-output", action="store_true", help="输出适合Mac菜单用户阅读的进度信息")
    args = parser.parse_args()
    if args.friendly_output:
        logging.basicConfig(level=logging.WARNING, format="[网络重试] %(message)s", force=True)

    entries = read_manager_roster(args.roster)
    companies = {entry.company for entry in entries}
    company_label = "、".join(sorted(companies))
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else beijing_today()
    report_date = dt.date.fromisoformat(args.report_date) if args.report_date else latest_closed_quarter(as_of)
    previous_date = previous_quarter(report_date)
    results: list[dict[str, object]] = []

    total = len(entries)
    stage_labels = {
        "fund_pool": "获取报告期基金池",
        "holdings": "抓取前十大持仓",
        "readiness": "检查季度披露",
        "industry": "匹配申万行业",
        "resources": "匹配研究资源",
        "history": "写入历史数据库",
        "comparison": "比较相邻季度",
        "reports": "生成逐经理Excel",
    }
    for position, entry in enumerate(entries, start=1):
        if args.friendly_output:
            print(f"\n[{position}/{total}] {entry.company} / {entry.manager}", flush=True)
        company_root = args.output_root / company_directory_name(entry.company)
        output_dir = company_root / f"{entry.manager}_{quarter_label(report_date)}"
        previous_dir_candidate = company_root / f"{entry.manager}_{quarter_label(previous_date)}"
        previous_dir = previous_dir_candidate if previous_dir_candidate.exists() else None
        manifest_path = output_dir / "batch_manifest.json"
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        was_waiting = old_manifest.get("overall_status") == "waiting"
        config = BatchConfig(
            manager=entry.manager,
            manager_id=entry.manager_id,
            report_date=report_date.isoformat(),
            output_dir=output_dir,
            raw_cache_dir=args.output_root / "_cache" / "raw",
            industry_cache_dir=args.output_root / "_cache" / "industry",
            personnel_path=args.personnel,
            candidate_confirmation_path=args.candidate_confirmations,
            history_db=args.output_root / "fund_holdings_history.sqlite",
            snapshot_date=as_of.isoformat(),
            previous_dir=previous_dir,
            workers=args.workers,
            retries=args.retries,
            timeout=args.timeout,
            sleep_seconds=args.sleep,
            refresh=args.refresh or was_waiting,
            retry_errors=args.retry_errors,
            force_stage=args.force_stage or ("holdings" if was_waiting else ""),
            require_complete_disclosure=not args.allow_incomplete_disclosure,
            skip_reports=args.skip_reports,
        )
        try:
            def show_progress(stage: str, status: str) -> None:
                if status == "running":
                    print(f"  · {stage_labels.get(stage, stage)}...", flush=True)
                elif status == "failed":
                    print(f"  × {stage_labels.get(stage, stage)}失败", flush=True)

            manifest = run_batch(config, progress=show_progress if args.friendly_output else None)
            summary = json.loads((output_dir / "batch_summary.json").read_text(encoding="utf-8"))
            results.append(
                {
                    "company": entry.company,
                    "manager": entry.manager,
                    "manager_id": entry.manager_id,
                    "overall_status": manifest["overall_status"],
                    "exit_code": summary["exit_code"],
                    "notification_summary": summary["notification_summary"],
                    "output_dir": str(output_dir.resolve()),
                    "manifest": str(manifest_path.resolve()),
                }
            )
            if args.friendly_output:
                print(f"  ✓ {entry.manager}：{manifest['overall_status']}", flush=True)
        except Exception as exc:
            results.append(
                {
                    "company": entry.company,
                    "manager": entry.manager,
                    "manager_id": entry.manager_id,
                    "overall_status": "failed",
                    "exit_code": 1,
                    "notification_summary": f"{entry.manager}：{type(exc).__name__}: {exc}",
                    "output_dir": str(output_dir.resolve()),
                    "manifest": str(manifest_path.resolve()),
                }
            )
            if args.friendly_output:
                print(f"  × {entry.manager}：运行失败，已记录异常并继续下一位", flush=True)

    overall_status, exit_code = aggregate_portfolio_status(results)
    notification = portfolio_notification(company_label, report_date.isoformat(), results)
    payload: dict[str, object] = {
        "companies": sorted(companies),
        "report_date": report_date.isoformat(),
        "as_of": as_of.isoformat(),
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "overall_status": overall_status,
        "exit_code": exit_code,
        "notification_summary": notification,
        "metrics": aggregate_portfolio_metrics(results),
        "manager_results": results,
    }
    summary_path = atomic_write_json(args.output_root / f"portfolio_summary_{quarter_label(report_date)}.json", payload)
    company_reports: list[dict[str, object]] = []
    if not args.skip_company_report:
        for company in sorted(companies):
            company_results = [row for row in results if row["company"] == company]
            company_status, company_exit_code = aggregate_portfolio_status(company_results)
            company_root = args.output_root / company_directory_name(company)
            company_payload: dict[str, object] = {
                "companies": [company],
                "report_date": report_date.isoformat(),
                "as_of": as_of.isoformat(),
                "overall_status": company_status,
                "exit_code": company_exit_code,
                "notification_summary": portfolio_notification(company, report_date.isoformat(), company_results),
                "metrics": aggregate_portfolio_metrics(company_results),
                "manager_results": company_results,
            }
            company_summary_path = atomic_write_json(
                company_root / f"portfolio_summary_{quarter_label(report_date)}.json",
                company_payload,
            )
            report_root = (args.company_report_output_root or args.output_root) / company_directory_name(company)
            manager_suffix = f"_{company_results[0]['manager']}" if len(company_results) == 1 else ""
            report_path = report_root / f"{company_directory_name(company)}{manager_suffix}_{quarter_label(report_date)}_基金经理持仓分析.xlsx"
            report_result: dict[str, object] = {
                "company": company,
                "summary_path": str(company_summary_path.resolve()),
                "output_path": str(report_path.resolve()),
            }
            if company_status in {"completed", "completed_with_errors"}:
                try:
                    build_company_portfolio_report(company_summary_path, report_path)
                    report_result["status"] = "completed"
                except Exception as exc:
                    report_result["status"] = "failed"
                    report_result["error"] = f"{type(exc).__name__}: {exc}"
                    if overall_status == "completed":
                        overall_status, exit_code = "completed_with_errors", 3
            else:
                report_result["status"] = "not_generated"
                report_result["reason"] = f"公司任务状态为 {company_status}"
            company_reports.append(report_result)
    payload["company_reports"] = company_reports
    payload["overall_status"] = overall_status
    payload["exit_code"] = exit_code
    receipt_path = args.output_root / f"portfolio_notification_{quarter_label(report_date)}.txt"
    payload["notification_path"] = str(receipt_path.resolve())
    summary_path = atomic_write_json(summary_path, payload)
    atomic_write_text(receipt_path, portfolio_run_receipt(payload))
    if args.friendly_output:
        print("\n运行结束", flush=True)
        print(f"总体状态：{overall_status}", flush=True)
        for row in company_reports:
            print(f"Excel：{row['output_path']}（{row.get('status', '')}）", flush=True)
    else:
        print(json.dumps({**payload, "summary_path": str(summary_path.resolve())}, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
