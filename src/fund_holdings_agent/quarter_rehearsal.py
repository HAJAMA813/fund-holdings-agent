from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .batch import BatchConfig, STAGES, run_batch
from .candidate_confirmations import read_candidate_confirmation_csv
from .eastmoney import parse_holdings
from .portfolio import atomic_write_json, atomic_write_text, read_manager_roster
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now, latest_closed_quarter
from .resource_matching import build_resource_matching, read_personnel_csv


DEFAULT_TARGET_REPORT_DATE = "2026-09-30"


def run_quarter_rehearsal(
    project_root: Path,
    output_dir: Path,
    roster_path: Path,
    personnel_path: Path,
    confirmation_path: Path,
    target_report_date: str = DEFAULT_TARGET_REPORT_DATE,
) -> dict[str, Any]:
    """Run the next-quarter controls entirely with local synthetic data."""
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    roster_path = roster_path.resolve()
    personnel_path = personnel_path.resolve()
    confirmation_path = confirmation_path.resolve()
    target_date = dt.date.fromisoformat(target_report_date)
    if target_date.month not in {3, 6, 9, 12}:
        raise ValueError("target_report_date 必须是自然季度末")

    checks: list[dict[str, Any]] = []

    def check(check_id: str, group: str, name: str, passed: bool, evidence: str) -> None:
        checks.append(
            {
                "id": check_id,
                "group": group,
                "name": name,
                "status": "通过" if passed else "失败",
                "severity": "阻断",
                "evidence": evidence,
            }
        )

    # A quarter becomes the latest closed quarter on the next Beijing calendar day.
    quarter_end_result = latest_closed_quarter(target_date)
    next_day = target_date + dt.timedelta(days=1)
    next_day_result = latest_closed_quarter(next_day)
    check(
        "Q3-01",
        "季度口径",
        "季度末当天不提前切换，次日才切换目标季度",
        quarter_end_result != target_date and next_day_result == target_date,
        f"{target_date} -> {quarter_end_result}；{next_day} -> {next_day_result}",
    )

    sydney_zone = ZoneInfo("Australia/Sydney")
    before_beijing_midnight = dt.datetime.combine(next_day, dt.time(0, 30), tzinfo=sydney_zone)
    after_beijing_midnight = dt.datetime.combine(next_day, dt.time(2, 30), tzinfo=sydney_zone)
    before_beijing = beijing_now(before_beijing_midnight)
    after_beijing = beijing_now(after_beijing_midnight)
    before_target = latest_closed_quarter(before_beijing.date())
    after_target = latest_closed_quarter(after_beijing.date())
    check(
        "Q3-02",
        "时区",
        "悉尼运行时间按北京时间边界判断季度",
        before_target != target_date and after_target == target_date,
        (
            f"悉尼 {before_beijing_midnight.isoformat()} = 北京 {before_beijing.isoformat()}，目标 {before_target}；"
            f"悉尼 {after_beijing_midnight.isoformat()} = 北京 {after_beijing.isoformat()}，目标 {after_target}"
        ),
    )

    prior_report_date = quarter_end_result.isoformat()
    payload = _single_quarter_payload(prior_report_date)
    prior_rows, prior_issue = parse_holdings(payload, prior_report_date, "offline://eastmoney/q2")
    target_rows, target_issue = parse_holdings(payload, target_report_date, "offline://eastmoney/q3")
    check(
        "Q3-03",
        "报告期防串期",
        "只有上一季度数据时不得回退代替目标季度",
        bool(prior_rows) and not prior_issue and not target_rows and f"未找到报告期 {target_report_date}" in target_issue,
        f"上一季度解析 {len(prior_rows)} 行；目标季度解析 {len(target_rows)} 行；提示：{target_issue}",
    )

    simulated_run = _simulate_wait_and_resume(output_dir / "simulated_run", target_report_date)
    first = simulated_run["first_run"]
    second = simulated_run["second_run"]
    check(
        "Q3-04",
        "披露等待",
        "披露不完整时暂停正式分析并返回等待退出码",
        first["overall_status"] == "waiting"
        and first["exit_code"] == 2
        and first["executed_stages"] == ["fund_pool", "holdings", "readiness"],
        f"状态 {first['overall_status']}；退出码 {first['exit_code']}；执行阶段 {first['executed_stages']}",
    )
    check(
        "Q3-05",
        "断点续跑",
        "下一检查窗口刷新持仓并从持仓阶段续跑",
        second["overall_status"] == "completed"
        and second["exit_code"] == 0
        and second["executed_stages"] == ["holdings", "readiness", "industry", "resources", "history", "reports"]
        and second["stage_attempts"]["fund_pool"] == 1
        and second["stage_attempts"]["holdings"] == 2,
        (
            f"第二次执行阶段 {second['executed_stages']}；"
            f"基金池尝试 {second['stage_attempts']['fund_pool']} 次；持仓尝试 {second['stage_attempts']['holdings']} 次"
        ),
    )

    roster = read_manager_roster(roster_path)
    company_counts = Counter(entry.company for entry in roster)
    check(
        "Q3-06",
        "基金经理名单",
        "25位基金经理名单可直接复用",
        len(roster) == 25 and sorted(company_counts.values()) == [5, 20],
        f"共 {len(roster)} 人；" + "；".join(f"{company} {count} 人" for company, count in sorted(company_counts.items())),
    )

    people, personnel_issues = read_personnel_csv(personnel_path)
    personnel_errors = [row for row in personnel_issues if row.get("severity") == "错误"]
    check(
        "Q3-07",
        "人员库",
        "研究所人员库可读取且无阻断错误",
        len(people) > 0 and not personnel_errors,
        f"人员 {len(people)}；错误 {len(personnel_errors)}；警告 {len(personnel_issues) - len(personnel_errors)}",
    )

    confirmations, confirmation_issues = read_candidate_confirmation_csv(confirmation_path)
    confirmation_sha = _sha256(confirmation_path)
    check(
        "Q3-08",
        "确认规则库",
        "候选确认关系可读取且无错误",
        len(confirmations) > 0 and not confirmation_issues,
        f"确认关系 {len(confirmations)}；解析错误 {len(confirmation_issues)}；SHA-256 {confirmation_sha}",
    )

    reuse_result = _exercise_confirmation_reuse(people, personnel_issues, confirmations, confirmation_issues, confirmation_path)
    check(
        "Q3-09",
        "确认规则复用",
        "上一季度人工确认可在新季度同一候选关系出现时自动复用",
        reuse_result["passed"],
        reuse_result["evidence"],
    )

    checklist_path = output_dir / f"上线操作清单_{target_date.year}Q{target_date.month // 3}.md"
    summary_path = output_dir / f"quarter_rehearsal_summary_{target_date.year}Q{target_date.month // 3}.json"
    atomic_write_text(checklist_path, _build_checklist(target_date, project_root, output_dir))

    failed = [row for row in checks if row["status"] == "失败"]
    payload_out: dict[str, Any] = {
        "title": "基金持仓 Agent 新季度离线切换演练",
        "target_report_date": target_report_date,
        "target_quarter": f"{target_date.year}Q{target_date.month // 3}",
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "overall_status": "passed" if not failed else "needs_revision",
        "passed_check_count": sum(row["status"] == "通过" for row in checks),
        "failed_check_count": len(failed),
        "network_used": False,
        "deepseek_used": False,
        "checks": checks,
        "simulated_runs": simulated_run,
        "reusable_inputs": {
            "roster": {"path": str(roster_path), "manager_count": len(roster), "company_counts": dict(company_counts)},
            "personnel": {
                "path": str(personnel_path),
                "person_count": len(people),
                "error_count": len(personnel_errors),
                "warning_count": len(personnel_issues) - len(personnel_errors),
            },
            "candidate_confirmations": {
                "path": str(confirmation_path),
                "relation_count": len(confirmations),
                "error_count": len(confirmation_issues),
                "sha256": confirmation_sha,
                "synthetic_reuse_check": reuse_result,
            },
        },
        "caveats": [
            "本次只验证季度切换、等待门禁、断点续跑和规则复用，不代表2026Q3真实公开披露已经可得。",
            "真实2026Q3任务最早应在北京时间2026-10-01进入检查窗口；未披露完整时应保留等待状态。",
            "本次不联网、不生成正式基金数据 Excel，也未调用 DeepSeek 或其他大模型。",
        ],
        "recommended_next_step": "冻结演练结果；到北京时间2026-10-01后使用季度运行脚本执行真实检查，若返回等待则在下一检查窗口续跑。",
        "outputs": {
            "summary": str(summary_path),
            "checklist": str(checklist_path),
            "simulated_manifest": str((output_dir / "simulated_run" / "batch_manifest.json").resolve()),
            "simulated_batch_summary": str((output_dir / "simulated_run" / "batch_summary.json").resolve()),
        },
    }
    atomic_write_json(summary_path, payload_out)
    return payload_out


def _single_quarter_payload(report_date: str) -> str:
    table = (
        '<table class="tzxq"><thead><tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>相关资讯</th>'
        '<th>占净值比例</th><th>持股数（万股）</th><th>持仓市值（万元）</th></tr></thead><tbody>'
        '<tr><td>1</td><td><a href="//quote.eastmoney.com/unify/r/1.600001">600001</a></td>'
        '<td>离线测试股票</td><td></td><td>5%</td><td>1</td><td>10</td></tr></tbody></table>'
    )
    content = f'<div class="boxitem"><h4>截止至：{report_date}</h4>{table}</div>'
    return 'var apidata={ content:"' + content.replace('"', r'\"') + '",arryear:[2026]};'


def _simulate_wait_and_resume(run_dir: Path, report_date: str) -> dict[str, Any]:
    calls: list[str] = []
    readiness_attempts = 0
    config = BatchConfig(
        manager="离线演练经理",
        report_date=report_date,
        output_dir=run_dir,
        raw_cache_dir=run_dir / "cache" / "raw",
        industry_cache_dir=run_dir / "cache" / "industry",
        personnel_path=run_dir / "not_used_people.csv",
        history_db=run_dir / "not_used_history.sqlite",
        snapshot_date=(dt.date.fromisoformat(report_date) + dt.timedelta(days=1)).isoformat(),
    )

    def build_handler(stage: str):
        def handler(_config: BatchConfig) -> dict[str, Any]:
            nonlocal readiness_attempts
            calls.append(stage)
            if stage == "readiness":
                readiness_attempts += 1
                waiting = readiness_attempts == 1
                summary = {
                    "selected_fund_count": 2,
                    "ready_fund_count": 1 if waiting else 2,
                    "pending_fund_count": 1 if waiting else 0,
                }
            else:
                waiting = False
                summary = {"stage": stage, "mode": "offline_stub"}
            attempt = calls.count(stage)
            output = run_dir / "markers" / f"{stage}_attempt_{attempt}.done"
            atomic_write_text(output, f"{stage}\n")
            return {
                "outputs": [output],
                "summary": summary,
                "has_errors": waiting,
                "gate_waiting": waiting,
                "reason": "离线模拟：目标报告期披露尚未完整",
            }

        return handler

    handlers = {stage: build_handler(stage) for stage in STAGES}
    first_manifest = run_batch(config, handlers)
    first_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    first_snapshot = {
        "overall_status": first_manifest["overall_status"],
        "exit_code": first_summary["exit_code"],
        "executed_stages": first_summary["executed_stages"],
        "stage_statuses": first_summary["stage_statuses"],
        "notification_summary": first_summary["notification_summary"],
        "stage_attempts": {stage: first_manifest["stages"][stage]["attempts"] for stage in STAGES},
    }

    retry_config = copy.copy(config)
    retry_config.refresh = True
    retry_config.force_stage = "holdings"
    second_manifest = run_batch(retry_config, handlers)
    second_summary = json.loads((run_dir / "batch_summary.json").read_text(encoding="utf-8"))
    second_snapshot = {
        "overall_status": second_manifest["overall_status"],
        "exit_code": second_summary["exit_code"],
        "executed_stages": second_summary["executed_stages"],
        "stage_statuses": second_summary["stage_statuses"],
        "notification_summary": second_summary["notification_summary"],
        "stage_attempts": {stage: second_manifest["stages"][stage]["attempts"] for stage in STAGES},
    }
    return {"first_run": first_snapshot, "second_run": second_snapshot, "all_stage_calls": calls}


def _exercise_confirmation_reuse(
    people: list[Any],
    personnel_issues: list[dict[str, str]],
    confirmations: dict[tuple[str, str, str, str], dict[str, str]],
    confirmation_issues: list[dict[str, str]],
    confirmation_path: Path,
) -> dict[str, Any]:
    candidate_people = {
        (person.person_name, person.organization)
        for person in people
        if person.industry_mapping_status == "候选映射"
    }
    company_keys = sorted(
        key
        for key in confirmations
        if key[0] == "公司" and (key[2], key[3]) in candidate_people
    )
    if not company_keys:
        return {"passed": False, "evidence": "规则库中没有候选映射人员仍在库内且已确认的公司关系可演练复用"}
    key = company_keys[0]
    person = next(person for person in people if (person.person_name, person.organization) == (key[2], key[3]))
    sw_level1 = person.sw_level1[0] if person.sw_level1 else ""
    sw_level2 = person.covered_sw_level2[0] if person.covered_sw_level2 else ""
    industry_data = {
        "summary": {"report_date": DEFAULT_TARGET_REPORT_DATE},
        "industry_summary": [
            {
                "sw_level1": sw_level1,
                "fund_code": "OFF001",
                "holding_count": 1,
                "market_value_10k": 10.0,
                "nav_ratio": 0.05,
            }
        ],
        "formal_holdings_industry": [
            {
                "fund_code": "OFF001",
                "stock_code": key[1],
                "stock_name": str(confirmations[key].get("target_name", "")),
                "market": "A股",
                "sw_level1": sw_level1,
                "sw_level2": sw_level2,
                "market_value_10k": 10.0,
                "nav_ratio": 0.05,
            }
        ],
    }
    result = build_resource_matching(
        industry_data,
        people,
        personnel_issues,
        confirmations,
        confirmation_issues,
        str(confirmation_path),
    )
    matching = [
        row
        for row in result["matches"]
        if (row["demand_type"], row["target_code"], row["person_name"], row["organization"]) == key
    ]
    passed = (
        len(matching) == 1
        and matching[0]["confirmation_status"] == "业务已确认"
        and matching[0].get("original_confirmation_status") == "待确认"
        and matching[0]["score"] == 30
        and matching[0]["match_type"] == "研究分组候选覆盖"
    )
    evidence = (
        f"命中 {len(matching)} 条；状态 {matching[0]['confirmation_status'] if matching else '未命中'}；"
        f"分数 {matching[0]['score'] if matching else '-'}；匹配方式 {matching[0]['match_type'] if matching else '-'}"
    )
    return {"passed": passed, "evidence": evidence, "test_key": list(key)}


def _build_checklist(target_date: dt.date, project_root: Path, output_dir: Path) -> str:
    quarter = f"{target_date.year}Q{target_date.month // 3}"
    first_check = target_date + dt.timedelta(days=1)
    return f"""# {quarter} 基金持仓任务上线操作清单

本清单依据离线切换演练生成。业务时区统一为 `Asia/Shanghai`（北京时间）。

## 启动前

- [ ] 在北京时间 {first_check.isoformat()} 之前，不把 {target_date.isoformat()} 作为“最近已结束季度”执行真实抓取。
- [ ] 确认基金经理名单仍为 `{project_root / 'data/managers_portfolio.csv'}` 中的25人；人员变更先更新名单。
- [ ] 确认人员库为 `{project_root / 'data/personnel_internal_20260616.csv'}`，并复核离岗、转组和联系权限变化。
- [ ] 确认候选关系规则库 `{project_root / 'data/resource_candidate_confirmations.csv'}` 未被意外修改；现有关系只复用相同需求、目标、人员和机构。
- [ ] 港股继续不进入研究资源匹配；只保留排除审计。

## 首次真实检查

- [ ] 在北京时间 {first_check.isoformat()} 或之后运行 `ops/run_portfolio_quarterly.sh`。
- [ ] 检查目标报告期是否为 `{target_date.isoformat()}`，不能用上一季度持仓替代。
- [ ] 若退出码为 `2`、状态为 `waiting`，这是正常披露等待，不生成或使用不完整的正式分析。
- [ ] 下一披露检查窗口原样重跑；系统应自动刷新并从 `holdings` 阶段续跑，不重复基金池阶段。

## 完成后

- [ ] 确认退出码为 `0` 或明确处理 `completed_with_errors` 中的异常清单。
- [ ] 核对每位经理的报告期、正式基金数、每只基金前十大持仓数量、A/C/E份额代表份额及行业映射异常。
- [ ] 核对人员对接结果中的“业务已确认”仅来自规则库，30分候选关系未被提升为精确覆盖。
- [ ] 核对联系方式：联系权限非“允许”的记录必须继续显示“已隐藏”。
- [ ] 保存本地运行回执、公司级 Excel、异常清单和机器可读摘要；不发送 Slack。

## DeepSeek 边界

- 当前季度抓取、清洗、校验、行业映射、资源匹配、Excel 和运行摘要均不需要 DeepSeek API。
- 只有未来明确增加“异常自然语言解释、非结构化材料归纳或自由文本问答”时才评估接入；接入前必须先说明用途、上传字段、脱敏方式、成本和失败降级方案并取得确认。

演练输出目录：`{output_dir}`
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
