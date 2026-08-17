from __future__ import annotations

import argparse
import json
from pathlib import Path

from .personnel_import import import_research_directory, save_import_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="把研究所通讯录标准化为基金持仓 Agent 人员库")
    parser.add_argument("--input", type=Path, required=True, help="研究所通讯录 XLSX")
    parser.add_argument("--output", type=Path, required=True, help="标准人员库 CSV")
    parser.add_argument("--summary", type=Path, required=True, help="导入质量摘要 JSON")
    parser.add_argument("--sheet-name", default="研究所通讯录")
    parser.add_argument("--organization", required=True, help="机构名称，写入人员库 organization 字段")
    parser.add_argument("--source-date", default="2026-06-16")
    parser.add_argument("--include-contact", action="store_true", help="复制电话和邮箱；默认不复制")
    parser.add_argument("--email-domain", help="机构官方邮箱域名；提供后统计非该域名的遗留邮箱数量")
    parser.add_argument("--overrides", type=Path, help="人工确认的人员新增或覆盖 CSV")
    args = parser.parse_args()

    summary = import_research_directory(
        args.input,
        args.output,
        sheet_name=args.sheet_name,
        organization=args.organization,
        source_date=args.source_date,
        include_contact=args.include_contact,
        email_domain=args.email_domain,
        manual_overrides_path=args.overrides,
    )
    summary_path = save_import_summary(summary, args.summary)
    print(json.dumps({**summary, "summary_file": str(summary_path.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
