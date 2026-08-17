from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .portfolio import atomic_write_json, read_manager_roster
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now


EXPECTED_RESOURCE_SHEETS = {
    "运行摘要",
    "基金经理概览",
    "行业需求汇总",
    "公司需求汇总",
    "人员对接汇总",
    "匹配明细",
    "待确认事项",
    "待补充项",
    "不纳入资源匹配",
    "数据校验",
    "来源与口径",
}
FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A")
DEEPSEEK_RUNTIME_PATTERN = re.compile(r"api\.deepseek|deepseek[^\n]{0,40}(api[_-]?key|base_url|client)", re.IGNORECASE)


def build_phase1_acceptance(
    project_root: Path,
    roster_path: Path,
    backfill_summary_path: Path,
    company_summary_path: Path,
    candidate_confirmation_path: Path,
    output_path: Path,
    test_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    roster_path = roster_path.resolve()
    backfill_summary_path = backfill_summary_path.resolve()
    company_summary_path = company_summary_path.resolve()
    candidate_confirmation_path = candidate_confirmation_path.resolve()
    checks: list[dict[str, Any]] = []

    def check(group: str, name: str, passed: bool, evidence: str, *, severity: str = "阻断") -> None:
        checks.append(
            {
                "group": group,
                "name": name,
                "status": "通过" if passed else "失败",
                "severity": severity,
                "evidence": evidence,
            }
        )

    required_paths = [
        project_root / "pyproject.toml",
        project_root / "README.md",
        project_root / "需求文档.md",
        project_root / "docs" / "phase1_audit.md",
        project_root / "src" / "fund_holdings_agent",
        project_root / "tests",
        roster_path,
        backfill_summary_path,
        company_summary_path,
        candidate_confirmation_path,
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    check("项目结构", "可重复运行的项目结构与审计材料存在", not missing, "缺失：" + "；".join(missing) if missing else "src、tests、data、docs、README、需求文档和关键摘要均存在")

    entries = read_manager_roster(roster_path)
    backfill = _read_json(backfill_summary_path)
    company_summary = _read_json(company_summary_path)
    check(
        "基金经理范围",
        "名单与全量回填经理数一致",
        len(entries) == int(backfill.get("manager_count", -1)),
        f"名单 {len(entries)} 人；回填摘要 {backfill.get('manager_count')} 人",
    )
    check(
        "基金经理范围",
        "所有基金经理完成",
        int(backfill.get("completed_manager_count", -1)) == len(entries) and int(backfill.get("failed_manager_count", -1)) == 0,
        f"完成 {backfill.get('completed_manager_count')}/{len(entries)}；失败 {backfill.get('failed_manager_count')}",
    )

    registry_sha = _sha256(candidate_confirmation_path) if candidate_confirmation_path.exists() else ""
    registry_rows = max(0, len(candidate_confirmation_path.read_text(encoding="utf-8-sig").splitlines()) - 1) if candidate_confirmation_path.exists() else 0
    check(
        "研究资源",
        "候选确认规则库完整且哈希一致",
        registry_rows == int(backfill.get("candidate_confirmation_relation_count", -1))
        and registry_sha == backfill.get("candidate_confirmation_sha256")
        and int(backfill.get("candidate_confirmation_error_count", -1)) == 0,
        f"规则 {registry_rows} 条；SHA-256 {registry_sha}；解析错误 {backfill.get('candidate_confirmation_error_count')}",
    )
    check(
        "研究资源",
        "候选确认与待补充项已闭环",
        int(backfill.get("confirmed_candidate_match_count_sum", -1)) >= 0
        and int(backfill.get("candidate_match_count_sum", -1)) == 0
        and int(backfill.get("pending_count_sum", -1)) == 0,
        f"业务已确认 {backfill.get('confirmed_candidate_match_count_sum')}；待确认 {backfill.get('candidate_match_count_sum')}；待补充 {backfill.get('pending_count_sum')}",
    )

    company_rows = company_summary.get("companies", [])
    company_metric_by_name = {row["company"]: row for row in backfill.get("company_metrics", [])}
    company_data: list[dict[str, Any]] = []
    workbooks: list[Path] = []
    for company_row in company_rows:
        data_path = Path(company_row["data_path"])
        data = _read_json(data_path)
        company_data.append(data)
        company_short = data_path.parent.name
        workbook = data_path.parent / f"{company_short}_{data['summary']['quarter']}_研究资源对接汇总.xlsx"
        workbooks.append(workbook)
        metric = company_metric_by_name.get(company_row["company"], {})
        summary = data.get("summary", {})
        aligned = all(
            int(summary.get(key, -1)) == int(metric.get(key, -2))
            for key in (
                "manager_count",
                "completed_manager_count",
                "industry_demand_count_sum",
                "company_demand_count_sum",
                "match_count_sum",
                "source_candidate_match_count_sum",
                "confirmed_candidate_match_count_sum",
                "candidate_match_count_sum",
                "pending_count_sum",
            )
        )
        check("公司汇总", f"{company_short}公司级指标与逐经理回填勾稽", aligned, f"公司汇总匹配 {summary.get('match_count_sum')}；回填匹配 {metric.get('match_count_sum')}")

    confirmed_items = [row for data in company_data for row in data.get("confirmed_candidate_items", [])]
    invalid_candidates = [
        row
        for row in confirmed_items
        if row.get("score") != 30
        or row.get("confirmation_status") != "业务已确认"
        or row.get("original_confirmation_status") != "待确认"
        or row.get("match_type") != "研究分组候选覆盖"
    ]
    check(
        "业务口径",
        "候选确认不改变原始分数和匹配类型",
        len(confirmed_items) == int(backfill.get("confirmed_candidate_match_count_sum", -1)) and not invalid_candidates,
        f"已检查 {len(confirmed_items)} 条；违规 {len(invalid_candidates)} 条",
    )

    match_rows = [row for data in company_data for row in data.get("match_details", [])]
    privacy_violations = [row for row in match_rows if row.get("contact_permission") != "允许" and row.get("contact_info") != "已隐藏"]
    check("隐私", "非允许联系方式全部隐藏", not privacy_violations, f"检查 {len(match_rows)} 条匹配；违规 {len(privacy_violations)} 条")

    workbook_evidence = []
    for workbook in workbooks:
        audit = _audit_workbook(workbook)
        workbook_evidence.append({"path": str(workbook), **audit})
    check(
        "正式交付",
        "公司级 Excel 均可读取且结构完整",
        len(workbook_evidence) == len(company_rows)
        and len(workbook_evidence) > 0
        and all(row["valid"] and set(row["sheets"]) == EXPECTED_RESOURCE_SHEETS and not row["formula_errors"] for row in workbook_evidence),
        "；".join(f"{Path(row['path']).name}: {len(row['sheets'])}表, 公式错误{len(row['formula_errors'])}" for row in workbook_evidence),
    )

    runtime_hits = []
    for path in sorted((project_root / "src").rglob("*.py")):
        if path.name in {"acceptance.py", "llm_agent.py", "llm_agent_cli.py", "agent.py", "agent_cli.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if DEEPSEEK_RUNTIME_PATTERN.search(text):
            runtime_hits.append(str(path))
    check("模型边界", "确定性管道未接入 DeepSeek 运行时", not runtime_hits, "未发现 DeepSeek API 客户端、密钥或基础地址" if not runtime_hits else "命中：" + "；".join(runtime_hits))

    if test_result is not None:
        check("自动测试", "全量自动测试通过", bool(test_result.get("passed")), test_result.get("summary", "未提供测试摘要"))

    blocker_failures = [row for row in checks if row["status"] == "失败" and row["severity"] == "阻断"]
    caveats = [
        "申万行业当前采用公开可得快照，尚不是带纳入／剔除日期的报告期历史行业库。",
        "天天基金／东方财富属于外部公开数据源，页面或接口变化仍可能导致季度抓取失败；系统已通过缓存、重试、披露等待和异常清单控制风险。",
        "当前业务明确不处理港股研究资源需求；港股持仓只进入排除审计。",
        "研究分组候选的业务确认代表本项目对接口径，不等同于研究员对具体公司的法定或永久覆盖关系；人员库变化后应复核规则库。",
        "定时调度和外部通知不属于本次确定性管道验收；当前不向 Slack 等外部渠道发送结果。",
    ]
    payload = {
        "title": "基金持仓 Agent 第一阶段验收",
        "report_date": backfill.get("report_date"),
        "quarter": backfill.get("quarter"),
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "overall_status": "accepted_with_caveats" if not blocker_failures else "needs_revision",
        "confidence": "ready_for_first_phase_use" if not blocker_failures else "not_ready",
        "passed_check_count": sum(row["status"] == "通过" for row in checks),
        "failed_check_count": sum(row["status"] == "失败" for row in checks),
        "checks": checks,
        "metrics": {
            "manager_count": len(entries),
            "company_count": len(company_rows),
            "industry_demand_count_sum": int(backfill.get("industry_demand_count_sum", 0)),
            "company_demand_count_sum": int(backfill.get("company_demand_count_sum", 0)),
            "match_count_sum": int(backfill.get("match_count_sum", 0)),
            "confirmed_candidate_match_count_sum": int(backfill.get("confirmed_candidate_match_count_sum", 0)),
            "remaining_candidate_match_count_sum": int(backfill.get("candidate_match_count_sum", 0)),
            "pending_count_sum": int(backfill.get("pending_count_sum", 0)),
            "candidate_confirmation_relation_count": registry_rows,
            "excluded_non_sw_company_count_sum": int(backfill.get("excluded_non_sw_company_count_sum", 0)),
        },
        "company_metrics": backfill.get("company_metrics", []),
        "workbooks": workbook_evidence,
        "test_result": test_result or {"passed": None, "summary": "本次验收命令未运行测试"},
        "caveats": caveats,
        "recommended_next_step": "冻结第一阶段口径，使用现有缓存做一次新季度演练；披露窗口到来后再执行真实季度抓取。",
        "source_files": [
            _source_record(roster_path),
            _source_record(backfill_summary_path),
            _source_record(company_summary_path),
            _source_record(candidate_confirmation_path),
        ],
    }
    atomic_write_json(output_path, payload)
    payload["output_file"] = str(output_path.resolve())
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_record(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path) if path.exists() and path.is_file() else ""}


def _audit_workbook(path: Path) -> dict[str, Any]:
    if not path.exists() or not zipfile.is_zipfile(path):
        return {"valid": False, "sheets": [], "formula_errors": ["文件不存在或不是有效 XLSX"]}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        workbook_xml = archive.read("xl/workbook.xml")
        root = ElementTree.fromstring(workbook_xml)
        namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets = [node.attrib["name"] for node in root.findall("m:sheets/m:sheet", namespace)]
        formula_errors = []
        for name in names:
            if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                continue
            text = archive.read(name).decode("utf-8", errors="ignore")
            for error in FORMULA_ERRORS:
                if error in text:
                    formula_errors.append(f"{name}:{error}")
        return {"valid": True, "sheets": sheets, "formula_errors": formula_errors, "sha256": _sha256(path)}
