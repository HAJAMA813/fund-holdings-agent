"""自然语言问答层（只读、可选、不参与确定性数据管道）。

本模块把 LLM 严格限制在「解释与摘要」：
- 只读取已由确定性管道生成的 JSON 产物，绝不写入、修改任何业务数据；
- 模型文本必须引用证据来源，不得编造基金、持仓、行业、人员或数值；
- 没有 DeepSeek API Key 时回退到确定性模板摘要，功能仍可用。

确定性管道（基金池、持仓抓取、去重、行业映射、资源匹配、季度比较、Excel/PDF）
不 import 本模块；本模块是独立的旁路助手。验收/健康检查的「模型边界」检查会把
本模块从「确定性管道未接入 DeepSeek」的扫描中豁免，同时由测试保证管道不依赖本模块。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .portfolio import company_directory_name, read_manager_roster
from .quarterly_cli import beijing_now, latest_closed_quarter, quarter_label

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_GUARDRAIL = (
    "你是一名基金持仓分析助手，只能依据下面提供的「已校验 JSON 证据」回答。"
    "硬性规则：1) 每个关键结论都要引用证据来源（文件名或字段）；"
    "2) 证据中没有的信息，直接回答「数据中未提供」，不得猜测；"
    "3) 不得修改持仓事实、行业映射、异常状态或任何计算结果；"
    "4) 你的回答是基于已验证 JSON 的摘要，不是实时行情，也不构成投资建议；"
    "5) 港股/海外股票按原始标记处理，不得强行归入申万行业；"
    "6) 涉及人员时只引用证据中明确给出的姓名和机构，不得虚构；"
    "7) 凡涉及跨产品的市值合计或净值比例合计，必须明确标注证据中的 aggregation_note"
    "（即：算术汇总，不代表统一组合加权仓位），不得把合计值表述成统一组合的仓位或比例。"
)

AGGREGATION_NOTE = "跨产品市值与净值比例为各基础产品披露值的算术汇总，不代表统一组合加权仓位。"


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _num(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_dotenv(path: Path | None = None) -> None:
    """加载 .env（KEY=VALUE 每行一条），不覆盖已存在的环境变量。"""
    target = path or Path(".env")
    if not target.exists():
        return
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and os.environ.get(key) is None:
            os.environ[key] = value


def _cap(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return rows[:limit]


def _record_source(sources: list[dict[str, str]], path: Path, label: str) -> None:
    sources.append({"label": label, "path": str(path), "sha256": _sha256(path)})


def locate_manager_quarter_dir(
    portfolio_root: Path,
    roster_path: Path,
    manager: str,
    report_date: str,
) -> tuple[Path, str, str]:
    """返回 (季度目录, 公司目录名, 季度标签)；找不到时抛出 ValueError。"""
    report = dt.date.fromisoformat(report_date)
    quarter = quarter_label(report)
    entries = read_manager_roster(roster_path)
    match = next((entry for entry in entries if entry.manager == manager.strip()), None)
    if match is None:
        raise ValueError(f"名单中未找到经理：{manager}")
    company_dir = company_directory_name(match.company)
    manager_dir = portfolio_root / company_dir / f"{manager}_{quarter}"
    if not manager_dir.exists():
        raise ValueError(f"缺少季度产物目录：{manager_dir}（请先运行季度任务）")
    return manager_dir, company_dir, quarter


def build_evidence_pack(manager_dir: Path, manager: str, company: str) -> dict[str, Any]:
    """从已验证 JSON 产物构建只读证据包，供 LLM 或确定性模板摘要使用。"""
    sources: list[dict[str, str]] = []
    pipeline = _read_json(manager_dir / "pipeline_data.json")
    industry = _read_json(manager_dir / "industry_analysis_data.json")
    resource = _read_json(manager_dir / "resource_matching_data.json")
    comparison = _read_json(manager_dir / "quarter_comparison_data.json")
    _record_source(sources, manager_dir / "pipeline_data.json", "持仓管道")
    _record_source(sources, manager_dir / "industry_analysis_data.json", "行业分析")
    _record_source(sources, manager_dir / "resource_matching_data.json", "研究资源匹配")
    _record_source(sources, manager_dir / "quarter_comparison_data.json", "季度比较")

    holdings = sorted(
        pipeline.get("formal_holdings", []),
        key=lambda row: (float(_num(row.get("rank"))) if row.get("rank") else 1e9, str(row.get("fund_code", ""))),
    )
    holdings_pack = [
        {
            "rank": row.get("rank"),
            "stock_code": row.get("stock_code"),
            "stock_name": row.get("stock_name"),
            "market": row.get("market"),
            "fund_name": row.get("fund_name"),
            "market_value_10k": _num(row.get("market_value_10k")),
            "nav_ratio": _num(row.get("nav_ratio")),
        }
        for row in _cap(holdings, 20)
    ]

    industry_agg: dict[str, dict[str, Any]] = {}
    for row in industry.get("industry_summary", []):
        key = str(row.get("sw_level1", "")).strip()
        if not key:
            continue
        target = industry_agg.setdefault(
            key,
            {"sw_level1": key, "holding_count": 0.0, "market_value_10k": 0.0, "nav_ratio_sum": 0.0},
        )
        target["holding_count"] += _num(row.get("holding_count"))
        target["market_value_10k"] += _num(row.get("market_value_10k"))
        target["nav_ratio_sum"] += _num(row.get("nav_ratio"))
    industry_exposure = sorted(
        industry_agg.values(), key=lambda row: row["market_value_10k"], reverse=True
    )

    company_demands = sorted(
        resource.get("company_demands", []),
        key=lambda row: _num(row.get("market_value_10k")),
        reverse=True,
    )
    matches = sorted(
        resource.get("matches", []),
        key=lambda row: (_num(row.get("score")), str(row.get("priority", ""))),
        reverse=True,
    )

    resource_summary = resource.get("summary", {})
    issues: list[dict[str, Any]] = []
    for row in pipeline.get("issues", []):
        issues.append(
            {
                "severity": row.get("severity"),
                "category": row.get("category"),
                "fund_code": row.get("fund_code"),
                "message": row.get("message"),
                "action": row.get("action"),
            }
        )
    for row in industry.get("industry_issues", []):
        issues.append(
            {
                "severity": row.get("severity"),
                "category": row.get("category", "行业"),
                "message": row.get("message"),
                "action": row.get("action"),
            }
        )

    change_pack: dict[str, Any] | None = None
    if comparison:
        change_pack = {
            "summary": {
                key: comparison.get("summary", {}).get(key)
                for key in (
                    "new_company_count",
                    "exited_company_count",
                    "increased_company_count",
                    "decreased_company_count",
                    "unchanged_company_count",
                    "new_industry_count",
                    "exited_industry_count",
                    "increased_industry_count",
                    "decreased_industry_count",
                )
            },
            "companies": [
                {
                    "change_type": row.get("change_type"),
                    "stock_code": row.get("stock_code"),
                    "stock_name": row.get("stock_name"),
                    "market_value_change_10k": _num(row.get("market_value_change_10k")),
                }
                for row in _cap(comparison.get("company_changes", []), 20)
            ],
            "industries": [
                {
                    "change_type": row.get("change_type"),
                    "sw_level1": row.get("sw_level1"),
                    "nav_ratio_change": _num(row.get("nav_ratio_change")),
                }
                for row in _cap(comparison.get("industry_changes", []), 20)
            ],
        }

    run_summary = pipeline.get("summary") or {}
    return {
        "manager": manager,
        "company": company,
        "report_date": str(run_summary.get("report_date", "")),
        "run_summary": run_summary,
        "holdings": holdings_pack,
        "industry_exposure": industry_exposure,
        "resource_demands": {
            "industry": _cap(resource.get("industry_demands", []), 20),
            "company": _cap(
                [
                    {
                        "stock_code": row.get("stock_code"),
                        "stock_name": row.get("stock_name"),
                        "sw_level1": row.get("sw_level1"),
                        "priority": row.get("priority"),
                        "holding_occurrences": row.get("holding_occurrences"),
                        "market_value_10k": _num(row.get("market_value_10k")),
                        "max_nav_ratio": _num(row.get("max_nav_ratio")),
                    }
                    for row in company_demands
                ],
                20,
            ),
            "match_summary": resource_summary,
            "top_matches": _cap(
                [
                    {
                        "demand_type": row.get("demand_type"),
                        "target_name": row.get("target_name"),
                        "person_name": row.get("person_name"),
                        "organization": row.get("organization"),
                        "match_type": row.get("match_type"),
                        "score": row.get("score"),
                        "confirmation_status": row.get("confirmation_status"),
                    }
                    for row in matches
                ],
                20,
            ),
            "pending_items": _cap(resource.get("pending_items", []), 20),
        },
        "quarter_change": change_pack,
        "issues": _cap(issues, 30),
        "aggregation_note": AGGREGATION_NOTE,
        "sources": sources,
    }


class DeepSeekClient:
    """基于 stdlib 的最小 DeepSeek 客户端（OpenAI 兼容 /chat/completions）。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict[str, str]]) -> str:
        message = self.chat_message(messages)
        return str(message.get("content") or "")

    def chat_message(self, messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """返回完整的 assistant 消息（content 与可选 tool_calls），支持 function calling。"""
        if not self.api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY；请设置环境变量后再调用大模型")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek 请求失败 HTTP {exc.code}：{detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek 请求失败：{exc.reason}") from exc
        try:
            return dict(body["choices"][0]["message"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"DeepSeek 响应结构异常：{json.dumps(body, ensure_ascii=False)[:300]}") from exc


def build_grounded_messages(question: str, evidence: dict[str, Any]) -> list[dict[str, str]]:
    evidence_text = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    return [
        {"role": "system", "content": SYSTEM_GUARDRAIL},
        {
            "role": "user",
            "content": (
                f"已校验 JSON 证据如下：\n```json\n{evidence_text}\n```\n\n"
                f"用户问题：{question}"
            ),
        },
    ]


def deterministic_summary(evidence: dict[str, Any]) -> str:
    """无 API Key 时的确定性模板摘要，仅引用证据包中的真实数值。"""
    run = evidence.get("run_summary") or {}
    manager = evidence.get("manager", "")
    report_date = evidence.get("report_date", "")
    lines: list[str] = [f"【{manager} {report_date} 持仓摘要】（确定性模板，未调用大模型）"]

    lines.append(
        f"抓取成功基金 {run.get('successful_funds', '-')} 只，正式去重后 {run.get('formal_funds', '-')} 只，"
        f"正式持仓 {run.get('formal_holding_rows', '-')} 条；错误 {run.get('error_count', '-')}，警告 {run.get('warning_count', '-')}。"
    )

    holdings = evidence.get("holdings") or []
    if holdings:
        top_holdings = sorted(holdings, key=lambda row: row.get("market_value_10k", 0.0), reverse=True)[:5]
        top = "、".join(
            f"{row['stock_name']}({row.get('fund_name', '')},{row.get('market_value_10k', 0.0):.0f}万)"
            for row in top_holdings
        )
        lines.append(f"前五大持仓（按市值）：{top}。")

    industries = evidence.get("industry_exposure") or []
    if industries:
        top = "、".join(f"{row['sw_level1']}" for row in industries[:3])
        lines.append(f"申万一级行业市值靠前：{top}。")

    resource = evidence.get("resource_demands") or {}
    match_summary = resource.get("match_summary") or {}
    lines.append(
        f"研究资源：行业需求 {len(resource.get('industry') or [])} 项、公司需求 {len(resource.get('company') or [])} 项、"
        f"匹配 {match_summary.get('match_count', '-')} 条、待补充 {len(resource.get('pending_items') or [])} 项。"
    )

    change = evidence.get("quarter_change")
    if change:
        summary = change.get("summary") or {}
        lines.append(
            f"季度变化：新进 {summary.get('new_company_count', '-')}、退出 {summary.get('exited_company_count', '-')}、"
            f"增持 {summary.get('increased_company_count', '-')}、减持 {summary.get('decreased_company_count', '-')}。"
        )

    issues = evidence.get("issues") or []
    lines.append(f"异常与警告 {len(issues)} 条。")
    lines.append(evidence.get("aggregation_note", AGGREGATION_NOTE))
    return "\n".join(lines)


def answer_question(
    *,
    manager: str,
    report_date: str,
    question: str,
    portfolio_root: Path,
    roster_path: Path,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """入口：定位季度产物 → 构建证据包 → LLM 或确定性模板回答。"""
    _load_dotenv()
    manager_dir, company_dir, quarter = locate_manager_quarter_dir(
        portfolio_root, roster_path, manager, report_date
    )
    evidence = build_evidence_pack(manager_dir, manager, company_dir)
    if not evidence.get("run_summary"):
        raise ValueError(f"季度产物缺少有效持仓摘要：{manager_dir}")

    client = DeepSeekClient(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
    if client.available:
        answer = client.chat(build_grounded_messages(question, evidence))
        mode = "llm"
    else:
        answer = deterministic_summary(evidence)
        mode = "deterministic"

    return {
        "manager": manager,
        "company_dir": company_dir,
        "quarter": quarter,
        "report_date": report_date,
        "question": question,
        "answer": answer,
        "mode": mode,
        "deepseek_used": mode == "llm",
        "model": client.model if mode == "llm" else None,
        "sources": evidence["sources"],
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
    }


def llm_available() -> bool:
    """是否已配置 DeepSeek API Key（读 .env 或环境变量）。"""
    _load_dotenv()
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def ask_grounded(
    question: str,
    evidence: dict[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: int = 60,
) -> tuple[str | None, bool]:
    """对任意已验证证据做接地气回答；无 key 时返回 (None, False)，由调用方跳过。"""
    _load_dotenv()
    client = DeepSeekClient(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
    if not client.available:
        return None, False
    answer = client.chat(build_grounded_messages(question, evidence))
    return answer, True
