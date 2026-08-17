from __future__ import annotations

import argparse
import json
from pathlib import Path

from .excel_reports import build_preproduction_replay_report, build_quarter_comparison_report
from .preproduction_replay import build_preproduction_replay


def main() -> None:
    parser = argparse.ArgumentParser(description="使用本地真实结果运行相邻季度全量准生产回放")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--portfolio-root", type=Path, default=Path("outputs/quarterly/portfolio"))
    parser.add_argument("--roster", type=Path, default=Path("data/managers_portfolio.csv"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--previous-report-date", default="2026-03-31")
    parser.add_argument("--current-report-date", default="2026-06-30")
    parser.add_argument("--skip-workbooks", action="store_true")
    args = parser.parse_args()

    payload = build_preproduction_replay(
        project_root=args.project_root,
        portfolio_root=args.portfolio_root,
        roster_path=args.roster,
        output_dir=args.output_dir,
        previous_report_date=args.previous_report_date,
        current_report_date=args.current_report_date,
    )
    if not args.skip_workbooks:
        for row in payload["outputs"]["company_outputs"]:
            build_quarter_comparison_report(Path(row["data_path"]), Path(row["workbook_path"]))
        build_preproduction_replay_report(Path(payload["outputs"]["summary_json"]), Path(payload["outputs"]["summary_workbook"]))
    print(
        json.dumps(
            {
                "overall_status": payload["overall_status"],
                "passed_check_count": payload["passed_check_count"],
                "failed_check_count": payload["failed_check_count"],
                "network_used": payload["network_used"],
                "deepseek_used": payload["deepseek_used"],
                "outputs": payload["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if payload["failed_check_count"] == 0 else 3)


if __name__ == "__main__":
    main()
