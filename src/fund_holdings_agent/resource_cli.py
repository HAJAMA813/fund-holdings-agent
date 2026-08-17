from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candidate_confirmations import read_candidate_confirmation_csv
from .excel_reports import build_resource_report
from .resource_matching import build_resource_matching, read_personnel_csv, save_resource_json


def main() -> None:
    parser = argparse.ArgumentParser(description="根据基金持仓行业生成研究员/专家对接需求与匹配结果")
    parser.add_argument("--input", type=Path, required=True, help="industry_analysis_data.json")
    parser.add_argument("--personnel", type=Path, required=True, help="内部人员库 CSV")
    parser.add_argument("--candidate-confirmations", type=Path, default=Path("data/resource_candidate_confirmations.csv"), help="候选确认规则库 CSV")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--output-name", default="研究资源对接准备.xlsx")
    args = parser.parse_args()

    industry_data = json.loads(args.input.read_text(encoding="utf-8"))
    people, issues = read_personnel_csv(args.personnel)
    confirmations, confirmation_issues = read_candidate_confirmation_csv(args.candidate_confirmations)
    data = build_resource_matching(
        industry_data,
        people,
        issues,
        confirmations,
        confirmation_issues,
        str(args.candidate_confirmations.resolve()) if args.candidate_confirmations.exists() else "",
    )
    json_path = save_resource_json(data, args.output_dir / "resource_matching_data.json")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    print(f"JSON={json_path}")
    if args.json_only:
        return
    output_path = args.output_dir / args.output_name
    build_resource_report(json_path, output_path)
    print(f"XLSX={output_path}")


if __name__ == "__main__":
    main()
