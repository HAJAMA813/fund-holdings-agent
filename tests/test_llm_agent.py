import json
import os
from pathlib import Path

import pytest

from fund_holdings_agent import llm_agent
from fund_holdings_agent.llm_agent import (
    DeepSeekClient,
    answer_question,
    build_evidence_pack,
    build_grounded_messages,
    deterministic_summary,
    locate_manager_quarter_dir,
)


def _write_quarter(dir_path: Path) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "pipeline_data.json").write_text(
        json.dumps(
            {
                "summary": {
                    "manager": "徐小勇",
                    "company": "长安基金管理有限公司",
                    "report_date": "2026-06-30",
                    "successful_funds": 2,
                    "formal_funds": 2,
                    "formal_holding_rows": 20,
                    "error_count": 0,
                    "warning_count": 1,
                },
                "formal_holdings": [
                    {"rank": 1, "stock_code": "300502.SZ", "stock_name": "新易盛", "market": "A股", "fund_name": "长安先进制造混合A", "market_value_10k": "9341.19", "nav_ratio": "0.385"},
                    {"rank": 2, "stock_code": "002371.SZ", "stock_name": "北方华创", "market": "A股", "fund_name": "长安先进制造混合A", "market_value_10k": "8000.0", "nav_ratio": "0.33"},
                ],
                "issues": [{"severity": "警告", "category": "持仓条数", "fund_code": "013513", "message": "少于10条", "action": "人工复核"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (dir_path / "industry_analysis_data.json").write_text(
        json.dumps(
            {
                "industry_summary": [
                    {"sw_level1": "电子", "holding_count": 6, "market_value_10k": "9341.19", "nav_ratio": "0.385"},
                    {"sw_level1": "机械设备", "holding_count": 4, "market_value_10k": "4000.0", "nav_ratio": "0.16"},
                ],
                "industry_issues": [{"severity": "警告", "message": "行业为当前快照", "action": "记录"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (dir_path / "resource_matching_data.json").write_text(
        json.dumps(
            {
                "summary": {"match_count": 63, "pending_count": 0, "personnel_count": 114},
                "industry_demands": [{"sw_level1": "电子", "priority": "P1", "fund_count": 2, "holding_count": 6, "market_value_10k": 9341.19}],
                "company_demands": [{"stock_code": "300502.SZ", "stock_name": "新易盛", "sw_level1": "电子", "priority": "P1", "holding_occurrences": 2, "market_value_10k": 9341.19, "max_nav_ratio": 0.385}],
                "matches": [{"demand_type": "行业", "target_name": "电子", "person_name": "甲", "organization": "示例券商研究所", "match_type": "行业覆盖", "score": 50, "confirmation_status": "已确认"}],
                "pending_items": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (dir_path / "quarter_comparison_data.json").write_text(
        json.dumps(
            {
                "summary": {"new_company_count": 3, "exited_company_count": 2, "increased_company_count": 1, "decreased_company_count": 1, "unchanged_company_count": 5},
                "company_changes": [{"change_type": "新进", "stock_code": "300502.SZ", "stock_name": "新易盛", "market_value_change_10k": 9341.19}],
                "industry_changes": [{"change_type": "增持", "sw_level1": "电子", "nav_ratio_change": 0.05}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_build_evidence_pack_extracts_all_sections(tmp_path: Path):
    _write_quarter(tmp_path)
    evidence = build_evidence_pack(tmp_path, "徐小勇", "长安基金管理有限公司")

    assert evidence["holdings"][0]["stock_name"] == "新易盛"
    assert evidence["industry_exposure"][0]["sw_level1"] == "电子"
    assert evidence["resource_demands"]["company"][0]["stock_code"] == "300502.SZ"
    assert evidence["resource_demands"]["match_summary"]["match_count"] == 63
    assert evidence["quarter_change"]["summary"]["new_company_count"] == 3
    assert any(row["category"] == "持仓条数" for row in evidence["issues"])
    assert len(evidence["sources"]) == 4


def test_deterministic_summary_references_only_real_data(tmp_path: Path):
    _write_quarter(tmp_path)
    evidence = build_evidence_pack(tmp_path, "徐小勇", "长安基金管理有限公司")
    text = deterministic_summary(evidence)

    assert "新易盛" in text
    assert "确定性模板" in text
    assert "未调用大模型" in text


def test_answer_question_falls_back_without_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(llm_agent, "_load_dotenv", lambda *a, **k: None)
    portfolio = tmp_path / "portfolio"
    _write_quarter(portfolio / "长安基金" / "徐小勇_2026Q2")
    roster = tmp_path / "roster.csv"
    roster.write_text(
        "company,manager,manager_id,active\n长安基金管理有限公司,徐小勇,30046790,yes\n",
        encoding="utf-8",
    )

    result = answer_question(
        manager="徐小勇",
        report_date="2026-06-30",
        question="本季度持仓如何",
        portfolio_root=portfolio,
        roster_path=roster,
    )

    assert result["mode"] == "deterministic"
    assert result["deepseek_used"] is False
    assert "新易盛" in result["answer"]
    assert result["sources"]


def test_locate_manager_quarter_dir_rejects_unknown_manager(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    roster.write_text("company,manager,manager_id,active\n长安基金管理有限公司,徐小勇,30046790,yes\n", encoding="utf-8")
    with pytest.raises(ValueError):
        locate_manager_quarter_dir(tmp_path / "portfolio", roster, "不存在的人", "2026-06-30")


def test_grounded_messages_contain_guardrail_and_evidence(tmp_path: Path):
    _write_quarter(tmp_path)
    evidence = build_evidence_pack(tmp_path, "徐小勇", "长安基金管理有限公司")
    messages = build_grounded_messages("问题", evidence)

    assert messages[0]["role"] == "system"
    assert "不得" in messages[0]["content"]
    assert "算术汇总" in messages[0]["content"] or "加权仓位" in messages[0]["content"]
    assert "新易盛" in messages[1]["content"]
    assert "问题" in messages[1]["content"]


def test_deepseek_client_payload_and_response(monkeypatch):
    captured: dict = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "你好"}}]}).encode("utf-8")

    def _fake_urlopen(request, timeout=None):
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr(llm_agent.urllib.request, "urlopen", _fake_urlopen)
    client = DeepSeekClient(api_key="test-key", base_url="https://example.invalid", model="deepseek-chat")
    assert client.available is True

    assert client.chat([{"role": "user", "content": "hi"}]) == "你好"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["temperature"] == 0.0


def test_deepseek_client_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = DeepSeekClient(api_key=None)
    assert client.available is False
    with pytest.raises(RuntimeError):
        client.chat([{"role": "user", "content": "hi"}])


def test_pipeline_modules_do_not_import_llm_agent():
    # 确定性数据管道（抓取/去重/行业/资源/比较/报表）不得依赖 LLM。
    # mac_cli.py / agent.py 是「Agent 编排/解读层」（需求文档 §18.2），允许 import LLM。
    shell_modules = {"mac_cli.py", "agent.py", "agent_cli.py", "llm_agent.py", "llm_agent_cli.py"}
    package_root = Path("src") / "fund_holdings_agent"
    offenders = []
    for path in sorted(package_root.glob("*.py")):
        if path.name in shell_modules or path.name.startswith("llm_agent") or path.name.startswith("agent"):
            continue
        text = path.read_text(encoding="utf-8")
        if "llm_agent" in text and ("import llm_agent" in text or "from .llm_agent" in text or "fund_holdings_agent.llm_agent" in text):
            offenders.append(str(path))
    assert offenders == [], f"确定性管道不应依赖 LLM 模块：{offenders}"


def test_load_dotenv_sets_only_missing_vars(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "existing-model")
    env_file = tmp_path / ".env"
    env_file.write_text(
        'DEEPSEEK_API_KEY="sk-abc"\nDEEPSEEK_MODEL=deepseek-chat\n# 注释\nDEEPSEEK_BASE_URL=https://api.deepseek.com\n',
        encoding="utf-8",
    )
    llm_agent._load_dotenv(env_file)

    assert os.environ["DEEPSEEK_API_KEY"] == "sk-abc"
    assert os.environ["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com"
    assert os.environ["DEEPSEEK_MODEL"] == "existing-model"


def test_llm_available_reads_env(monkeypatch):
    monkeypatch.setattr(llm_agent, "_load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abc")
    assert llm_agent.llm_available() is True
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert llm_agent.llm_available() is False


def test_ask_grounded_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(llm_agent, "_load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    answer, used = llm_agent.ask_grounded("问题", {"a": 1})
    assert answer is None
    assert used is False
