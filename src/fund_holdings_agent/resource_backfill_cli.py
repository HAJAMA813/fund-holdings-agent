from __future__ import annotations

import argparse
import json
from pathlib import Path

from .resource_backfill import backfill_portfolio_resources


def main() -> None:
    parser = argparse.ArgumentParser(description="使用指定人员库回填已有基金经理季度研究资源匹配结果")
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--personnel", type=Path, required=True)
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    payload = backfill_portfolio_resources(
        args.roster,
        args.output_root,
        args.report_date,
        args.personnel,
        args.summary,
        args.candidate_confirmations,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(payload["exit_code"])


if __name__ == "__main__":
    main()
