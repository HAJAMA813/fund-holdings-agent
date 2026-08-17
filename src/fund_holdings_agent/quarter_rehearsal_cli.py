from __future__ import annotations

import argparse
import json
from pathlib import Path

from .quarter_rehearsal import DEFAULT_TARGET_REPORT_DATE, run_quarter_rehearsal


def main() -> None:
    parser = argparse.ArgumentParser(description="不联网的新季度切换演练")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--target-report-date", default=DEFAULT_TARGET_REPORT_DATE)
    parser.add_argument("--roster", type=Path, default=Path("data/managers_portfolio.csv"))
    parser.add_argument("--personnel", type=Path, default=Path("data/personnel_internal_20260616.csv"))
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = run_quarter_rehearsal(
        project_root=args.project_root,
        output_dir=args.output_dir,
        roster_path=args.roster,
        personnel_path=args.personnel,
        confirmation_path=args.candidate_confirmations,
        target_report_date=args.target_report_date,
    )
    print(
        json.dumps(
            {
                "target_quarter": payload["target_quarter"],
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
    raise SystemExit(0 if payload["overall_status"] == "passed" else 1)


if __name__ == "__main__":
    main()
