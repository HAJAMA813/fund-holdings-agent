from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .excel_reports import build_holdings_report
from .industry import IndustryFetcher, enrich_industries, save_industry_json


def main() -> None:
    parser = argparse.ArgumentParser(description="为基金持仓匹配申万一级行业并生成行业分析")
    parser.add_argument("--input", type=Path, required=True, help="持仓管道 pipeline_data.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--snapshot-date", default=dt.date.today().isoformat())
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--output-name", default="基金持仓_申万一级行业分析.xlsx")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pipeline_data = json.loads(args.input.read_text(encoding="utf-8"))
    fetcher = IndustryFetcher(args.output_dir / "industry_cache", refresh=args.refresh)
    data = enrich_industries(pipeline_data, args.snapshot_date, fetcher, max_workers=args.workers)
    json_path = save_industry_json(data, args.output_dir / "industry_analysis_data.json")
    print(json.dumps(data["industry_quality"], ensure_ascii=False, indent=2))
    print(f"JSON={json_path}")
    if args.json_only:
        return
    output_path = args.output_dir / args.output_name
    build_holdings_report(json_path, output_path)
    print(f"XLSX={output_path}")


if __name__ == "__main__":
    main()
