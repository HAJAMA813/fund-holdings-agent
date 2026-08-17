from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candidate_confirmations import build_candidate_confirmation_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="从已确认的公司级候选快照生成可重复使用的候选确认规则库")
    parser.add_argument("--input", type=Path, action="append", required=True, help="公司级研究资源汇总 data.json；可重复提供")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    result = build_candidate_confirmation_registry(args.input, args.output)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["summary_file"] = str(args.summary.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
