from __future__ import annotations

import argparse
import json
from pathlib import Path

from .disclosure import assess_disclosure, save_disclosure_json


def main() -> None:
    parser = argparse.ArgumentParser(description="检查指定季度基金持仓披露是否完整")
    parser.add_argument("--input", type=Path, required=True, help="pipeline_data.json")
    parser.add_argument("--output", type=Path, help="默认写入输入文件同目录的 disclosure_readiness.json")
    args = parser.parse_args()

    pipeline = json.loads(args.input.read_text(encoding="utf-8"))
    result = assess_disclosure(pipeline)
    output = save_disclosure_json(result, args.output or args.input.parent / "disclosure_readiness.json")
    print(json.dumps({**result["summary"], "output": str(output.resolve())}, ensure_ascii=False, indent=2))
    if not result["summary"]["is_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
