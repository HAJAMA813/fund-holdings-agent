import json
from pathlib import Path

from fund_holdings_agent import agent
from fund_holdings_agent.agent import _execute_tool, run_agent


def _write_roster(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "company,manager,manager_id,active\n"
        "甲基金管理有限公司,甲经理,1,yes\n"
        "甲基金管理有限公司,乙经理,2,yes\n",
        encoding="utf-8",
    )


def _write_pipeline(portfolio_root: Path, company: str, manager: str, report_date: str) -> None:
    quarter = f"{report_date[:4]}Q{int(report_date[5:7]) // 3}"
    directory = portfolio_root / company / f"{manager}_{quarter}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pipeline_data.json").write_text(
        json.dumps(
            {
                "summary": {
                    "manager": manager,
                    "company": f"{company}管理有限公司",
                    "report_date": report_date,
                    "successful_funds": 2,
                    "formal_funds": 2,
                    "formal_holding_rows": 10,
                    "error_count": 0,
                    "warning_count": 0,
                },
                "formal_holdings": [
                    {"rank": 1, "stock_code": "300502.SZ", "stock_name": "新易盛", "market": "A股", "fund_name": "甲成长A", "market_value_10k": "1000", "nav_ratio": "0.1"},
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "industry_analysis_data.json").write_text(
        json.dumps(
            {
                "industry_summary": [{"sw_level1": "电子", "holding_count": 1, "market_value_10k": "1000", "nav_ratio": "0.1"}],
                "industry_issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "resource_matching_data.json").write_text(
        json.dumps({"summary": {"match_count": 0, "pending_count": 0}, "industry_demands": [], "company_demands": [], "matches": [], "pending_items": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_run_agent_not_ready_without_key(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(agent, "_load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(agent.DeepSeekClient, "available", property(lambda self: False))
    result = run_agent("问题", portfolio_root=tmp_path, roster_path=tmp_path / "roster.csv")
    assert result["used_llm"] is False
    assert result["answer"] is None


def test_tool_list_managers(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    _write_roster(roster)
    result = _execute_tool("list_managers", {}, tmp_path / "portfolio", roster)
    assert result["ok"] is True
    assert result["data"]["companies"][0]["company"] == "甲基金管理有限公司"
    assert set(result["data"]["companies"][0]["managers"]) == {"甲经理", "乙经理"}


def test_tool_list_quarters(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    _write_roster(roster)
    _write_pipeline(tmp_path / "portfolio", "甲基金", "甲经理", "2026-06-30")
    result = _execute_tool("list_quarters", {"manager": "甲经理"}, tmp_path / "portfolio", roster)
    assert result["ok"] is True
    assert result["data"]["quarters"][0]["quarter"] == "2026Q2"
    assert result["data"]["quarters"][0]["report_date"] == "2026-06-30"


def test_tool_manager_overview(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    _write_roster(roster)
    _write_pipeline(tmp_path / "portfolio", "甲基金", "甲经理", "2026-06-30")
    result = _execute_tool("manager_overview", {"manager": "甲经理", "report_date": "2026-06-30"}, tmp_path / "portfolio", roster)
    assert result["ok"] is True
    assert result["data"]["run_summary"]["formal_funds"] == 2
    assert result["data"]["top_holdings"][0]["stock_name"] == "新易盛"


def test_tool_compare_managers(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    _write_roster(roster)
    _write_pipeline(tmp_path / "portfolio", "甲基金", "甲经理", "2026-06-30")
    _write_pipeline(tmp_path / "portfolio", "甲基金", "乙经理", "2026-06-30")
    result = _execute_tool(
        "compare_managers",
        {"manager_a": "甲经理", "manager_b": "乙经理", "report_date": "2026-06-30"},
        tmp_path / "portfolio",
        roster,
    )
    assert result["ok"] is True
    assert result["data"]["manager_a"] == "甲经理"
    assert "industry_diff" in result["data"]


def test_tool_unknown_and_missing_manager(tmp_path: Path):
    roster = tmp_path / "roster.csv"
    _write_roster(roster)
    assert _execute_tool("nope", {}, tmp_path / "p", roster)["ok"] is False
    missing = _execute_tool("manager_overview", {"manager": "不存在", "report_date": "2026-06-30"}, tmp_path / "portfolio", roster)
    assert missing["ok"] is False


def test_run_agent_multi_step_loop_with_fake_client(tmp_path: Path, monkeypatch):
    roster = tmp_path / "roster.csv"
    _write_roster(roster)
    _write_pipeline(tmp_path / "portfolio", "甲基金", "甲经理", "2026-06-30")
    monkeypatch.setattr(agent, "_load_dotenv", lambda *a, **k: None)

    responses = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "list_managers", "arguments": "{}"}}]},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "2", "type": "function", "function": {"name": "manager_overview", "arguments": '{"manager":"甲经理","report_date":"2026-06-30"}'}}]},
        {"role": "assistant", "content": "最终回答：甲经理本季度重仓新易盛。", "tool_calls": []},
    ]

    class _FakeClient:
        available = True

        def __init__(self, *args, **kwargs):
            pass

        def chat_message(self, messages, tools=None):
            return responses.pop(0)

    monkeypatch.setattr(agent, "DeepSeekClient", _FakeClient)
    result = run_agent("甲经理重仓什么？", portfolio_root=tmp_path / "portfolio", roster_path=roster)

    assert result["used_llm"] is True
    assert result["tool_calls"] == 2
    assert [step["tool"] for step in result["steps"]] == ["list_managers", "manager_overview"]
    assert "新易盛" in result["answer"]
