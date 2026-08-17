from __future__ import annotations

import argparse
import json
from pathlib import Path

from .manager_funds import CachedFetcher
from .portfolio import ManagerEntry, resolve_manager_for_company, write_manager_roster


def main() -> None:
    parser = argparse.ArgumentParser(description="按基金公司核验经理姓名和天天基金 ID")
    parser.add_argument("--company", required=True)
    parser.add_argument("--names", type=Path, required=True, help="每行一个经理姓名")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.3)
    args = parser.parse_args()

    names = [line.strip() for line in args.names.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(names) != len(set(names)):
        raise ValueError("姓名文件存在重复记录")
    fetcher = CachedFetcher(
        args.cache_dir,
        refresh=args.refresh,
        retries=args.retries,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
    )
    entries: list[ManagerEntry] = []
    issues: list[dict[str, str]] = []
    for name in names:
        try:
            candidate, company = resolve_manager_for_company(name, args.company, fetcher)
            entries.append(ManagerEntry(company or args.company, name, candidate.manager_id))
        except Exception as exc:
            issues.append({"manager": name, "error": f"{type(exc).__name__}: {exc}"})
    if entries:
        write_manager_roster(args.output, entries)
    payload = {
        "expected_company": args.company,
        "input_count": len(names),
        "resolved_count": len(entries),
        "issue_count": len(issues),
        "resolved": [entry.__dict__ for entry in entries],
        "issues": issues,
        "output": str(args.output.resolve()) if entries else "",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if issues:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
