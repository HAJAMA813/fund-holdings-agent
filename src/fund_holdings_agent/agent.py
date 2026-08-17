"""多步工具编排 Agent：让模型自主规划、调用确定性工具、观察结果并最终回答。

与单轮问答（llm_agent.answer_question）的区别：本模块实现「计划 → 选工具 → 执行 →
观察 → 再决定」的循环。模型只做编排与解释；所有工具都是只读的确定性函数，读取
已验证 JSON 产物，绝不写入或计算事实数据。没有 DeepSeek Key 时直接返回未就绪。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm_agent import DeepSeekClient, build_evidence_pack, locate_manager_quarter_dir, _load_dotenv
from .portfolio import company_directory_name, read_manager_roster

AGENT_SYSTEM_PROMPT = (
    "你是一名基金持仓分析 Agent。你可以调用工具来获取已经由确定性管道生成、可验证的基金持仓数据。"
    "硬性规则：1) 先用工具查清事实再回答，绝不编造基金、持仓、行业、人员或数值；"
    "2) 工具返回的都是已验证 JSON，回答时引用其中的字段或来源；"
    "3) 工具返回错误或数据缺失时直接说明，不要猜测；"
    "4) 涉及跨产品市值或净值比例合计时，标注「算术汇总，不代表统一组合加权仓位」；"
    "5) 港股/海外股票按原始标记处理，不强行归入申万行业；"
    "6) 最终回答用中文、简明，并说明你调用了哪些工具；"
    "7) 你不是实时行情，也不构成投资建议。"
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_managers",
            "description": "列出可分析的基金经理（按基金公司分组）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_quarters",
            "description": "列出某基金经理已生成数据的季度及其报告期",
            "parameters": {
                "type": "object",
                "properties": {"manager": {"type": "string", "description": "基金经理姓名"}},
                "required": ["manager"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manager_overview",
            "description": "获取某经理某季度的持仓、申万行业暴露、研究资源、季度变化与异常概览",
            "parameters": {
                "type": "object",
                "properties": {
                    "manager": {"type": "string"},
                    "report_date": {"type": "string", "description": "报告期，格式 YYYY-MM-DD"},
                },
                "required": ["manager", "report_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_managers",
            "description": "对比两位经理同一季度的申万行业暴露与重仓股",
            "parameters": {
                "type": "object",
                "properties": {
                    "manager_a": {"type": "string"},
                    "manager_b": {"type": "string"},
                    "report_date": {"type": "string", "description": "报告期，格式 YYYY-MM-DD"},
                },
                "required": ["manager_a", "manager_b", "report_date"],
            },
        },
    },
]


def _read_report_date(manager_dir: Path) -> str:
    for name in ("pipeline_data.json", "manager_fund_pool_data.json", "industry_analysis_data.json"):
        path = manager_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary = data.get("summary") if isinstance(data, dict) else None
        if isinstance(summary, dict) and summary.get("report_date"):
            return str(summary["report_date"])
    return ""


def _compact_overview(evidence: dict[str, Any]) -> dict[str, Any]:
    run = evidence.get("run_summary") or {}
    resource = evidence.get("resource_demands") or {}
    match_summary = resource.get("match_summary") or {}
    return {
        "manager": evidence.get("manager"),
        "company": evidence.get("company"),
        "report_date": evidence.get("report_date"),
        "run_summary": {
            key: run.get(key)
            for key in ("successful_funds", "formal_funds", "formal_holding_rows", "error_count", "warning_count")
        },
        "top_holdings": evidence.get("holdings", [])[:10],
        "industry_exposure": evidence.get("industry_exposure", [])[:8],
        "resource_demands": {
            "industry": resource.get("industry", []),
            "company": resource.get("company", [])[:10],
            "match_summary": {
                key: match_summary.get(key)
                for key in (
                    "match_count",
                    "pending_count",
                    "personnel_count",
                    "candidate_match_count",
                    "confirmed_candidate_match_count",
                )
            },
        },
        "quarter_change": evidence.get("quarter_change"),
        "issues": evidence.get("issues", [])[:10],
        "aggregation_note": evidence.get("aggregation_note"),
    }


def _manager_evidence(manager: str, report_date: str, portfolio_root: Path, roster_path: Path) -> dict[str, Any]:
    manager_dir, company_dir, _ = locate_manager_quarter_dir(portfolio_root, roster_path, manager, report_date)
    evidence = build_evidence_pack(manager_dir, manager, company_dir)
    if not evidence.get("run_summary"):
        raise ValueError(f"{manager} {report_date} 缺少有效持仓摘要")
    return evidence


def _tool_list_managers(roster_path: Path) -> dict[str, Any]:
    entries = read_manager_roster(roster_path)
    grouped: dict[str, list[str]] = {}
    for entry in entries:
        grouped.setdefault(entry.company, []).append(entry.manager)
    return {
        "ok": True,
        "data": {
            "companies": [
                {"company": company, "managers": sorted(managers)} for company, managers in sorted(grouped.items())
            ]
        },
    }


def _tool_list_quarters(manager: str, portfolio_root: Path, roster_path: Path) -> dict[str, Any]:
    entries = read_manager_roster(roster_path)
    match = next((entry for entry in entries if entry.manager == manager.strip()), None)
    if match is None:
        return {"ok": False, "error": f"名单中未找到经理：{manager}"}
    base = portfolio_root / company_directory_name(match.company)
    quarters: list[dict[str, str]] = []
    for path in sorted(base.glob(f"{manager}_*")):
        if path.is_dir():
            quarters.append({"quarter": path.name[len(manager) + 1 :], "report_date": _read_report_date(path)})
    return {"ok": True, "data": {"manager": manager, "quarters": quarters}}


def _tool_manager_overview(manager: str, report_date: str, portfolio_root: Path, roster_path: Path) -> dict[str, Any]:
    evidence = _manager_evidence(manager, report_date, portfolio_root, roster_path)
    return {"ok": True, "data": _compact_overview(evidence)}


def _tool_compare_managers(
    manager_a: str,
    manager_b: str,
    report_date: str,
    portfolio_root: Path,
    roster_path: Path,
) -> dict[str, Any]:
    evidence_a = _manager_evidence(manager_a, report_date, portfolio_root, roster_path)
    evidence_b = _manager_evidence(manager_b, report_date, portfolio_root, roster_path)
    market_a = {row["sw_level1"]: row["market_value_10k"] for row in evidence_a.get("industry_exposure", [])}
    market_b = {row["sw_level1"]: row["market_value_10k"] for row in evidence_b.get("industry_exposure", [])}
    industries = sorted(set(market_a) | set(market_b), key=lambda k: -(market_a.get(k, 0.0) + market_b.get(k, 0.0)))
    return {
        "ok": True,
        "data": {
            "manager_a": manager_a,
            "manager_b": manager_b,
            "report_date": report_date,
            "industry_diff": [
                {
                    "sw_level1": sw,
                    f"{manager_a}_market_value_10k": market_a.get(sw, 0.0),
                    f"{manager_b}_market_value_10k": market_b.get(sw, 0.0),
                }
                for sw in industries
            ],
            "top_holdings_a": evidence_a.get("holdings", [])[:10],
            "top_holdings_b": evidence_b.get("holdings", [])[:10],
        },
    }


def _execute_tool(name: str, args: dict[str, Any], portfolio_root: Path, roster_path: Path) -> dict[str, Any]:
    try:
        if name == "list_managers":
            return _tool_list_managers(roster_path)
        if name == "list_quarters":
            return _tool_list_quarters(str(args["manager"]), portfolio_root, roster_path)
        if name == "manager_overview":
            return _tool_manager_overview(str(args["manager"]), str(args["report_date"]), portfolio_root, roster_path)
        if name == "compare_managers":
            return _tool_compare_managers(
                str(args["manager_a"]),
                str(args["manager_b"]),
                str(args["report_date"]),
                portfolio_root,
                roster_path,
            )
        return {"ok": False, "error": f"未知工具：{name}"}
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_agent(
    question: str,
    *,
    portfolio_root: Path,
    roster_path: Path,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 60,
    max_steps: int = 6,
) -> dict[str, Any]:
    """运行多步工具编排循环；无 key 时返回 used_llm=False。"""
    _load_dotenv()
    client = DeepSeekClient(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
    if not client.available:
        return {"answer": None, "used_llm": False, "steps": [], "tool_calls": 0}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    steps: list[dict[str, Any]] = []
    for _ in range(max_steps):
        message = client.chat_message(messages, tools=TOOLS)
        messages.append(message)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return {
                "answer": str(message.get("content") or ""),
                "used_llm": True,
                "steps": steps,
                "tool_calls": len(steps),
            }
        for call in tool_calls:
            function = call.get("function") or {}
            name = str(function.get("name", ""))
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            result = _execute_tool(name, args, portfolio_root, roster_path)
            steps.append({"tool": name, "args": args, "ok": bool(result.get("ok"))})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id", "")),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
    return {
        "answer": "（达到最大工具调用步数仍未收敛，请换一种问法，或更具体地指定经理与报告期）",
        "used_llm": True,
        "steps": steps,
        "tool_calls": len(steps),
        "stopped": True,
    }
