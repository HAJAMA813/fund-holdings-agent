from __future__ import annotations

import argparse
import json
from pathlib import Path

from .excel_reports import build_quarter_comparison_report
from .quarter_compare import compare_quarters, save_comparison_json


def main() -> None:
    parser = argparse.ArgumentParser(description="比较相邻季度基金前十大持仓和申万一级行业变化")
    parser.add_argument("--previous", type=Path, required=True, help="上期 pipeline_data.json")
    parser.add_argument("--current", type=Path, required=True, help="本期 pipeline_data.json")
    parser.add_argument("--previous-industry", type=Path, required=True, help="上期 industry_analysis_data.json")
    parser.add_argument("--current-industry", type=Path, required=True, help="本期 industry_analysis_data.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--output-name", default="基金季度持仓变化分析.xlsx")
    args = parser.parse_args()

    inputs = [json.loads(path.read_text(encoding="utf-8")) for path in [args.previous, args.current, args.previous_industry, args.current_industry]]
    data = compare_quarters(*inputs)
    data["sources"] = [
        {"item": "上期持仓输入", "path": str(args.previous), "report_date": data["summary"]["previous_report_date"]},
        {"item": "本期持仓输入", "path": str(args.current), "report_date": data["summary"]["current_report_date"]},
        {"item": "上期行业输入", "path": str(args.previous_industry), "report_date": data["summary"]["previous_report_date"]},
        {"item": "本期行业输入", "path": str(args.current_industry), "report_date": data["summary"]["current_report_date"]},
    ]
    json_path = save_comparison_json(data, args.output_dir / "quarter_comparison_data.json")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    print(f"JSON={json_path}")
    if args.json_only:
        return

    output_path = args.output_dir / args.output_name
    build_quarter_comparison_report(json_path, output_path)
    print(f"XLSX={output_path}")


if __name__ == "__main__":
    main()
