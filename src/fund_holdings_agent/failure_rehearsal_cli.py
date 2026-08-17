from __future__ import annotations

import argparse
import json
from pathlib import Path

from .failure_rehearsal import run_failure_rehearsal


def main() -> None:
    parser = argparse.ArgumentParser(description="离线注入网络、网页、空持仓和缓存故障并验证恢复")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report-date", default="2026-06-30")
    args = parser.parse_args()
    payload = run_failure_rehearsal(args.output_dir, args.report_date)
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
    raise SystemExit(0 if payload["overall_status"] == "passed" else 1)


if __name__ == "__main__":
    main()
