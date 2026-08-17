from __future__ import annotations

import argparse
import json
from pathlib import Path

from .company_resources import build_company_resource_packages
from .excel_reports import build_company_resource_report
from .portfolio import atomic_write_json, company_directory_name


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总同一基金公司多位基金经理的研究资源匹配结果")
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--personnel", type=Path)
    parser.add_argument("--skip-report", action="store_true")
    parser.add_argument("--confirm-all-candidates", action="store_true", help="将本次报告中的全部候选登记为业务已确认")
    parser.add_argument("--confirmed-by", default="项目用户", help="业务确认人或确认来源")
    args = parser.parse_args()

    result = build_company_resource_packages(
        args.roster,
        args.input_root,
        args.report_date,
        args.output_root,
        args.personnel,
        args.confirm_all_candidates,
        args.confirmed_by,
    )
    if not args.skip_report:
        for row in result["companies"]:
            company_dir = args.output_root / company_directory_name(row["company"])
            output_path = company_dir / f"{company_directory_name(row['company'])}_{result['quarter']}_研究资源对接汇总.xlsx"
            try:
                build_company_resource_report(Path(row["data_path"]), output_path)
                row["report_path"] = str(output_path.resolve())
                row["report_status"] = "completed"
            except Exception as exc:
                row["report_path"] = str(output_path.resolve())
                row["report_status"] = "failed"
                row["report_error"] = f"工作簿构建失败：{type(exc).__name__}: {exc}"
                result["overall_status"] = "completed_with_errors"
                result["exit_code"] = 3
        atomic_write_json(Path(result["summary_file"]), {key: value for key, value in result.items() if key != "summary_file"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result["exit_code"])


if __name__ == "__main__":
    main()
