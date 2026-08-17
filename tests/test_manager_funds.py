import json
import tempfile
from pathlib import Path

from fund_holdings_agent.io import read_funds_json
from fund_holdings_agent.manager_funds import (
    disclosure_exemption_reason,
    get_manager_funds,
    parse_fund_info,
    parse_manager_profile,
    parse_manager_suggestions,
    product_exclusion_reason,
)


def test_parse_manager_suggestions():
    parsed = parse_manager_suggestions('(["于威业,YWY,30814729","于某,YM,123"]);')
    assert [(row.name, row.manager_id) for row in parsed] == [("于威业", "30814729"), ("于某", "123")]


PROFILE = """
<html><h3 id="name_1">于威业</h3><a href="/Company/80000225.html">大成基金</a>
<table><tr><th>基金代码</th><th>基金名称</th><th>相关链接</th><th>基金类型</th><th>规模</th><th>任职时间</th></tr>
<tr><td>008275</td><td>大成行业先锋混合C</td><td></td><td>混合型-偏股</td><td>1.0</td><td>2024-12-27 ~ 至今</td></tr>
<tr><td>012473</td><td>大成成长回报六个月持有混合A</td><td></td><td>混合型-偏股</td><td>2.0</td><td>2024-01-03 ~ 2025-11-03</td></tr>
</table></html>
"""


def test_parse_manager_profile_history():
    name, company, rows = parse_manager_profile(PROFILE, "30814729")
    assert name == "于威业"
    assert company == "大成基金"
    assert rows[0].tenure_end == ""
    assert rows[1].tenure_end == "2025-11-03"


def test_parse_fund_info():
    info = parse_fund_info("<html><h4 class='title'>测试基金(012473)</h4><body>成立日期：2021-06-17 基金类型：混合型-偏股 基金管理人：大成基金</body></html>")
    assert info["fund_name"] == "测试基金"
    assert info["inception_date"] == "2021-06-17"
    assert info["company"] == "大成基金"


def test_get_manager_funds_uses_historical_point_in_time():
    suggestion_url = "FundDataPortfolio_Interface"
    profile_url = "/manager/30814729.html"
    manager_history = """
    <table><tr><th>起始期</th><th>截止期</th><th>基金经理</th></tr>
    <tr><td>2024-01-03</td><td>2025-11-03</td><td>于威业</td></tr></table>
    """

    def fake_fetch(url: str) -> str:
        if suggestion_url in url:
            return '(["于威业,YWY,30814729"])'
        if profile_url in url:
            return PROFILE
        if "jbgk_" in url:
            return "<html>成立日期：2020-01-01</html>"
        if "jjjl_" in url:
            return manager_history
        raise AssertionError(url)

    result = get_manager_funds("于威业", "2025-03-31", fake_fetch)
    assert result["summary"]["selected_share_count"] == 2
    assert result["summary"]["product_count"] == 2
    assert all(row["manager_verification"] == "通过" for row in result["selected_funds"])


def test_get_manager_funds_excludes_after_tenure():
    def fake_fetch(url: str) -> str:
        if "FundDataPortfolio_Interface" in url:
            return '(["于威业,YWY,30814729"])'
        if "/manager/30814729.html" in url:
            return PROFILE
        if "jbgk_" in url:
            return "<html>成立日期：2020-01-01</html>"
        if "jjjl_" in url:
            return "<table><tr><th>起始期</th><th>截止期</th><th>基金经理</th></tr><tr><td>2024-12-27</td><td>至今</td><td>于威业</td></tr></table>"
        raise AssertionError(url)

    result = get_manager_funds("于威业", "2026-03-31", fake_fetch)
    assert [row["fund_code"] for row in result["selected_funds"]] == ["008275"]
    excluded = next(row for row in result["all_tenures"] if row["fund_code"] == "012473")
    assert excluded["selection_reason"] == "报告期不在经理任职区间"


def test_read_fund_pool_json_preserves_six_digit_code():
    payload = {
        "selected_funds": [{
            "manager": "于威业",
            "fund_code": "008274",
            "fund_name": "大成行业先锋混合A",
            "fund_type": "混合型-偏股",
            "inception_date": "2020-03-23",
        }]
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "pool.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        funds, issues = read_funds_json(path, "2026-03-31")
    assert not issues
    assert funds[0].fund_code == "008274"


def test_product_scope_excludes_fof_pure_bond_and_fixed_income_index():
    assert product_exclusion_reason("FOF-均衡型")
    assert product_exclusion_reason("债券型-长债")
    assert product_exclusion_reason("债券型-混合一级")
    assert product_exclusion_reason("指数型-固收")
    assert not product_exclusion_reason("债券型-混合二级")
    assert not product_exclusion_reason("混合型-偏股")


def test_new_fund_under_two_calendar_months_is_disclosure_exempt():
    assert disclosure_exemption_reason("2026-06-02", "2026-06-30")
    assert disclosure_exemption_reason("2026-05-01", "2026-06-30")
    assert not disclosure_exemption_reason("2026-04-30", "2026-06-30")
