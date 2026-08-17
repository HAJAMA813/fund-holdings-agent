from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .acceptance import build_phase1_acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description="运行基金持仓 Agent 第一阶段确定性验收")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--roster", type=Path, default=Path("data/managers_portfolio.csv"))
    parser.add_argument("--backfill-summary", type=Path, required=True)
    parser.add_argument("--company-summary", type=Path, required=True)
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()

    test_result = None
    if args.run_tests:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=args.project_root,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout + completed.stderr).strip()
        test_result = {
            "passed": completed.returncode == 0,
            "exit_code": completed.returncode,
            "summary": output.splitlines()[-1] if output else "pytest 未输出摘要",
        }

    result = build_phase1_acceptance(
        args.project_root,
        args.roster,
        args.backfill_summary,
        args.company_summary,
        args.candidate_confirmations,
        args.output,
        test_result,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["overall_status"] == "accepted_with_caveats" else 3)


if __name__ == "__main__":
    main()
