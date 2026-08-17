from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .dedup import base_name, share_priority


READY = "已披露"
PENDING = "待披露"
FAILED = "抓取失败"
PERIOD_MISMATCH = "报告期不一致"
INCOMPLETE = "数据不完整"


def assess_disclosure(pipeline: dict[str, Any]) -> dict[str, Any]:
    report_date = str(pipeline.get("summary", {}).get("report_date", ""))
    rows_by_fund: dict[str, list[dict[str, Any]]] = {}
    for row in pipeline.get("all_holdings", []):
        rows_by_fund.setdefault(str(row.get("fund_code", "")), []).append(row)

    issue_categories: dict[str, set[str]] = {}
    for issue in pipeline.get("issues", []):
        code = str(issue.get("fund_code", ""))
        if code:
            issue_categories.setdefault(code, set()).add(str(issue.get("category", "")))

    records: list[dict[str, Any]] = []
    for fund in pipeline.get("funds", []):
        if not fund.get("selected"):
            continue
        code = str(fund.get("fund_code", ""))
        rows = rows_by_fund.get(code, [])
        row_dates = sorted({str(row.get("report_date", "")) for row in rows if row.get("report_date")})
        fetch_status = str(fund.get("fetch_status", ""))
        categories = issue_categories.get(code, set())
        if rows and row_dates == [report_date] and fetch_status == "已抓取":
            status = READY
            reason = f"目标报告期已解析 {len(rows)} 条股票持仓"
            retryable = False
        elif rows and row_dates != [report_date]:
            status = PERIOD_MISMATCH
            reason = f"目标报告期={report_date}；持仓行报告期={','.join(row_dates) or '空'}"
            retryable = True
        elif fetch_status == "请求失败" or "持仓请求失败" in categories:
            status = FAILED
            reason = "持仓请求失败，需要重试"
            retryable = True
        elif fetch_status == "无持仓/待核实" or "持仓为空" in categories:
            status = PENDING
            reason = "目标报告期暂无可解析股票持仓，可能尚未披露或产品不适用"
            retryable = True
        else:
            status = INCOMPLETE
            reason = f"抓取状态={fetch_status or '空'}，未形成有效持仓"
            retryable = True
        records.append(
            {
                "fund_code": code,
                "fund_name": fund.get("fund_name", ""),
                "report_date": report_date,
                "fetch_status": fetch_status,
                "holding_count": len(rows),
                "holding_report_dates": row_dates,
                "readiness_status": status,
                "reason": reason,
                "retryable": retryable,
            }
        )

    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        group_name = base_name(str(record.get("fund_name", ""))) or str(record.get("fund_code", ""))
        record["product_base_name"] = group_name
        groups.setdefault(group_name, []).append(record)

    gate_counts: Counter[str] = Counter()
    ready_share_count = 0
    for group_records in groups.values():
        ready_records = [record for record in group_records if record["readiness_status"] == READY]
        candidates = ready_records or group_records
        representative = min(
            candidates,
            key=lambda record: share_priority(str(record.get("fund_name", "")), str(record.get("fund_code", ""))),
        )
        representative_code = representative["fund_code"]
        if ready_records:
            gate_counts[READY] += 1
        else:
            gate_counts[representative["readiness_status"]] += 1
        for record in group_records:
            if record["readiness_status"] == READY:
                ready_share_count += 1
            record["representative_fund_code"] = representative_code
            record["gate_required"] = record is representative
            if record is representative:
                record["gate_status"] = "通过" if ready_records else "阻断"
            else:
                record["gate_status"] = "份额重复不阻断"

    selected_share_count = len(records)
    selected_product_count = len(groups)
    ready_product_count = gate_counts[READY]
    is_ready = ready_product_count == selected_product_count
    pending_product_count = selected_product_count - ready_product_count
    summary = {
        "report_date": report_date,
        "selected_fund_count": selected_product_count,
        "ready_fund_count": ready_product_count,
        "pending_fund_count": pending_product_count,
        "selected_share_count": selected_share_count,
        "ready_share_count": ready_share_count,
        "selected_product_count": selected_product_count,
        "ready_product_count": ready_product_count,
        "pending_product_count": pending_product_count,
        "failed_fund_count": gate_counts[FAILED],
        "period_mismatch_count": gate_counts[PERIOD_MISMATCH],
        "incomplete_fund_count": gate_counts[INCOMPLETE],
        "readiness_rate": ready_product_count / selected_product_count if selected_product_count else 1.0,
        "is_ready": is_ready,
        "status": "无适用产品" if not selected_product_count else ("披露完整" if is_ready else "等待披露完整"),
    }
    return {
        "summary": summary,
        "fund_readiness": records,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "rules": [
            "仅检查基金池中 selected=true 的基金份额，并按基础产品形成披露闸门",
            "同一基础产品的 A/C/E 等份额只需一个代表份额解析到目标报告期股票持仓",
            "少于十条但大于零视为已披露，按实际披露保留",
            "代表份额请求失败、目标报告期缺失或持仓为空会阻止默认正式运行",
            "确认产品确实不适用时，可在人工复核后显式允许不完整运行",
        ],
    }


def save_disclosure_json(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
