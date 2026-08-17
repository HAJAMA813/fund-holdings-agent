from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .models import Fund, Issue


REQUIRED_COLUMNS = {"manager", "fund_code", "fund_name"}


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def clean_fund_code(value: object) -> str:
    match = re.search(r"(\d{6})", clean_text(value))
    return match.group(1) if match else ""


def read_funds_csv(path: Path, report_date: str) -> tuple[list[Fund], list[Issue]]:
    funds: list[Fund] = []
    issues: list[Issue] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"输入名单缺少列: {', '.join(sorted(missing))}")
        for row_no, row in enumerate(reader, start=2):
            manager = clean_text(row.get("manager"))
            code = clean_fund_code(row.get("fund_code"))
            name = clean_text(row.get("fund_name"))
            fund = Fund(
                manager=manager,
                fund_code=code,
                fund_name=name,
                fund_type=clean_text(row.get("fund_type")),
                inception_date=clean_text(row.get("inception_date")),
                input_row=row_no,
            )
            if not code or not manager or not name:
                fund.selected = False
                fund.selection_reason = "输入字段缺失"
                issues.append(Issue("错误", "输入无效", code, name, manager, report_date, f"CSV 第 {row_no} 行基金代码、名称或经理缺失", action="补全名单后重跑"))
            elif fund.inception_date and fund.inception_date > report_date:
                fund.selected = False
                fund.selection_reason = "成立日晚于报告期"
                issues.append(Issue("提示", "报告期不适用", code, name, manager, report_date, f"成立日 {fund.inception_date} 晚于报告期", action="不纳入该报告期正式口径"))
            funds.append(fund)
    return funds, issues


def read_funds_json(path: Path, report_date: str) -> tuple[list[Fund], list[Issue]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("selected_funds")
    if not isinstance(rows, list):
        raise ValueError("基金池 JSON 缺少 selected_funds 数组")
    funds: list[Fund] = []
    issues: list[Issue] = []
    for row_no, row in enumerate(rows, start=1):
        manager = clean_text(row.get("manager"))
        code = clean_fund_code(row.get("fund_code"))
        name = clean_text(row.get("fund_name"))
        if not manager or not code or not name:
            issues.append(Issue("错误", "基金池输入无效", code, name, manager, report_date, f"JSON 第 {row_no} 条缺少经理、代码或名称", action="修复基金池后重跑"))
            continue
        funds.append(
            Fund(
                manager=manager,
                fund_code=code,
                fund_name=name,
                fund_type=clean_text(row.get("fund_type")),
                inception_date=clean_text(row.get("inception_date")),
                input_row=row_no,
                selection_reason=clean_text(row.get("selection_reason")) or "报告期基金池纳入",
            )
        )
    return funds, issues


def read_funds_input(path: Path, report_date: str) -> tuple[list[Fund], list[Issue]]:
    if path.suffix.lower() == ".json":
        return read_funds_json(path, report_date)
    return read_funds_csv(path, report_date)
