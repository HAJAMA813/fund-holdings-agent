from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from .deployment_healthcheck import build_deployment_healthcheck


def _run_tests(project_root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "summary": output.splitlines()[-1] if output else "pytest 未输出摘要",
    }


def _check_network(timeout: int) -> dict[str, object]:
    urls = [
        "https://fund.eastmoney.com/",
        "https://fundf10.eastmoney.com/",
    ]
    results: list[str] = []
    passed = True
    for url in urls:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 fund-holdings-agent-healthcheck"})
            with urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                response.read(256)
            results.append(f"{url} HTTP {status}")
            passed = passed and 200 <= status < 400
        except OSError as exc:
            passed = False
            results.append(f"{url} {exc}")
    return {"passed": passed, "evidence": "；".join(results)}


def main() -> None:
    parser = argparse.ArgumentParser(description="运行基金持仓 Agent 上线前健康检查")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--portfolio-root", type=Path, default=Path("outputs/quarterly/portfolio"))
    parser.add_argument("--roster", type=Path, default=Path("data/managers_portfolio.csv"))
    parser.add_argument("--personnel", type=Path, default=Path("data/personnel_internal_20260616.csv"))
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"))
    parser.add_argument("--backfill-summary", type=Path, default=Path("outputs/personnel_import/20260616/resource_backfill_summary_2026Q2_confirmed.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/019fff23-cef4-7d91-8837-7401263c06d4/deployment_healthcheck"))
    parser.add_argument("--report-date", help="默认按北京时间选择最近结束的自然季度")
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--check-network", action="store_true", help="会真实访问天天基金/东方财富，仅在部署主机使用")
    parser.add_argument("--network-timeout", type=int, default=10)
    args = parser.parse_args()

    import datetime as dt

    report_date = dt.date.fromisoformat(args.report_date) if args.report_date else None
    test_result = _run_tests(args.project_root) if args.run_tests else None
    network_result = _check_network(args.network_timeout) if args.check_network else None
    result = build_deployment_healthcheck(
        args.project_root,
        args.portfolio_root,
        args.roster,
        args.personnel,
        args.candidate_confirmations,
        args.backfill_summary,
        args.output_dir,
        report_date=report_date,
        min_free_gb=args.min_free_gb,
        network_result=network_result,
        test_result=test_result,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(3 if result["manual_run_readiness"] == "BLOCKED" else 0)


if __name__ == "__main__":
    main()
