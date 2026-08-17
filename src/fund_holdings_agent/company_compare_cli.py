from __future__ import annotations

import argparse
import json
from pathlib import Path

from .company_compare import build_company_comparison, save_company_comparison


def main() -> None:
    parser = argparse.ArgumentParser(description="生成基金公司相邻季度去重比较数据")
    parser.add_argument("--previous-summary", type=Path, required=True)
    parser.add_argument("--current-summary", type=Path, required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = build_company_comparison(args.previous_summary, args.current_summary, args.company)
    output = save_company_comparison(data, args.output)
    print(json.dumps({"output": str(output.resolve()), "summary": data["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
