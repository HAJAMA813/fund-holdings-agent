from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .candidate_confirmations import read_candidate_confirmation_csv
from .portfolio import atomic_write_json, atomic_write_text, company_directory_name, read_manager_roster
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now, latest_closed_quarter, quarter_label
from .resource_matching import read_personnel_csv


DEEPSEEK_RUNTIME_PATTERN = re.compile(
    r"api\.deepseek|deepseek[^\n]{0,40}(api[_-]?key|base_url|client)", re.IGNORECASE
)
ESSENTIAL_MANAGER_FILES = (
    "batch_manifest.json",
    "pipeline_data.json",
    "industry_analysis_data.json",
    "resource_matching_data.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(command: list[str], *, cwd: Path, timeout: int = 20) -> tuple[bool, str]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode == 0, output


def derive_readiness(checks: list[dict[str, Any]]) -> str:
    if any(row["severity"] == "阻断" and row["status"] == "FAIL" for row in checks):
        return "BLOCKED"
    if any(row["status"] in {"WARN", "SKIP"} for row in checks):
        return "READY_WITH_WARNINGS"
    return "READY"


def _audit_cache(directory: Path) -> dict[str, Any]:
    files = [path for path in directory.rglob("*") if path.is_file()] if directory.exists() else []
    corrupt = [path for path in files if ".corrupt" in path.name]
    temporary = [path for path in files if path.name.endswith(".tmp")]
    zero_size = [path for path in files if path.stat().st_size == 0]
    invalid: list[Path] = []
    for path in files:
        if path in corrupt or path in temporary or path in zero_size:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if "\x00" in text:
                invalid.append(path)
        except UnicodeDecodeError:
            invalid.append(path)
    return {
        "file_count": len(files),
        "corrupt_count": len(corrupt),
        "temporary_count": len(temporary),
        "zero_size_count": len(zero_size),
        "invalid_utf8_or_nul_count": len(invalid),
        "problem_examples": [str(path) for path in (corrupt + temporary + zero_size + invalid)[:10]],
    }


def _probe_writable(directory: Path) -> tuple[bool, str]:
    probe = directory / ".deployment_healthcheck_probe"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("healthcheck", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "healthcheck":
            return False, "写入后读取内容不一致"
        return True, "写入、读取和清理探针成功"
    except OSError as exc:
        return False, str(exc)
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def _active_scheduler_evidence(project_root: Path) -> list[str]:
    evidence: list[str] = []
    markers = ("fund-holdings-agent", "run_portfolio_quarterly", str(project_root))
    for command, label in ((["crontab", "-l"], "cron"), (["launchctl", "list"], "launchd")):
        passed, output = _run(command, cwd=project_root, timeout=10)
        if passed and any(marker in output for marker in markers):
            evidence.append(label)
    service_files = [
        project_root / "Dockerfile",
        project_root / "docker-compose.yml",
        project_root / "compose.yml",
        project_root / "ops" / "com.fund-holdings-agent.plist",
        project_root / ".github" / "workflows" / "quarterly.yml",
    ]
    evidence.extend(str(path.relative_to(project_root)) for path in service_files if path.exists())
    return evidence


def build_deployment_healthcheck(
    project_root: Path,
    portfolio_root: Path,
    roster_path: Path,
    personnel_path: Path,
    confirmation_path: Path,
    backfill_summary_path: Path,
    output_dir: Path,
    *,
    report_date: dt.date | None = None,
    min_free_gb: float = 2.0,
    network_result: dict[str, Any] | None = None,
    test_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    portfolio_root = portfolio_root.resolve()
    roster_path = roster_path.resolve()
    personnel_path = personnel_path.resolve()
    confirmation_path = confirmation_path.resolve()
    backfill_summary_path = backfill_summary_path.resolve()
    output_dir = output_dir.resolve()
    now = beijing_now()
    target_date = report_date or latest_closed_quarter(now.date())
    target_quarter = quarter_label(target_date)
    checks: list[dict[str, Any]] = []

    def add(
        check_id: str,
        group: str,
        name: str,
        status: str,
        evidence: str,
        *,
        severity: str = "阻断",
        action: str = "无需处理",
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "group": group,
                "name": name,
                "status": status,
                "severity": severity,
                "evidence": evidence,
                "action": action,
            }
        )

    required = [
        project_root / "pyproject.toml",
        project_root / "ops" / "run_portfolio_quarterly.sh",
        project_root / "src" / "fund_holdings_agent",
        roster_path,
        personnel_path,
        confirmation_path,
        backfill_summary_path,
    ]
    missing = [str(path) for path in required if not path.exists()]
    add("HC-01", "项目", "项目与生产输入文件完整", "FAIL" if missing else "PASS", "缺失：" + "；".join(missing) if missing else "关键代码、脚本、名单、人员库和确认库均存在", action="补齐缺失文件后重跑")

    python_ok = sys.version_info >= (3, 11)
    try:
        import lxml  # type: ignore

        lxml_version = getattr(lxml, "__version__", "unknown")
        lxml_ok = True
    except ImportError:
        lxml_version = "未安装"
        lxml_ok = False
    try:
        import openpyxl  # type: ignore

        openpyxl_version = getattr(openpyxl, "__version__", "unknown")
        openpyxl_ok = True
    except ImportError:
        openpyxl_version = "未安装"
        openpyxl_ok = False
    runtime_ok = python_ok and lxml_ok and openpyxl_ok
    add(
        "HC-02",
        "环境",
        "Python、lxml 和纯Python Excel依赖可用",
        "PASS" if runtime_ok else "FAIL",
        f"Python {sys.version.split()[0]}；lxml {lxml_version}；openpyxl {openpyxl_version}；Node/Codex不需要",
        action="安装缺失的Python依赖，或通过 FUND_AGENT_PYTHON 指定Python运行时",
    )

    script = project_root / "ops" / "run_portfolio_quarterly.sh"
    executable = script.exists() and os.access(script, os.X_OK)
    add("HC-03", "环境", "生产运行脚本可执行", "PASS" if executable else "FAIL", str(script), action="为脚本增加执行权限并复核解释器路径")

    try:
        roster = read_manager_roster(roster_path)
        companies = Counter(row.company for row in roster)
        roster_ok = len(roster) == 25 and sorted(companies.values()) == [5, 20]
        roster_evidence = f"启用 {len(roster)} 人；" + "；".join(f"{key}={value}" for key, value in companies.items())
    except (OSError, ValueError) as exc:
        roster = []
        roster_ok = False
        roster_evidence = str(exc)
    add("HC-04", "业务输入", "基金经理名单为已确认的25人范围", "PASS" if roster_ok else "FAIL", roster_evidence, action="核对姓名、公司、manager_id 和 active 字段")

    try:
        people, personnel_issues = read_personnel_csv(personnel_path)
        personnel_errors = sum(row.get("severity") == "错误" for row in personnel_issues)
        personnel_warnings = sum(row.get("severity") == "警告" for row in personnel_issues)
        personnel_ok = len(people) > 0 and personnel_errors == 0
        personnel_evidence = f"人员 {len(people)}；错误 {personnel_errors}；警告 {personnel_warnings}"
    except (OSError, ValueError) as exc:
        people, personnel_issues, personnel_warnings = [], [], 0
        personnel_ok = False
        personnel_evidence = str(exc)
    add("HC-05", "业务输入", "研究人员库可读取且无错误", "PASS" if personnel_ok else "FAIL", personnel_evidence, action="修正人员库必填字段、重复项或枚举值")
    if personnel_ok and personnel_warnings:
        add("HC-06", "业务输入", "人员库警告已显式披露", "WARN", f"共 {personnel_warnings} 条警告，主要为未参与行业自动匹配的人员", severity="警告", action="不阻断抓取；人员库维护者可逐步完善覆盖口径")
    else:
        add("HC-06", "业务输入", "人员库警告已显式披露", "PASS", "没有待披露警告", severity="警告")

    try:
        confirmation_records, confirmation_issues = read_candidate_confirmation_csv(confirmation_path)
        backfill = _read_json(backfill_summary_path)
        confirmation_sha = _sha256(confirmation_path)
        confirmation_ok = (
            len(confirmation_records) > 0
            and not confirmation_issues
            and confirmation_sha == backfill.get("candidate_confirmation_sha256")
            and int(backfill.get("candidate_confirmation_error_count", -1)) == 0
        )
        confirmation_evidence = f"关系 {len(confirmation_records)}；解析问题 {len(confirmation_issues)}；SHA-256={confirmation_sha}"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        confirmation_ok = False
        confirmation_evidence = str(exc)
    add("HC-07", "业务输入", "候选确认规则库与回填摘要一致", "PASS" if confirmation_ok else "FAIL", confirmation_evidence, action="重新生成或人工复核候选确认规则库，确保哈希勾稽")

    usage = shutil.disk_usage(portfolio_root if portfolio_root.exists() else project_root)
    free_gb = usage.free / (1024**3)
    add("HC-08", "存储", "磁盘余量满足运行阈值", "PASS" if free_gb >= min_free_gb else "FAIL", f"可用 {free_gb:.1f} GiB；阈值 {min_free_gb:.1f} GiB", action="清理或扩容输出磁盘")
    writable_ok, writable_evidence = _probe_writable(portfolio_root)
    add("HC-09", "存储", "生产输出目录可写且探针无残留", "PASS" if writable_ok else "FAIL", writable_evidence, action="修复目录权限或可用空间")

    raw_audit = _audit_cache(portfolio_root / "_cache" / "raw")
    industry_audit = _audit_cache(portfolio_root / "_cache" / "industry")
    cache_bad = sum(
        audit[key]
        for audit in (raw_audit, industry_audit)
        for key in ("temporary_count", "zero_size_count", "invalid_utf8_or_nul_count")
    )
    cache_warn = raw_audit["corrupt_count"] + industry_audit["corrupt_count"]
    cache_status = "FAIL" if cache_bad else ("WARN" if cache_warn else "PASS")
    add(
        "HC-10",
        "缓存",
        "生产缓存无损坏或中断写入残留",
        cache_status,
        f"raw={json.dumps(raw_audit, ensure_ascii=False)}；industry={json.dumps(industry_audit, ensure_ascii=False)}",
        severity="阻断" if cache_bad else ("警告" if cache_warn else "阻断"),
        action="保留异常副本；刷新相应缓存并从失败阶段续跑",
    )

    db_path = portfolio_root / "fund_holdings_history.sqlite"
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        run_count = connection.execute("SELECT COUNT(*) FROM quarter_runs").fetchone()[0]
        comparison_count = connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
        connection.close()
        db_ok = integrity == "ok" and run_count >= len(roster) * 2 and comparison_count >= len(roster)
        db_evidence = f"integrity={integrity}；季度运行 {run_count}；季度比较 {comparison_count}"
    except (OSError, sqlite3.Error) as exc:
        db_ok = False
        db_evidence = str(exc)
    add("HC-11", "历史库", "SQLite 完整且具备两期基线", "PASS" if db_ok else "FAIL", db_evidence, action="从已验证 JSON 结果重建历史库，禁止在损坏库上继续写入")

    portfolio_summary_path = portfolio_root / f"portfolio_summary_{target_quarter}.json"
    try:
        portfolio_summary = _read_json(portfolio_summary_path)
        summary_managers = portfolio_summary.get("manager_results", [])
        summary_ok = (
            portfolio_summary.get("overall_status") == "completed"
            and portfolio_summary.get("report_date") == target_date.isoformat()
            and len(summary_managers) == len(roster)
            and all(row.get("overall_status") == "completed" for row in summary_managers)
        )
        summary_evidence = f"状态={portfolio_summary.get('overall_status')}；报告期={portfolio_summary.get('report_date')}；经理={len(summary_managers)}"
    except (OSError, json.JSONDecodeError) as exc:
        summary_ok = False
        summary_evidence = str(exc)
    add("HC-12", "生产基线", "最近结束季度25位经理全部完成", "PASS" if summary_ok else "FAIL", summary_evidence, action="补跑失败或缺失经理，再执行健康检查")

    missing_manager_files: list[str] = []
    missing_comparisons: list[str] = []
    for entry in roster:
        manager_dir = portfolio_root / company_directory_name(entry.company) / f"{entry.manager}_{target_quarter}"
        for filename in ESSENTIAL_MANAGER_FILES:
            if not (manager_dir / filename).exists():
                missing_manager_files.append(str(manager_dir / filename))
        if not (manager_dir / "quarter_comparison_data.json").exists():
            missing_comparisons.append(entry.manager)
    manager_files_ok = not missing_manager_files and not missing_comparisons and bool(roster)
    add(
        "HC-13",
        "生产基线",
        "逐经理管道、行业、资源、任务清单和季度比较齐全",
        "PASS" if manager_files_ok else "FAIL",
        f"检查 {len(roster)} 人；缺关键文件 {len(missing_manager_files)}；缺比较 {len(missing_comparisons)}" + (f"；示例={missing_manager_files[:3]}" if missing_manager_files else ""),
        action="按缺失清单从对应阶段续跑",
    )

    evidence_files = {
        "第一阶段验收": project_root / "outputs" / "019fff23-cef4-7d91-8837-7401263c06d4" / "phase1_acceptance" / "phase1_acceptance_2026Q2.json",
        "季度切换演练": project_root / "outputs" / "019fff23-cef4-7d91-8837-7401263c06d4" / "quarter_rehearsal_2026Q3" / "quarter_rehearsal_summary_2026Q3.json",
        "准生产回放": project_root / "outputs" / "019fff23-cef4-7d91-8837-7401263c06d4" / "preproduction_replay_2026Q1_to_Q2" / "preproduction_replay_summary_2026Q1_to_2026Q2.json",
        "故障恢复演练": project_root / "outputs" / "019fff23-cef4-7d91-8837-7401263c06d4" / "failure_rehearsal" / "failure_rehearsal_summary.json",
    }
    expected_statuses = {
        "第一阶段验收": {"accepted_with_caveats"},
        "季度切换演练": {"passed"},
        "准生产回放": {"passed", "passed_with_limitations"},
        "故障恢复演练": {"passed"},
    }
    evidence_status: dict[str, str] = {}
    for label, path in evidence_files.items():
        try:
            evidence_status[label] = str(_read_json(path).get("overall_status", ""))
        except (OSError, json.JSONDecodeError):
            evidence_status[label] = "missing_or_invalid"
    rehearsals_ok = all(evidence_status[label] in expected_statuses[label] for label in evidence_files)
    add("HC-14", "验证证据", "验收、季度切换、准生产回放和故障演练通过", "PASS" if rehearsals_ok else "FAIL", json.dumps(evidence_status, ensure_ascii=False), action="重新运行缺失或失败的离线验证")

    findings: list[str] = []
    source_root = project_root / "src" / "fund_holdings_agent"
    for source in source_root.glob("*.py"):
        if source.name in {"acceptance.py", "deployment_healthcheck.py", "llm_agent.py", "llm_agent_cli.py", "agent.py", "agent_cli.py"}:
            continue
        if DEEPSEEK_RUNTIME_PATTERN.search(source.read_text(encoding="utf-8")):
            findings.append(str(source))
    add("HC-15", "模型边界", "确定性管道未接入 DeepSeek 运行时", "PASS" if not findings else "FAIL", "未发现 DeepSeek 客户端、密钥或基础地址" if not findings else "；".join(findings), action="移除核心管道中的模型依赖；模型只能用于非核心文本辅助")

    if test_result is None:
        add("HC-16", "自动测试", "本次健康检查包含全量自动测试", "SKIP", "未使用 --run-tests；本项不替代历史测试证据", severity="警告", action="上线前使用 --run-tests 再执行一次")
    else:
        add("HC-16", "自动测试", "本次健康检查包含全量自动测试", "PASS" if test_result.get("passed") else "FAIL", str(test_result.get("summary", "")), action="修复失败测试后重跑健康检查")

    if network_result is None:
        add("HC-17", "外部数据源", "本次探测天天基金与东方财富连通性", "SKIP", "离线模式，未发起真实网络请求", severity="警告", action="正式部署主机上使用 --check-network 验证连通性")
    else:
        add("HC-17", "外部数据源", "本次探测天天基金与东方财富连通性", "PASS" if network_result.get("passed") else "FAIL", str(network_result.get("evidence", "")), action="检查 DNS、代理、TLS、访问频率和数据源页面变化")

    scheduler_evidence = _active_scheduler_evidence(project_root)
    if scheduler_evidence:
        add("HC-18", "部署", "已发现常驻或定时调度配置", "PASS", "；".join(scheduler_evidence), severity="警告")
    else:
        add("HC-18", "部署", "已发现常驻或定时调度配置", "WARN", "当前仅有本机运行脚本，未发现 cron、launchd、容器或 CI 季度任务", severity="警告", action="确定部署主机后配置调度、日志保留和失败通知")
    add("HC-19", "口径限制", "历史行业时点限制已显式披露", "WARN", "申万一级行业采用当前公开快照，尚非带生效日期的历史行业库", severity="警告", action="获得授权历史行业数据源后升级，不影响当前快照分析")

    readiness = derive_readiness(checks)
    scheduler_ready = bool(scheduler_evidence)
    result = {
        "title": "基金持仓 Agent 上线前健康检查",
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": now.isoformat(timespec="seconds"),
        "report_date": target_date.isoformat(),
        "quarter": target_quarter,
        "manual_run_readiness": readiness,
        "automation_deployment_status": "DEPLOYED" if scheduler_ready and readiness != "BLOCKED" else "NOT_DEPLOYED",
        "blocking_failure_count": sum(row["severity"] == "阻断" and row["status"] == "FAIL" for row in checks),
        "warning_or_skipped_count": sum(row["status"] in {"WARN", "SKIP"} for row in checks),
        "passed_check_count": sum(row["status"] == "PASS" for row in checks),
        "total_check_count": len(checks),
        "checks": checks,
        "deepseek_used": False,
        "network_checked": network_result is not None,
        "test_result": test_result,
        "deployment_scope": "当前项目位于本机目录；健康检查不等于常驻服务部署",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = atomic_write_json(output_dir / "deployment_healthcheck.json", result)
    report_path = atomic_write_text(output_dir / "上线健康检查报告.md", render_healthcheck_markdown(result))
    todo_path = atomic_write_text(output_dir / "部署待办清单.md", render_deployment_todo(result))
    result["artifacts"] = {"json": str(json_path), "report": str(report_path), "todo": str(todo_path)}
    atomic_write_json(json_path, result)
    return result


def render_healthcheck_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 基金持仓 Agent 上线健康检查报告",
        "",
        f"- 生成时间（北京时间）：{result['generated_at_beijing']}",
        f"- 检查报告期：{result['report_date']}（{result['quarter']}）",
        f"- 手动运行就绪度：**{result['manual_run_readiness']}**",
        f"- 自动化部署状态：**{result['automation_deployment_status']}**",
        f"- 检查结果：通过 {result['passed_check_count']}，警告/跳过 {result['warning_or_skipped_count']}，阻断失败 {result['blocking_failure_count']}",
        "- DeepSeek：未调用",
        "",
        "## 检查明细",
        "",
        "| 编号 | 分组 | 检查项 | 严重性 | 状态 | 证据 |",
        "|---|---|---|---|---|---|",
    ]
    for row in result["checks"]:
        evidence = str(row["evidence"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row['id']} | {row['group']} | {row['name']} | {row['severity']} | {row['status']} | {evidence} |")
    lines.extend(["", "## 判定说明", "", "`READY` 表示阻断项与警告项均清零；`READY_WITH_WARNINGS` 表示可手动运行但仍有已披露的非阻断事项；`BLOCKED` 表示不得开始正式任务。自动化部署状态单独判断，只有发现实际调度配置时才会标记为 `DEPLOYED`。", ""])
    return "\n".join(lines)


def render_deployment_todo(result: dict[str, Any]) -> str:
    pending = [row for row in result["checks"] if row["status"] in {"FAIL", "WARN", "SKIP"}]
    lines = ["# 部署待办清单", "", f"当前手动运行就绪度：**{result['manual_run_readiness']}**", f"当前自动化部署状态：**{result['automation_deployment_status']}**", ""]
    if not pending:
        lines.append("- 无待办项。")
    else:
        for row in pending:
            lines.append(f"- [{row['severity']}/{row['status']}] {row['id']} {row['name']}：{row['action']}。证据：{row['evidence']}")
    lines.extend(["", "上线完成定义：选择稳定运行主机，安装项目声明的Python依赖，配置北京时间季度调度和失败通知，并在部署主机执行包含自动测试及真实网络探测的健康检查。", ""])
    return "\n".join(lines)
