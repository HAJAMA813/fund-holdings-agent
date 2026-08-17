from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .company_compare import build_company_comparison, save_company_comparison
from .portfolio import atomic_write_json, atomic_write_text, read_manager_roster
from .quarterly_cli import BEIJING_TIMEZONE, beijing_now, quarter_label


def build_preproduction_replay(
    project_root: Path,
    portfolio_root: Path,
    roster_path: Path,
    output_dir: Path,
    previous_report_date: str = "2026-03-31",
    current_report_date: str = "2026-06-30",
) -> dict[str, Any]:
    project_root = project_root.resolve()
    portfolio_root = portfolio_root.resolve()
    roster_path = roster_path.resolve()
    output_dir = output_dir.resolve()
    previous_quarter = quarter_label(_date(previous_report_date))
    current_quarter = quarter_label(_date(current_report_date))
    previous_summary_path = portfolio_root / f"portfolio_summary_{previous_quarter}.json"
    current_summary_path = portfolio_root / f"portfolio_summary_{current_quarter}.json"
    previous_summary = _read_json(previous_summary_path)
    current_summary = _read_json(current_summary_path)
    roster = read_manager_roster(roster_path)

    checks: list[dict[str, Any]] = []

    def check(check_id: str, name: str, passed: bool, actual: Any, expected: Any, note: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "check_name": name,
                "actual": actual,
                "expected": expected,
                "status": "OK" if passed else "FAIL",
                "note": note,
            }
        )

    check(
        "PR-01",
        "批次报告期",
        previous_summary.get("report_date") == previous_report_date and current_summary.get("report_date") == current_report_date,
        f"{previous_summary.get('report_date')} -> {current_summary.get('report_date')}",
        f"{previous_report_date} -> {current_report_date}",
        "只允许相邻自然季度回放",
    )

    roster_keys = {(row.company, row.manager) for row in roster}
    previous_results = _result_map(previous_summary)
    current_results = _result_map(current_summary)
    result_keys_match = set(previous_results) == roster_keys == set(current_results)
    check(
        "PR-02",
        "两期经理范围一致",
        result_keys_match and len(roster_keys) == 25,
        f"名单{len(roster_keys)}、上期{len(previous_results)}、本期{len(current_results)}",
        "三者均为25",
        "公司+经理为身份主键",
    )

    status_counts = Counter(
        [row.get("overall_status", "") for row in previous_results.values()]
        + [row.get("overall_status", "") for row in current_results.values()]
    )
    check(
        "PR-03",
        "50个季度任务全部完成",
        status_counts == Counter({"completed": 50}),
        dict(status_counts),
        {"completed": 50},
        "每位经理每季度一个任务",
    )

    manager_rows: list[dict[str, Any]] = []
    missing_comparisons: list[str] = []
    report_date_errors: list[str] = []
    pipeline_error_count = 0
    pipeline_warning_count = 0
    industry_error_count = 0
    industry_warning_count = 0
    for entry in roster:
        key = (entry.company, entry.manager)
        previous_result = previous_results[key]
        current_result = current_results[key]
        previous_dir = Path(str(previous_result["output_dir"]))
        current_dir = Path(str(current_result["output_dir"]))
        previous_pipeline = _read_json(previous_dir / "pipeline_data.json")["summary"]
        current_pipeline = _read_json(current_dir / "pipeline_data.json")["summary"]
        previous_industry = _read_json(previous_dir / "industry_analysis_data.json")["industry_quality"]
        current_industry = _read_json(current_dir / "industry_analysis_data.json")["industry_quality"]
        comparison_path = current_dir / "quarter_comparison_data.json"
        if comparison_path.exists():
            comparison = _read_json(comparison_path)["summary"]
        else:
            missing_comparisons.append(f"{entry.company}/{entry.manager}")
            comparison = {}
        if previous_pipeline.get("report_date") != previous_report_date or current_pipeline.get("report_date") != current_report_date:
            report_date_errors.append(f"{entry.company}/{entry.manager}")
        pipeline_error_count += int(previous_pipeline.get("error_count", 0)) + int(current_pipeline.get("error_count", 0))
        pipeline_warning_count += int(previous_pipeline.get("warning_count", 0)) + int(current_pipeline.get("warning_count", 0))
        industry_error_count += int(previous_industry.get("error_count", 0)) + int(current_industry.get("error_count", 0))
        industry_warning_count += int(previous_industry.get("warning_count", 0)) + int(current_industry.get("warning_count", 0))
        manager_rows.append(
            {
                "company": entry.company,
                "manager": entry.manager,
                "manager_id": entry.manager_id,
                "previous_status": previous_result.get("overall_status"),
                "current_status": current_result.get("overall_status"),
                "previous_formal_funds": int(previous_pipeline.get("formal_funds", 0)),
                "current_formal_funds": int(current_pipeline.get("formal_funds", 0)),
                "fund_change": int(current_pipeline.get("formal_funds", 0)) - int(previous_pipeline.get("formal_funds", 0)),
                "previous_holding_rows": int(previous_pipeline.get("formal_holding_rows", 0)),
                "current_holding_rows": int(current_pipeline.get("formal_holding_rows", 0)),
                "new_company_count": int(comparison.get("new_company_count", 0)),
                "exited_company_count": int(comparison.get("exited_company_count", 0)),
                "increased_company_count": int(comparison.get("increased_company_count", 0)),
                "decreased_company_count": int(comparison.get("decreased_company_count", 0)),
                "unchanged_company_count": int(comparison.get("unchanged_company_count", 0)),
                "comparison_status": comparison.get("status", "缺失"),
                "pipeline_warning_count": int(previous_pipeline.get("warning_count", 0)) + int(current_pipeline.get("warning_count", 0)),
                "industry_warning_count": int(previous_industry.get("warning_count", 0)) + int(current_industry.get("warning_count", 0)),
                "comparison_path": str(comparison_path.resolve()),
            }
        )

    check("PR-04", "逐经理报告期无串期", not report_date_errors, len(report_date_errors), 0, "异常：" + "；".join(report_date_errors) if report_date_errors else "50份管道摘要报告期正确")
    check("PR-05", "逐经理季度比较完整", not missing_comparisons, 25 - len(missing_comparisons), 25, "缺失：" + "；".join(missing_comparisons) if missing_comparisons else "25位经理均有相邻季度比较")
    check("PR-06", "管道与行业无错误", pipeline_error_count == 0 and industry_error_count == 0, f"管道{pipeline_error_count}、行业{industry_error_count}", "均为0", "警告单独保留，不与错误混淆")

    companies = sorted({entry.company for entry in roster})
    company_rows: list[dict[str, Any]] = []
    company_outputs: list[dict[str, str]] = []
    dedup_conflicts = 0
    company_previous_rows = 0
    company_current_rows = 0
    removed_previous_rows = 0
    removed_current_rows = 0
    for company in companies:
        comparison = build_company_comparison(previous_summary_path, current_summary_path, company)
        short_name = company.replace("管理有限公司", "").replace("管理股份有限公司", "")
        company_dir = output_dir / short_name
        data_path = save_company_comparison(comparison, company_dir / f"{short_name}_{previous_quarter}至{current_quarter}_持仓变化数据.json")
        workbook_path = company_dir / f"{short_name}_{previous_quarter}至{current_quarter}_持仓变化分析.xlsx"
        preview_dir = company_dir / "previews"
        summary = comparison["summary"]
        dedup_conflicts += int(summary.get("dedup_conflict_count", 0))
        company_previous_rows += int(summary["previous_holding_rows"])
        company_current_rows += int(summary["current_holding_rows"])
        removed_previous_rows += int(summary.get("previous_duplicate_rows_removed", 0))
        removed_current_rows += int(summary.get("current_duplicate_rows_removed", 0))
        company_rows.append(
            {
                "company": company,
                "previous_manager_count": int(summary["previous_manager_count"]),
                "current_manager_count": int(summary["current_manager_count"]),
                "previous_formal_funds": int(summary["previous_formal_funds"]),
                "current_formal_funds": int(summary["current_formal_funds"]),
                "previous_holding_rows": int(summary["previous_holding_rows"]),
                "current_holding_rows": int(summary["current_holding_rows"]),
                "previous_duplicate_rows_removed": int(summary["previous_duplicate_rows_removed"]),
                "current_duplicate_rows_removed": int(summary["current_duplicate_rows_removed"]),
                "company_union_count": int(summary["company_union_count"]),
                "new_company_count": int(summary["new_company_count"]),
                "exited_company_count": int(summary["exited_company_count"]),
                "increased_company_count": int(summary["increased_company_count"]),
                "decreased_company_count": int(summary["decreased_company_count"]),
                "unchanged_company_count": int(summary["unchanged_company_count"]),
                "industry_union_count": int(summary["industry_union_count"]),
                "industry_snapshot_date": summary["industry_snapshot_date"],
                "dedup_conflict_count": int(summary["dedup_conflict_count"]),
                "status": summary["status"],
            }
        )
        company_outputs.append({"company": company, "data_path": str(data_path), "workbook_path": str(workbook_path), "preview_dir": str(preview_dir)})

    check("PR-07", "公司共同管理去重无冲突", dedup_conflicts == 0, dedup_conflicts, 0, "重复披露排名、股数、市值、净值比例须一致")
    previous_individual_rows = int(previous_summary.get("metrics", {}).get("formal_holding_rows", 0))
    current_individual_rows = int(current_summary.get("metrics", {}).get("formal_holding_rows", 0))
    reconcile_ok = previous_individual_rows - removed_previous_rows == company_previous_rows and current_individual_rows - removed_current_rows == company_current_rows
    check(
        "PR-08",
        "公司去重持仓勾稽",
        reconcile_ok,
        f"上期{previous_individual_rows}-{removed_previous_rows}={company_previous_rows}；本期{current_individual_rows}-{removed_current_rows}={company_current_rows}",
        "左右相等",
        "逐经理正式持仓减去共同管理重复行等于公司层持仓",
    )
    previous_coverage = float(previous_summary.get("metrics", {}).get("global_a_industry_coverage", 0.0))
    current_coverage = float(current_summary.get("metrics", {}).get("global_a_industry_coverage", 0.0))
    check("PR-09", "两期A股申万一级覆盖率", previous_coverage == 1.0 and current_coverage == 1.0, f"{previous_coverage:.2%} / {current_coverage:.2%}", "100.00% / 100.00%", "当前快照覆盖，不冒充历史时点行业库")

    failed = [row for row in checks if row["status"] == "FAIL"]
    summary_path = output_dir / f"preproduction_replay_summary_{previous_quarter}_to_{current_quarter}.json"
    workbook_path = output_dir / f"基金持仓Agent_{previous_quarter}至{current_quarter}_准生产回放报告.xlsx"
    preview_dir = output_dir / "report_previews"
    receipt_path = output_dir / f"准生产回放运行摘要_{previous_quarter}至{current_quarter}.md"
    payload: dict[str, Any] = {
        "title": "基金持仓 Agent 相邻季度全量准生产回放",
        "previous_report_date": previous_report_date,
        "current_report_date": current_report_date,
        "previous_quarter": previous_quarter,
        "current_quarter": current_quarter,
        "timezone": BEIJING_TIMEZONE,
        "generated_at_beijing": beijing_now().isoformat(timespec="seconds"),
        "overall_status": "passed_with_limitations" if not failed else "needs_revision",
        "passed_check_count": sum(row["status"] == "OK" for row in checks),
        "failed_check_count": len(failed),
        "network_used": False,
        "deepseek_used": False,
        "metrics": {
            "manager_count": len(roster),
            "quarter_task_count": len(previous_results) + len(current_results),
            "manager_comparison_count": 25 - len(missing_comparisons),
            "previous_formal_product_count_individual_sum": int(previous_summary.get("metrics", {}).get("formal_product_count", 0)),
            "current_formal_product_count_individual_sum": int(current_summary.get("metrics", {}).get("formal_product_count", 0)),
            "previous_formal_holding_rows_individual_sum": previous_individual_rows,
            "current_formal_holding_rows_individual_sum": current_individual_rows,
            "previous_company_dedup_holding_rows": company_previous_rows,
            "current_company_dedup_holding_rows": company_current_rows,
            "previous_joint_management_duplicate_rows_removed": removed_previous_rows,
            "current_joint_management_duplicate_rows_removed": removed_current_rows,
            "pipeline_error_count": pipeline_error_count,
            "pipeline_warning_count": pipeline_warning_count,
            "industry_error_count": industry_error_count,
            "industry_warning_count": industry_warning_count,
            "previous_a_share_industry_coverage": previous_coverage,
            "current_a_share_industry_coverage": current_coverage,
        },
        "company_rows": company_rows,
        "manager_rows": manager_rows,
        "checks": checks,
        "limitations": [
            "两期申万行业均使用2026-08-14同一当前快照，可用于同口径方向比较，但不能证明报告期历史行业归属。",
            "公司级结果已消除名单内共同管理基金重复披露；逐经理结果仍用于经理视角，不可直接相加作为公司组合暴露。",
            "变化标签基于季度前十大持仓披露，不代表基金完整持仓交易流水。",
            "本次全部读取本地真实结果和缓存，不联网，也未调用DeepSeek或其他大模型。",
        ],
        "source_files": [
            _source_record(roster_path, "基金经理名单"),
            _source_record(previous_summary_path, "2026Q1批次摘要"),
            _source_record(current_summary_path, "2026Q2批次摘要"),
        ],
        "outputs": {
            "summary_json": str(summary_path),
            "summary_workbook": str(workbook_path),
            "summary_preview_dir": str(preview_dir),
            "receipt": str(receipt_path),
            "company_outputs": company_outputs,
        },
    }
    atomic_write_json(summary_path, payload)
    atomic_write_text(receipt_path, _receipt(payload))
    return payload


def _result_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row["company"]), str(row["manager"])): row for row in summary.get("manager_results", [])}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _date(value: str):
    import datetime as dt

    return dt.date.fromisoformat(value)


def _source_record(path: Path, item: str) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"item": item, "path": str(path.resolve()), "sha256": digest}


def _receipt(payload: dict[str, Any]) -> str:
    m = payload["metrics"]
    lines = [
        f"# {payload['previous_quarter']} → {payload['current_quarter']} 全量准生产回放",
        "",
        f"- 总体状态：{payload['overall_status']}",
        f"- 检查结果：{payload['passed_check_count']}项通过，{payload['failed_check_count']}项失败",
        f"- 经理范围：{m['manager_count']}人；季度任务：{m['quarter_task_count']}个；逐经理比较：{m['manager_comparison_count']}份",
        f"- 逐经理正式持仓：上期{m['previous_formal_holding_rows_individual_sum']}行，本期{m['current_formal_holding_rows_individual_sum']}行",
        f"- 公司去重正式持仓：上期{m['previous_company_dedup_holding_rows']}行，本期{m['current_company_dedup_holding_rows']}行",
        f"- 共同管理重复移除：上期{m['previous_joint_management_duplicate_rows_removed']}行，本期{m['current_joint_management_duplicate_rows_removed']}行",
        f"- 数据错误：管道{m['pipeline_error_count']}，行业{m['industry_error_count']}",
        f"- A股行业覆盖率：上期{m['previous_a_share_industry_coverage']:.2%}，本期{m['current_a_share_industry_coverage']:.2%}",
        "- 网络调用：无",
        "- DeepSeek调用：无",
        "",
        "## 已知限制",
        "",
        *[f"- {row}" for row in payload["limitations"]],
    ]
    return "\n".join(lines) + "\n"
