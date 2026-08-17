from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .excel_reports import audit_workbook, build_three_quarter_brief_report
from .three_quarter import build_three_quarter_dataset, discover_quarter_inputs, save_three_quarter_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总连续三个季度并生成基金经理持仓简报")
    parser.add_argument("--manager-root", type=Path, required=True, help="包含‘经理_季度’目录的根目录")
    parser.add_argument("--manager", required=True)
    parser.add_argument("--end-report-date", required=True)
    parser.add_argument("--data-output", type=Path, required=True)
    parser.add_argument("--excel-output", type=Path, required=True)
    args = parser.parse_args()

    end_report_date = dt.date.fromisoformat(args.end_report_date)
    inputs = discover_quarter_inputs(args.manager_root, args.manager, end_report_date)
    data = build_three_quarter_dataset(inputs)
    data_path = save_three_quarter_dataset(data, args.data_output)
    excel_path = build_three_quarter_brief_report(data_path, args.excel_output)
    audit = audit_workbook(excel_path, expected_sheets=["01_三季持仓", "99_说明异常"])
    print(
        json.dumps(
            {
                "status": "completed" if audit["valid"] else "failed",
                "manager": data["summary"]["manager"],
                "quarters": data["summary"]["quarters"],
                "product_count": data["summary"]["product_count"],
                "data_output": str(data_path.resolve()),
                "excel_output": str(excel_path.resolve()),
                "workbook_audit": audit,
                "deepseek_used": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if audit["valid"] else 1)


if __name__ == "__main__":
    main()
