from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Callable

from .dedup import base_name, mark_duplicate_shares
from .eastmoney import HOLDINGS_URL, MANAGER_URL, fetch_url, parse_holdings, parse_manager_at_date
from .io import read_funds_input
from .models import FetchResult, Holding, Issue


def validate_report_date(value: str) -> dt.date:
    date = dt.date.fromisoformat(value)
    if (date.month, date.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        raise ValueError("report-date 必须是自然季度末")
    return date


def _same_managers(left: str, right: str) -> bool:
    normalize = lambda text: {part for part in text.replace("，", ",").replace("、", ",").split(",") if part}
    expected = normalize(left)
    actual = normalize(right)
    return bool(expected) and expected.issubset(actual)


def run_pipeline(
    input_path: Path,
    report_date: str,
    retries: int,
    timeout: int,
    sleep_seconds: float,
    fetcher: Callable[..., str] | None = None,
) -> dict:
    date = validate_report_date(report_date)
    funds, issues = read_funds_input(input_path, report_date)
    input_summary: dict = {}
    if input_path.suffix.lower() == ".json":
        input_summary = json.loads(input_path.read_text(encoding="utf-8")).get("summary", {})
    request = fetcher or (lambda url, referer="": fetch_url(url, retries, timeout, sleep_seconds, referer))
    results: list[FetchResult] = []
    for position, fund in enumerate(funds, start=1):
        if not fund.selected:
            results.append(FetchResult(fund=fund, issues=[] , status="已排除"))
            continue
        logging.info("处理基金 %s/%s %s %s", position, len(funds), fund.fund_code, fund.fund_name)
        result = FetchResult(fund=fund)
        manager_url = MANAGER_URL.format(code=fund.fund_code)
        fund.manager_source_url = manager_url
        try:
            manager_html = request(manager_url)
            verified_manager, records = parse_manager_at_date(manager_html, report_date)
            fund.verified_manager = verified_manager
            if verified_manager and _same_managers(fund.manager, verified_manager):
                fund.manager_status = "一致"
            elif verified_manager:
                fund.manager_status = "不一致"
                result.issues.append(Issue("警告", "基金经理不一致", fund.fund_code, fund.fund_name, fund.manager, report_date, f"名单={fund.manager}；F10={verified_manager}", manager_url, "人工复核经理任职记录"))
            else:
                fund.manager_status = "无法核实"
                result.issues.append(Issue("警告", "基金经理无法核实", fund.fund_code, fund.fund_name, fund.manager, report_date, "未找到覆盖报告期的任职记录", manager_url, "查阅基金季报原文"))
        except Exception as exc:
            fund.manager_status = "请求失败"
            result.issues.append(Issue("警告", "经理页面请求失败", fund.fund_code, fund.fund_name, fund.manager, report_date, str(exc), manager_url, "稍后重试"))

        holdings_url = HOLDINGS_URL.format(code=fund.fund_code, year=date.year, month=date.month)
        try:
            payload = request(holdings_url, referer=f"https://fundf10.eastmoney.com/ccmx_{fund.fund_code}.html")
            rows, parse_issue = parse_holdings(payload, report_date, holdings_url)
            for row in rows:
                result.holdings.append(Holding(fund.fund_code, fund.fund_name, fund.verified_manager or fund.manager, report_date, **row))
            if not rows:
                result.status = "无持仓/待核实"
                result.issues.append(Issue("警告", "持仓为空", fund.fund_code, fund.fund_name, fund.manager, report_date, parse_issue, holdings_url, "确认是否为不适用产品；必要时查季报 PDF"))
            else:
                result.status = "已抓取"
                if len(rows) < 10:
                    result.issues.append(Issue("提示", "披露少于10条", fund.fund_code, fund.fund_name, fund.manager, report_date, f"接口返回 {len(rows)} 条，按实际披露保留", holdings_url, "无需自动补足"))
                for row in result.holdings:
                    missing = [name for name, value in (("股票代码", row.stock_code), ("股票名称", row.stock_name), ("占净值比例", row.nav_ratio)) if value in (None, "")]
                    if missing:
                        result.issues.append(Issue("警告", "字段缺失", fund.fund_code, fund.fund_name, fund.manager, report_date, f"第 {row.rank} 行缺少 {','.join(missing)}", holdings_url, "人工核查原始页面"))
        except Exception as exc:
            result.status = "请求失败"
            result.issues.append(Issue("错误", "持仓请求失败", fund.fund_code, fund.fund_name, fund.manager, report_date, str(exc), holdings_url, "稍后重试"))
        issues.extend(result.issues)
        results.append(result)

    product_members: dict[str, list[FetchResult]] = {}
    for result in results:
        if result.fund.selected and result.holdings:
            product_members.setdefault(base_name(result.fund.fund_name), []).append(result)
    for product_name, members in product_members.items():
        if len(members) < 2:
            continue
        signatures = {tuple(row.stock_code for row in sorted(member.holdings, key=lambda item: item.rank)) for member in members}
        if len(signatures) > 1:
            codes = "、".join(member.fund.fund_code for member in members)
            issues.append(Issue("警告", "份额持仓不一致", codes, product_name, members[0].fund.manager, report_date, "同一基础产品的不同份额前十大股票代码序列不一致", action="保留各份额并人工核对，不自动合并"))

    representative_by_code = mark_duplicate_shares(results)
    for result in results:
        representative = representative_by_code.get(result.fund.fund_code)
        if representative and representative != result.fund.fund_code:
            issues.append(Issue("提示", "非代表份额", result.fund.fund_code, result.fund.fund_name, result.fund.manager, report_date, f"正式版保留 {representative}", action="全量底稿保留，本基金不重复计入正式版"))

    all_holdings = [holding.to_dict() for result in results for holding in result.holdings]
    formal_holdings = [row for row in all_holdings if row["representative"] == "是"]
    selected_funds = [fund for fund in funds if fund.selected]
    successful_funds = [result for result in results if result.holdings]
    summary = {
        "manager": input_summary.get("manager") or "、".join(sorted({fund.manager for fund in funds if fund.manager})),
        "company": input_summary.get("company", ""),
        "report_date": report_date,
        "input_funds": len(funds),
        "selected_funds": len(selected_funds),
        "successful_funds": len(successful_funds),
        "formal_funds": len({row["fund_code"] for row in formal_holdings}),
        "raw_holding_rows": len(all_holdings),
        "formal_holding_rows": len(formal_holdings),
        "issue_count": len(issues),
        "error_count": sum(issue.severity == "错误" for issue in issues),
        "warning_count": sum(issue.severity == "警告" for issue in issues),
        "success_rate": len(successful_funds) / len(selected_funds) if selected_funds else 0,
        "duplicate_product_count": len({row["duplicate_group"] for row in all_holdings if row["duplicate_group"]}),
    }
    return {
        "summary": summary,
        "funds": [fund.to_dict() | {"fetch_status": next((result.status for result in results if result.fund is fund), "")} for fund in funds],
        "all_holdings": all_holdings,
        "formal_holdings": formal_holdings,
        "issues": [issue.to_dict() for issue in issues],
        "sources": [
            {"item": "季度前十大持仓", "url": "https://fundf10.eastmoney.com/FundArchivesDatas.aspx", "note": "参数 type=jjcc、topline=10、year、month"},
            {"item": "报告期基金经理", "url": "https://fundf10.eastmoney.com/jjjl_{基金代码}.html", "note": "按任职起止日期覆盖报告期末判定"},
            {"item": "基金池输入", "url": str(input_path), "note": "由基金经理历史任职区间生成的报告期基金池" if input_path.suffix.lower() == ".json" else "用户提供的 CSV 基金名单"},
        ],
    }


def save_json_outputs(data: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "pipeline_data.json"
    summary_path = output_dir / "run_summary.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(data["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    return data_path, summary_path
