from __future__ import annotations

import unittest

from fund_holdings_agent.dedup import base_name, mark_duplicate_shares
from fund_holdings_agent.eastmoney import parse_holdings
from fund_holdings_agent.models import FetchResult, Fund, Holding
from fund_holdings_agent.pipeline import _same_managers, validate_report_date


class PipelineTests(unittest.TestCase):
    def test_target_manager_can_be_one_of_multiple_co_managers(self):
        self.assertTrue(_same_managers("目标经理", "目标经理,共同经理"))
        self.assertTrue(_same_managers("目标经理、共同经理", "共同经理,目标经理"))
        self.assertFalse(_same_managers("另一经理", "目标经理,共同经理"))

    def test_report_date_must_be_quarter_end(self):
        self.assertEqual(validate_report_date("2026-03-31").isoformat(), "2026-03-31")
        with self.assertRaises(ValueError):
            validate_report_date("2026-04-01")

    def test_base_name(self):
        self.assertEqual(base_name("大成专精特新混合A"), "大成专精特新混合")
        self.assertEqual(base_name("大成专精特新混合C"), "大成专精特新混合")

    def test_holdings_parser(self):
        table = '<table class="tzxq"><thead><tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>相关资讯</th><th>占净值比例</th><th>持股数（万股）</th><th>持仓市值（万元）</th></tr></thead><tbody><tr><td>1</td><td><a href="//quote.eastmoney.com/unify/r/1.600000">600000</a></td><td>浦发银行</td><td></td><td>5.25%</td><td>12.30</td><td>99.80</td></tr></tbody></table>'
        content = '<div class="boxitem"><h4>截止至：2026-03-31</h4>' + table + '</div>'
        payload = 'var apidata={ content:"' + content.replace('"', r'\"') + '",arryear:[2026]};'
        rows, issue = parse_holdings(payload, "2026-03-31", "https://example.test")
        self.assertEqual(issue, "")
        self.assertEqual(rows[0]["stock_code"], "600000.SH")
        self.assertEqual(rows[0]["nav_ratio"], 0.0525)

    def test_holdings_parser_never_falls_back_to_another_quarter(self):
        def section(date: str, code: str) -> str:
            return (
                f'<div class="boxitem"><h4>截止至：{date}</h4><table class="tzxq"><thead><tr>'
                '<th>序号</th><th>股票代码</th><th>股票名称</th><th>相关资讯</th><th>占净值比例</th>'
                '<th>持股数（万股）</th><th>持仓市值（万元）</th></tr></thead><tbody><tr><td>1</td>'
                f'<td><a href="//quote.eastmoney.com/unify/r/1.{code}">{code}</a></td><td>测试</td><td></td>'
                '<td>5%</td><td>1</td><td>10</td></tr></tbody></table></div>'
            )
        content = section("2026-06-30", "600001") + section("2026-03-31", "600000")
        payload = 'var apidata={ content:"' + content.replace('"', r'\"') + '",arryear:[2026]};'

        rows, issue = parse_holdings(payload, "2026-03-31", "https://example.test")
        missing, missing_issue = parse_holdings(payload, "2025-12-31", "https://example.test")

        self.assertEqual(issue, "")
        self.assertEqual(rows[0]["stock_code"], "600000.SH")
        self.assertEqual(missing, [])
        self.assertIn("未找到报告期 2025-12-31", missing_issue)

    def test_beijing_exchange_suffix(self):
        from fund_holdings_agent.eastmoney import infer_stock_code
        self.assertEqual(infer_stock_code("920522", "//quote.eastmoney.com/unify/r/0.920522"), ("920522.BJ", "A股"))
        self.assertEqual(infer_stock_code("NVDA", "//quote.eastmoney.com/unify/r/116.NVDA"), ("NVDA.US", "美股/海外"))
        self.assertEqual(infer_stock_code("00700", "//quote.eastmoney.com/unify/r/116.00700"), ("00700.HK", "港股"))

    def test_duplicate_prefers_a_share(self):
        def result(code: str, name: str) -> FetchResult:
            fund = Fund("经理", code, name)
            holding = Holding(code, name, "经理", "2026-03-31", 1, "600000.SH", "浦发银行", 1, 2, 0.1, "A股", "url")
            return FetchResult(fund, [holding], [], "已抓取")
        a = result("014651", "大成专精特新混合A")
        c = result("014652", "大成专精特新混合C")
        representatives = mark_duplicate_shares([c, a])
        self.assertEqual(representatives["014652"], "014651")
        self.assertEqual(a.holdings[0].representative, "是")
        self.assertEqual(c.holdings[0].representative, "否")


if __name__ == "__main__":
    unittest.main()
