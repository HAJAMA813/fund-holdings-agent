from __future__ import annotations

import argparse
import json
from pathlib import Path

from .excel_reports import build_manager_fund_pool_report
from .manager_funds import CachedFetcher, get_manager_funds


def main() -> None:
    parser = argparse.ArgumentParser(description="按基金经理和报告期生成历史时点基金池")
    parser.add_argument("--manager", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--manager-id", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json-only", action="store_true", help="只生成可审计 JSON，不生成 Excel")
    parser.add_argument("--sleep-seconds", type=float, default=0.3)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fetcher = CachedFetcher(
        args.output_dir / "raw_cache",
        refresh=args.refresh,
        retries=3,
        timeout=20,
        sleep_seconds=args.sleep_seconds,
    )
    data = get_manager_funds(args.manager, args.report_date, fetcher, args.manager_id)
    json_path = args.output_dir / "manager_fund_pool_data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
        print(f"JSON={json_path}")
        return

    workbook_path = args.output_dir / f"基金经理基金池_{args.manager}_{args.report_date}.xlsx"
    build_manager_fund_pool_report(json_path, workbook_path)
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    print(f"JSON={json_path}")
    print(f"XLSX={workbook_path}")


if __name__ == "__main__":
    main()
