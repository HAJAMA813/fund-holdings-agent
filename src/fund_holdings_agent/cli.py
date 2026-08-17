from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .excel_reports import build_holdings_report
from .manager_funds import CachedFetcher
from .pipeline import run_pipeline, save_json_outputs


def configure_logging(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)], force=True)
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取、清洗、校验并导出基金季度前十大持仓")
    parser.add_argument("--input", type=Path, required=True, help="基金名单 CSV，或 get_manager_funds 生成的 JSON")
    parser.add_argument("--report-date", required=True, help="季度末日期 YYYY-MM-DD")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.8)
    parser.add_argument("--skip-xlsx", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="忽略网页缓存重新抓取")
    parser.add_argument("--output-name", default="", help="自定义 Excel 文件名")
    args = parser.parse_args(argv)

    log_path = configure_logging(args.output_dir)
    fetcher = CachedFetcher(args.output_dir / "raw_cache", refresh=args.refresh, retries=args.retries, timeout=args.timeout, sleep_seconds=args.sleep)
    data = run_pipeline(args.input, args.report_date, args.retries, args.timeout, args.sleep, fetcher)
    data_path, summary_path = save_json_outputs(data, args.output_dir)
    default_name = f"fund_holdings_{args.report_date[:4]}Q{(int(args.report_date[5:7]) - 1) // 3 + 1}.xlsx"
    xlsx_path = args.output_dir / (args.output_name or default_name)
    if not args.skip_xlsx:
        build_holdings_report(data_path, xlsx_path)
    logging.info("完成: data=%s summary=%s xlsx=%s log=%s", data_path, summary_path, xlsx_path, log_path)
    print(f"OUTPUT={xlsx_path}")
    print(f"SUMMARY={summary_path}")
    return 0
