from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


CHANGE_ORDER = {"新进": 0, "增持": 1, "减持": 2, "退出": 3, "持平": 4, "无法判定": 5}
INDUSTRY_CHANGE_ORDER = {"新进入前十行业": 0, "上升": 1, "下降": 2, "退出前十行业": 3, "持平": 4}


def compare_quarters(
    previous_pipeline: dict[str, Any],
    current_pipeline: dict[str, Any],
    previous_industry: dict[str, Any],
    current_industry: dict[str, Any],
) -> dict[str, Any]:
    previous_date = previous_pipeline["summary"]["report_date"]
    current_date = current_pipeline["summary"]["report_date"]
    consecutive = _is_consecutive_quarter(previous_date, current_date)
    if not consecutive:
        raise ValueError(f"季度必须相邻且按时间顺序输入：{previous_date} -> {current_date}")

    previous_formal = previous_pipeline["formal_holdings"]
    current_formal = current_pipeline["formal_holdings"]
    previous_industry_map = _stock_industry_map(previous_industry)
    current_industry_map = _stock_industry_map(current_industry)

    company_changes = _company_changes(previous_formal, current_formal, previous_industry_map, current_industry_map)
    fund_stock_changes = _fund_stock_changes(previous_formal, current_formal, previous_industry_map, current_industry_map)
    industry_changes = _industry_changes(previous_industry, current_industry)

    previous_funds = {row["fund_code"] for row in previous_formal}
    current_funds = {row["fund_code"] for row in current_formal}
    previous_snapshot = previous_industry["industry_quality"]["snapshot_date"]
    current_snapshot = current_industry["industry_quality"]["snapshot_date"]
    historical_industry = bool(previous_industry["industry_quality"].get("historical_point_in_time")) and bool(
        current_industry["industry_quality"].get("historical_point_in_time")
    )
    source_errors = previous_pipeline["summary"].get("error_count", 0) + current_pipeline["summary"].get("error_count", 0)

    company_counts = _count_status(company_changes, "change_type")
    industry_counts = _count_status(industry_changes, "change_type")
    checks = [
        _check("相邻季度", "是" if consecutive else "否", "是", "OK" if consecutive else "CHECK", "仅比较相邻自然季度"),
        _check("持仓抓取错误", source_errors, 0, "OK" if source_errors == 0 else "CHECK", "两期基础管道错误数合计"),
        _check(
            "正式基金范围一致",
            "是" if previous_funds == current_funds else "否",
            "是",
            "OK" if previous_funds == current_funds else "INFO",
            "范围不一致可能来自基金新成立、清盘或经理任职变化，应结合基金池解释",
        ),
        _check(
            "行业快照日期一致",
            "是" if previous_snapshot == current_snapshot else "否",
            "是",
            "OK" if previous_snapshot == current_snapshot else "CHECK",
            f"上期={previous_snapshot}；本期={current_snapshot}",
        ),
        _check(
            "历史时点行业口径",
            "是" if historical_industry else "否",
            "是",
            "OK" if historical_industry else "限制",
            "当前公开快照可用于同口径原型比较，但不能证明报告期当时的行业归属",
        ),
    ]
    blocking_checks = [row for row in checks if row["status"] == "CHECK"]
    summary = {
        "manager": _analysis_manager(previous_pipeline, current_pipeline, previous_formal, current_formal),
        "previous_report_date": previous_date,
        "current_report_date": current_date,
        "previous_formal_funds": len(previous_funds),
        "current_formal_funds": len(current_funds),
        "previous_holding_rows": len(previous_formal),
        "current_holding_rows": len(current_formal),
        "company_union_count": len(company_changes),
        "new_company_count": company_counts.get("新进", 0),
        "exited_company_count": company_counts.get("退出", 0),
        "increased_company_count": company_counts.get("增持", 0),
        "decreased_company_count": company_counts.get("减持", 0),
        "unchanged_company_count": company_counts.get("持平", 0),
        "fund_stock_change_count": len(fund_stock_changes),
        "industry_union_count": len(industry_changes),
        "new_industry_count": industry_counts.get("新进入前十行业", 0),
        "exited_industry_count": industry_counts.get("退出前十行业", 0),
        "increased_industry_count": industry_counts.get("上升", 0),
        "decreased_industry_count": industry_counts.get("下降", 0),
        "industry_snapshot_date": current_snapshot,
        "historical_industry_point_in_time": historical_industry,
        "status": "通过（行业时点有限制）" if not blocking_checks else "存在需核查项",
    }
    return {
        "summary": summary,
        "company_changes": company_changes,
        "fund_stock_changes": fund_stock_changes,
        "industry_changes": industry_changes,
        "checks": checks,
        "rules": [
            {"item": "比较范围", "rule": "仅使用两期 A/C/E 去重后的正式版前十大持仓；全量份额不重复计入"},
            {"item": "公司新进/退出", "rule": "股票代码只出现在本期为新进，只出现在上期为退出"},
            {"item": "公司增减持", "rule": "同一股票在正式基金中的披露持股数量合计增加超过0.01万股为增持，减少超过0.01万股为减持，否则为持平"},
            {"item": "基金内变化", "rule": "按基金代码+股票代码分别比较，规则与公司层相同"},
            {"item": "行业变化", "rule": "按申万一级行业汇总两期前十大持仓净值比例算术合计；变化超过0.01个百分点判定上升/下降"},
            {"item": "净值比例", "rule": "跨基金净值比例算术合计仅用于方向判断和勾稽，不代表统一组合真实行业暴露"},
            {"item": "行业时点", "rule": f"两期均使用 {current_snapshot} 当前申万公开快照；历史时点行业成分尚未接入"},
            {"item": "模型调用", "rule": "不调用 DeepSeek 或其他大模型，所有变化标签由确定性规则产生"},
        ],
        "sources": [
            {"item": "上期持仓输入", "path": "previous_pipeline", "report_date": previous_date},
            {"item": "本期持仓输入", "path": "current_pipeline", "report_date": current_date},
            {"item": "上期行业输入", "path": "previous_industry", "report_date": previous_date},
            {"item": "本期行业输入", "path": "current_industry", "report_date": current_date},
        ],
    }


def save_comparison_json(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _company_changes(
    previous_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    previous_industry: dict[str, str],
    current_industry: dict[str, str],
) -> list[dict[str, Any]]:
    previous = _aggregate_companies(previous_rows)
    current = _aggregate_companies(current_rows)
    result = []
    for stock_code in previous.keys() | current.keys():
        old = previous.get(stock_code)
        new = current.get(stock_code)
        change_type = _holding_change_type(old, new)
        old_shares = old["shares_10k"] if old else 0.0
        new_shares = new["shares_10k"] if new else 0.0
        old_market_value = old["market_value_10k"] if old else 0.0
        new_market_value = new["market_value_10k"] if new else 0.0
        old_nav = old["nav_ratio_sum"] if old else 0.0
        new_nav = new["nav_ratio_sum"] if new else 0.0
        reference = new or old or {}
        result.append(
            {
                "change_type": change_type,
                "stock_code": stock_code,
                "stock_name": reference.get("stock_name", ""),
                "market": reference.get("market", ""),
                "sw_level1": current_industry.get(stock_code) or previous_industry.get(stock_code, "待核查"),
                "previous_fund_count": old["fund_count"] if old else 0,
                "current_fund_count": new["fund_count"] if new else 0,
                "previous_fund_codes": old["fund_codes"] if old else "",
                "current_fund_codes": new["fund_codes"] if new else "",
                "previous_shares_10k": old_shares,
                "current_shares_10k": new_shares,
                "shares_change_10k": new_shares - old_shares,
                "shares_change_pct": _change_pct(old_shares, new_shares),
                "previous_market_value_10k": old_market_value,
                "current_market_value_10k": new_market_value,
                "market_value_change_10k": new_market_value - old_market_value,
                "market_value_change_pct": _change_pct(old_market_value, new_market_value),
                "previous_nav_ratio_sum": old_nav,
                "current_nav_ratio_sum": new_nav,
                "nav_ratio_change": new_nav - old_nav,
                "previous_best_rank": old["best_rank"] if old else None,
                "current_best_rank": new["best_rank"] if new else None,
                "rank_improvement": (old["best_rank"] - new["best_rank"]) if old and new else None,
            }
        )
    return sorted(result, key=lambda row: (CHANGE_ORDER[row["change_type"]], -abs(row["nav_ratio_change"]), row["stock_code"]))


def _fund_stock_changes(
    previous_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    previous_industry: dict[str, str],
    current_industry: dict[str, str],
) -> list[dict[str, Any]]:
    previous = {(row["fund_code"], row["stock_code"]): row for row in previous_rows}
    current = {(row["fund_code"], row["stock_code"]): row for row in current_rows}
    result = []
    for fund_code, stock_code in previous.keys() | current.keys():
        old = previous.get((fund_code, stock_code))
        new = current.get((fund_code, stock_code))
        change_type = _holding_change_type(old, new)
        old_shares = _number(old, "shares_10k")
        new_shares = _number(new, "shares_10k")
        old_market_value = _number(old, "market_value_10k")
        new_market_value = _number(new, "market_value_10k")
        old_nav = _number(old, "nav_ratio")
        new_nav = _number(new, "nav_ratio")
        reference = new or old or {}
        result.append(
            {
                "change_type": change_type,
                "fund_code": fund_code,
                "fund_name": reference.get("fund_name", ""),
                "stock_code": stock_code,
                "stock_name": reference.get("stock_name", ""),
                "sw_level1": current_industry.get(stock_code) or previous_industry.get(stock_code, "待核查"),
                "previous_rank": old.get("rank") if old else None,
                "current_rank": new.get("rank") if new else None,
                "rank_improvement": (old["rank"] - new["rank"]) if old and new else None,
                "previous_shares_10k": old_shares,
                "current_shares_10k": new_shares,
                "shares_change_10k": new_shares - old_shares,
                "shares_change_pct": _change_pct(old_shares, new_shares),
                "previous_market_value_10k": old_market_value,
                "current_market_value_10k": new_market_value,
                "market_value_change_10k": new_market_value - old_market_value,
                "previous_nav_ratio": old_nav,
                "current_nav_ratio": new_nav,
                "nav_ratio_change": new_nav - old_nav,
            }
        )
    return sorted(result, key=lambda row: (row["fund_code"], CHANGE_ORDER[row["change_type"]], -abs(row["nav_ratio_change"]), row["stock_code"]))


def _industry_changes(previous_data: dict[str, Any], current_data: dict[str, Any]) -> list[dict[str, Any]]:
    previous = _aggregate_industries(previous_data["industry_summary"])
    current = _aggregate_industries(current_data["industry_summary"])
    result = []
    for industry in previous.keys() | current.keys():
        old = previous.get(industry)
        new = current.get(industry)
        old_nav = old["nav_ratio_sum"] if old else 0.0
        new_nav = new["nav_ratio_sum"] if new else 0.0
        if old is None:
            change_type = "新进入前十行业"
        elif new is None:
            change_type = "退出前十行业"
        elif new_nav - old_nav > 0.0001:
            change_type = "上升"
        elif new_nav - old_nav < -0.0001:
            change_type = "下降"
        else:
            change_type = "持平"
        result.append(
            {
                "change_type": change_type,
                "sw_level1": industry,
                "previous_fund_count": old["fund_count"] if old else 0,
                "current_fund_count": new["fund_count"] if new else 0,
                "previous_fund_codes": old["fund_codes"] if old else "",
                "current_fund_codes": new["fund_codes"] if new else "",
                "previous_holding_count": old["holding_count"] if old else 0,
                "current_holding_count": new["holding_count"] if new else 0,
                "holding_count_change": (new["holding_count"] if new else 0) - (old["holding_count"] if old else 0),
                "previous_market_value_10k": old["market_value_10k"] if old else 0.0,
                "current_market_value_10k": new["market_value_10k"] if new else 0.0,
                "market_value_change_10k": (new["market_value_10k"] if new else 0.0) - (old["market_value_10k"] if old else 0.0),
                "previous_nav_ratio_sum": old_nav,
                "current_nav_ratio_sum": new_nav,
                "nav_ratio_change": new_nav - old_nav,
            }
        )
    return sorted(result, key=lambda row: (INDUSTRY_CHANGE_ORDER[row["change_type"]], -abs(row["nav_ratio_change"]), row["sw_level1"]))


def _aggregate_companies(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        target = grouped.setdefault(
            row["stock_code"],
            {
                "stock_name": row["stock_name"],
                "market": row.get("market", ""),
                "fund_codes_set": set(),
                "shares_10k": 0.0,
                "market_value_10k": 0.0,
                "nav_ratio_sum": 0.0,
                "best_rank": row["rank"],
            },
        )
        target["fund_codes_set"].add(row["fund_code"])
        target["shares_10k"] += _number(row, "shares_10k")
        target["market_value_10k"] += _number(row, "market_value_10k")
        target["nav_ratio_sum"] += _number(row, "nav_ratio")
        target["best_rank"] = min(target["best_rank"], row["rank"])
    for target in grouped.values():
        target["fund_count"] = len(target["fund_codes_set"])
        target["fund_codes"] = "、".join(sorted(target.pop("fund_codes_set")))
    return grouped


def _aggregate_industries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"fund_codes_set": set(), "holding_count": 0, "market_value_10k": 0.0, "nav_ratio_sum": 0.0}
    )
    for row in rows:
        target = grouped[row["sw_level1"]]
        target["fund_codes_set"].add(row["fund_code"])
        target["holding_count"] += int(row["holding_count"])
        target["market_value_10k"] += _number(row, "market_value_10k")
        target["nav_ratio_sum"] += _number(row, "nav_ratio")
    result = {}
    for industry, target in grouped.items():
        result[industry] = {
            "fund_count": len(target["fund_codes_set"]),
            "fund_codes": "、".join(sorted(target["fund_codes_set"])),
            "holding_count": target["holding_count"],
            "market_value_10k": target["market_value_10k"],
            "nav_ratio_sum": target["nav_ratio_sum"],
        }
    return result


def _stock_industry_map(data: dict[str, Any]) -> dict[str, str]:
    return {row["stock_code"]: row["sw_level1"] for row in data["stock_industry_mapping"]}


def _holding_change_type(old: dict[str, Any] | None, new: dict[str, Any] | None) -> str:
    if old is None:
        return "新进"
    if new is None:
        return "退出"
    old_shares = _number(old, "shares_10k")
    new_shares = _number(new, "shares_10k")
    if new_shares - old_shares > 0.01:
        return "增持"
    if new_shares - old_shares < -0.01:
        return "减持"
    return "持平"


def _number(row: dict[str, Any] | None, key: str) -> float:
    return float((row or {}).get(key) or 0.0)


def _change_pct(old: float, new: float) -> float | None:
    return (new - old) / abs(old) if old else None


def _is_consecutive_quarter(previous: str, current: str) -> bool:
    previous_date = dt.date.fromisoformat(previous)
    current_date = dt.date.fromisoformat(current)
    quarter_ends = {(3, 31): 1, (6, 30): 2, (9, 30): 3, (12, 31): 4}
    if (previous_date.month, previous_date.day) not in quarter_ends or (current_date.month, current_date.day) not in quarter_ends:
        return False
    previous_index = previous_date.year * 4 + quarter_ends[(previous_date.month, previous_date.day)]
    current_index = current_date.year * 4 + quarter_ends[(current_date.month, current_date.day)]
    return current_index - previous_index == 1


def _manager_name(rows: list[dict[str, Any]]) -> str:
    managers = sorted({str(row.get("manager", "")) for row in rows if row.get("manager")})
    return "、".join(managers)


def _analysis_manager(
    previous_pipeline: dict[str, Any],
    current_pipeline: dict[str, Any],
    previous_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
) -> str:
    """Return the requested analysis manager, not co-manager text from disclosures."""
    return (
        str(current_pipeline.get("summary", {}).get("manager", "")).strip()
        or str(previous_pipeline.get("summary", {}).get("manager", "")).strip()
        or _manager_name(current_rows)
        or _manager_name(previous_rows)
    )


def _count_status(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row[key]] += 1
    return dict(counts)


def _check(item: str, actual: Any, expected: Any, status: str, note: str) -> dict[str, Any]:
    return {"item": item, "actual": actual, "expected": expected, "status": status, "note": note}
