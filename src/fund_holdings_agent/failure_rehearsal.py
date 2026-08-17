from __future__ import annotations

import copy
import hashlib
import json
import urllib.error
from pathlib import Path
from typing import Any

from . import eastmoney, industry, manager_funds
from .batch import BatchConfig, STAGES, run_batch
from .disclosure import assess_disclosure
from .eastmoney import fetch_url, parse_holdings
from .industry import IndustryFetcher
from .manager_funds import CachedFetcher
from .portfolio import atomic_write_json, atomic_write_text
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now


def run_failure_rehearsal(output_dir: Path, report_date: str = "2026-06-30") -> dict[str, Any]:
    output_dir = output_dir.resolve()
    checks: list[dict[str, Any]] = []

    def check(check_id: str, group: str, name: str, passed: bool, evidence: str, expected_action: str) -> None:
        checks.append(
            {
                "id": check_id,
                "group": group,
                "name": name,
                "status": "通过" if passed else "失败",
                "severity": "阻断",
                "evidence": evidence,
                "expected_action": expected_action,
            }
        )

    retry_result = _exercise_http_retry(permanent=False)
    check(
        "FR-01",
        "网络",
        "临时网络失败按配置重试后成功",
        retry_result["passed"],
        retry_result["evidence"],
        "无需人工处理；保留重试次数日志",
    )
    permanent_result = _exercise_http_retry(permanent=True)
    check(
        "FR-02",
        "网络",
        "持续网络失败在达到上限后明确失败",
        permanent_result["passed"],
        permanent_result["evidence"],
        "保留失败现场，下一窗口从失败阶段续跑",
    )

    resume_result = _exercise_batch_resume(output_dir / "technical_failure", report_date)
    check(
        "FR-03",
        "断点续跑",
        "持仓阶段技术失败后只重跑失败阶段及下游",
        resume_result["passed"],
        resume_result["evidence"],
        "重复执行原任务；不删除任务清单",
    )

    drift_result = _exercise_page_drift(report_date)
    check(
        "FR-04",
        "网页变化",
        "持仓字段变化不会被误判为成功",
        drift_result["passed"],
        drift_result["evidence"],
        "进入等待并检查原始页面、字段映射和解析器",
    )

    share_result = _exercise_share_fallback(report_date)
    check(
        "FR-05",
        "份额容错",
        "同一产品A份额有效时C份额空页不阻断",
        share_result["passed"],
        share_result["evidence"],
        "正式口径使用已披露代表份额；空页保留审计警告",
    )

    empty_result = _exercise_all_empty(report_date)
    check(
        "FR-06",
        "空持仓",
        "同一产品全部份额为空时阻断正式运行",
        empty_result["passed"],
        empty_result["evidence"],
        "保持waiting；确认披露或产品不适用后再处理",
    )

    raw_cache_result = _exercise_corrupt_raw_cache(output_dir / "corrupt_raw_cache")
    check(
        "FR-07",
        "缓存",
        "原始网页缓存损坏时旁路保存并原子刷新",
        raw_cache_result["passed"],
        raw_cache_result["evidence"],
        "保留.corrupt文件审计；使用新缓存继续",
    )

    industry_cache_result = _exercise_corrupt_industry_cache(output_dir / "corrupt_industry_cache")
    check(
        "FR-08",
        "缓存",
        "行业缓存损坏时旁路保存并原子刷新",
        industry_cache_result["passed"],
        industry_cache_result["evidence"],
        "保留.corrupt文件审计；使用新缓存继续",
    )

    stale_result = _exercise_stale_quarter(report_date)
    check(
        "FR-09",
        "报告期",
        "缓存只有上一季度时禁止跨季度回退",
        stale_result["passed"],
        stale_result["evidence"],
        "保持等待并刷新目标季度，不复用旧季度数据",
    )

    failed = [row for row in checks if row["status"] == "失败"]
    summary_path = output_dir / "failure_rehearsal_summary.json"
    playbook_path = output_dir / "故障处置手册.md"
    payload: dict[str, Any] = {
        "title": "基金持仓 Agent 离线故障注入与恢复演练",
        "report_date": report_date,
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "overall_status": "passed" if not failed else "needs_revision",
        "passed_check_count": sum(row["status"] == "通过" for row in checks),
        "failed_check_count": len(failed),
        "network_used": False,
        "deepseek_used": False,
        "checks": checks,
        "scenario_details": {
            "http_retry": retry_result,
            "permanent_http_failure": permanent_result,
            "batch_resume": resume_result,
            "page_drift": drift_result,
            "share_fallback": share_result,
            "all_empty": empty_result,
            "raw_cache_recovery": raw_cache_result,
            "industry_cache_recovery": industry_cache_result,
            "stale_quarter": stale_result,
        },
        "safety_boundaries": [
            "物理损坏缓存只移动到同目录.corrupt旁路文件，不删除，刷新写入使用临时文件原子替换。",
            "可读取但网页字段变化的缓存不自动删除；解析器产生明确异常，披露门禁阻止下游正式结果。",
            "A/C/E份额按基础产品设闸门；至少一个份额成功披露即可通过，全部为空才阻断。",
            "所有场景使用本地合成响应和注入异常，不访问公开网站，不调用DeepSeek。",
        ],
        "outputs": {"summary": str(summary_path), "playbook": str(playbook_path)},
    }
    atomic_write_text(playbook_path, _build_playbook(payload))
    atomic_write_json(summary_path, payload)
    return payload


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def _exercise_http_retry(permanent: bool) -> dict[str, Any]:
    attempts = 0
    original = eastmoney.urllib.request.urlopen
    original_sleep = eastmoney.time.sleep

    def fake_urlopen(_request, timeout=0):
        nonlocal attempts
        attempts += 1
        if permanent or attempts < 3:
            raise urllib.error.URLError("offline simulated timeout")
        return _Response(b"offline-success")

    eastmoney.urllib.request.urlopen = fake_urlopen
    eastmoney.time.sleep = lambda _seconds: None
    error = ""
    value = ""
    try:
        value = fetch_url("https://offline.invalid/test", retries=3, timeout=1, sleep_seconds=0)
    except RuntimeError as exc:
        error = str(exc)
    finally:
        eastmoney.urllib.request.urlopen = original
        eastmoney.time.sleep = original_sleep
    passed = attempts == 3 and ((permanent and "请求重试后仍失败" in error) or (not permanent and value == "offline-success" and not error))
    return {"passed": passed, "attempts": attempts, "result": value, "error": error, "evidence": f"尝试{attempts}次；" + (f"错误={error}" if error else f"结果={value}")}


def _exercise_batch_resume(run_dir: Path, report_date: str) -> dict[str, Any]:
    calls: list[str] = []
    holdings_attempts = 0
    config = BatchConfig(
        manager="故障演练经理",
        report_date=report_date,
        output_dir=run_dir,
        raw_cache_dir=run_dir / "raw",
        industry_cache_dir=run_dir / "industry",
        personnel_path=run_dir / "unused.csv",
        history_db=run_dir / "unused.sqlite",
        snapshot_date=report_date,
    )

    def build(stage: str):
        def handler(_config: BatchConfig) -> dict[str, Any]:
            nonlocal holdings_attempts
            calls.append(stage)
            if stage == "holdings":
                holdings_attempts += 1
                if holdings_attempts == 1:
                    raise RuntimeError("offline simulated network exhaustion")
            marker = run_dir / "markers" / f"{stage}_{calls.count(stage)}.done"
            atomic_write_text(marker, stage)
            return {"outputs": [marker], "summary": {"stage": stage}, "has_errors": False}

        return handler

    handlers = {stage: build(stage) for stage in STAGES}
    first_error = ""
    try:
        run_batch(config, handlers)
    except RuntimeError as exc:
        first_error = str(exc)
    failed_manifest = json.loads((run_dir / "batch_manifest.json").read_text(encoding="utf-8"))
    failed_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    final_manifest = run_batch(copy.copy(config), handlers)
    final_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    expected_calls = ["fund_pool", "holdings", "holdings", "readiness", "industry", "resources", "history", "reports"]
    passed = (
        "network exhaustion" in first_error
        and failed_manifest["overall_status"] == "failed"
        and failed_summary["exit_code"] == 1
        and final_manifest["overall_status"] == "completed"
        and final_summary["exit_code"] == 0
        and calls == expected_calls
        and final_manifest["stages"]["fund_pool"]["attempts"] == 1
        and final_manifest["stages"]["holdings"]["attempts"] == 2
    )
    return {
        "passed": passed,
        "first_status": failed_manifest["overall_status"],
        "first_exit_code": failed_summary["exit_code"],
        "final_status": final_manifest["overall_status"],
        "final_exit_code": final_summary["exit_code"],
        "calls": calls,
        "evidence": f"首次{failed_manifest['overall_status']}/退出码{failed_summary['exit_code']}；恢复后{final_manifest['overall_status']}/退出码{final_summary['exit_code']}；基金池1次、持仓2次",
    }


def _exercise_page_drift(report_date: str) -> dict[str, Any]:
    table = '<table class="tzxq"><thead><tr><th>序号</th><th>证券编号</th><th>证券简称</th></tr></thead><tbody><tr><td>1</td><td>600000</td><td>测试</td></tr></tbody></table>'
    content = f'<div class="boxitem"><h4>截止至：{report_date}</h4>{table}</div>'
    payload = 'var apidata={ content:"' + content.replace('"', r'\"') + '",arryear:[2026]};'
    rows, issue = parse_holdings(payload, report_date, "offline://page-drift")
    pipeline = _empty_pipeline(report_date, "测试混合A", issue)
    readiness = assess_disclosure(pipeline)
    passed = not rows and "字段不完整" in issue and not readiness["summary"]["is_ready"] and readiness["summary"]["status"] == "等待披露完整"
    return {"passed": passed, "parsed_rows": len(rows), "parse_issue": issue, "readiness": readiness["summary"], "evidence": f"解析{len(rows)}行；{issue}；门禁={readiness['summary']['status']}"}


def _exercise_share_fallback(report_date: str) -> dict[str, Any]:
    pipeline = {
        "summary": {"report_date": report_date},
        "funds": [
            {"fund_code": "000001", "fund_name": "测试混合A", "selected": True, "fetch_status": "已抓取"},
            {"fund_code": "000002", "fund_name": "测试混合C", "selected": True, "fetch_status": "无持仓/待核实"},
        ],
        "all_holdings": [{"fund_code": "000001", "report_date": report_date}],
        "issues": [{"fund_code": "000002", "category": "持仓为空"}],
    }
    readiness = assess_disclosure(pipeline)
    c_share = next(row for row in readiness["fund_readiness"] if row["fund_code"] == "000002")
    passed = readiness["summary"]["is_ready"] and readiness["summary"]["ready_product_count"] == 1 and c_share["gate_status"] == "份额重复不阻断"
    return {"passed": passed, "summary": readiness["summary"], "c_share": c_share, "evidence": f"产品1个、已就绪1个；C份额={c_share['gate_status']}"}


def _exercise_all_empty(report_date: str) -> dict[str, Any]:
    pipeline = {
        "summary": {"report_date": report_date},
        "funds": [
            {"fund_code": "000001", "fund_name": "测试混合A", "selected": True, "fetch_status": "无持仓/待核实"},
            {"fund_code": "000002", "fund_name": "测试混合C", "selected": True, "fetch_status": "无持仓/待核实"},
        ],
        "all_holdings": [],
        "issues": [
            {"fund_code": "000001", "category": "持仓为空"},
            {"fund_code": "000002", "category": "持仓为空"},
        ],
    }
    readiness = assess_disclosure(pipeline)
    passed = not readiness["summary"]["is_ready"] and readiness["summary"]["pending_product_count"] == 1 and readiness["summary"]["status"] == "等待披露完整"
    return {"passed": passed, "summary": readiness["summary"], "evidence": f"产品1个、待披露1个；门禁={readiness['summary']['status']}"}


def _exercise_corrupt_raw_cache(cache_dir: Path) -> dict[str, Any]:
    url = "https://offline.invalid/raw-cache"
    path = cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00broken")
    calls = 0
    original = manager_funds.fetch_url

    def fake_fetch(_url: str, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        return "offline-refreshed-raw-cache"

    manager_funds.fetch_url = fake_fetch
    try:
        value = CachedFetcher(cache_dir)(url)
    finally:
        manager_funds.fetch_url = original
    quarantined = sorted(cache_dir.glob("*.corrupt*"))
    temporary = sorted(cache_dir.glob("*.tmp"))
    passed = value == "offline-refreshed-raw-cache" and calls == 1 and len(quarantined) == 1 and path.read_text(encoding="utf-8") == value and not temporary
    return {"passed": passed, "fetch_calls": calls, "quarantined": [str(row) for row in quarantined], "temporary_files": [str(row) for row in temporary], "evidence": f"刷新{calls}次；旁路文件{len(quarantined)}个；残留临时文件{len(temporary)}个"}


def _exercise_corrupt_industry_cache(cache_dir: Path) -> dict[str, Any]:
    url = "https://offline.invalid/industry-cache"
    path = cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    calls = 0
    original = industry.urllib.request.urlopen

    def fake_urlopen(_request, timeout=0):
        nonlocal calls
        calls += 1
        return _Response("行业缓存已刷新".encode("utf-8"))

    industry.urllib.request.urlopen = fake_urlopen
    try:
        value = IndustryFetcher(cache_dir, retries=1, sleep_seconds=0)(url)
    finally:
        industry.urllib.request.urlopen = original
    quarantined = sorted(cache_dir.glob("*.corrupt*"))
    temporary = sorted(cache_dir.glob("*.tmp"))
    passed = value == "行业缓存已刷新" and calls == 1 and len(quarantined) == 1 and path.read_text(encoding="utf-8") == value and not temporary
    return {"passed": passed, "fetch_calls": calls, "quarantined": [str(row) for row in quarantined], "temporary_files": [str(row) for row in temporary], "evidence": f"刷新{calls}次；旁路文件{len(quarantined)}个；残留临时文件{len(temporary)}个"}


def _exercise_stale_quarter(report_date: str) -> dict[str, Any]:
    previous_date = "2026-03-31" if report_date == "2026-06-30" else "2025-12-31"
    table = '<table class="tzxq"><thead><tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>相关资讯</th><th>占净值比例</th><th>持股数（万股）</th><th>持仓市值（万元）</th></tr></thead><tbody><tr><td>1</td><td><a href="//quote.eastmoney.com/unify/r/1.600000">600000</a></td><td>测试</td><td></td><td>5%</td><td>1</td><td>10</td></tr></tbody></table>'
    content = f'<div class="boxitem"><h4>截止至：{previous_date}</h4>{table}</div>'
    payload = 'var apidata={ content:"' + content.replace('"', r'\"') + '",arryear:[2026]};'
    rows, issue = parse_holdings(payload, report_date, "offline://stale-quarter")
    passed = not rows and f"未找到报告期 {report_date}" in issue and previous_date in issue
    return {"passed": passed, "parsed_rows": len(rows), "issue": issue, "evidence": f"解析{len(rows)}行；{issue}"}


def _empty_pipeline(report_date: str, fund_name: str, issue: str) -> dict[str, Any]:
    return {
        "summary": {"report_date": report_date},
        "funds": [{"fund_code": "000001", "fund_name": fund_name, "selected": True, "fetch_status": "无持仓/待核实"}],
        "all_holdings": [],
        "issues": [{"fund_code": "000001", "category": "持仓为空", "message": issue}],
    }


def _build_playbook(payload: dict[str, Any]) -> str:
    return f"""# 基金持仓 Agent 故障处置手册

业务时区：`{payload['timezone']}`  
演练报告期：`{payload['report_date']}`  
演练结论：{payload['passed_check_count']}项通过，{payload['failed_check_count']}项失败。

## 状态与操作

| 现象 | 系统状态 | 操作 |
|---|---|---|
| 临时网络超时后重试成功 | 继续运行 | 查看重试日志，无需人工修改数据 |
| 达到重试上限 | `failed` / 退出码1 | 保留任务清单，重复执行原任务，从失败阶段续跑 |
| 目标季度未披露或网页字段无法解析 | `waiting` / 退出码2 | 不生成正式结果；核对原始页面并在下一窗口刷新持仓 |
| A/C/E之一空页，但同一基础产品另一份额有效 | 产品门禁通过 | 使用有效代表份额；空页保留异常审计 |
| 同一基础产品所有份额为空 | `waiting` / 退出码2 | 等待披露；仅在人工确认产品不适用后使用例外参数 |
| 缓存为空、乱码或含空字节 | 自动旁路并刷新 | 保留 `.corrupt` 文件；确认新缓存原子写入成功 |
| 缓存可读取但页面结构变化 | 解析异常并阻断 | 不自动删除缓存；修复解析规则并从相应阶段重跑 |
| 缓存只有旧季度 | `waiting` | 禁止跨季度回退，刷新目标报告期 |

## 安全边界

{chr(10).join(f'- {row}' for row in payload['safety_boundaries'])}

## DeepSeek

上述故障判断、重试、缓存恢复和披露门禁全部为确定性逻辑，不需要DeepSeek API。
"""
