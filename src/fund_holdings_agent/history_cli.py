from __future__ import annotations

import argparse
import json
from pathlib import Path

from .history import history_status, ingest_comparison, ingest_quarter


def main() -> None:
    parser = argparse.ArgumentParser(description="基金持仓历史 SQLite 数据库")
    subparsers = parser.add_subparsers(dest="command", required=True)

    quarter = subparsers.add_parser("ingest-quarter", help="幂等写入一个季度结果")
    quarter.add_argument("--db", type=Path, required=True)
    quarter.add_argument("--pipeline", type=Path, required=True)
    quarter.add_argument("--industry", type=Path)

    comparison = subparsers.add_parser("ingest-comparison", help="幂等写入一个相邻季度比较结果")
    comparison.add_argument("--db", type=Path, required=True)
    comparison.add_argument("--comparison", type=Path, required=True)

    status = subparsers.add_parser("status", help="显示数据库完整性、季度和行数")
    status.add_argument("--db", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "ingest-quarter":
        pipeline = json.loads(args.pipeline.read_text(encoding="utf-8"))
        industry = json.loads(args.industry.read_text(encoding="utf-8")) if args.industry else None
        result = ingest_quarter(args.db, pipeline, industry, args.pipeline, args.industry)
    elif args.command == "ingest-comparison":
        comparison_data = json.loads(args.comparison.read_text(encoding="utf-8"))
        result = ingest_comparison(args.db, comparison_data, args.comparison)
    else:
        result = history_status(args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
