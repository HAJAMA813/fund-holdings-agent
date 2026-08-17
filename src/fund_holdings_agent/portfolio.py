from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .manager_funds import MANAGER_PROFILE_URL, MANAGER_SUGGEST_URL, ManagerCandidate, parse_manager_profile, parse_manager_suggestions


@dataclass(frozen=True)
class ManagerEntry:
    company: str
    manager: str
    manager_id: str


def normalize_company(value: str) -> str:
    text = re.sub(r"\s+", "", value)
    for suffix in ("基金管理股份有限公司", "基金管理有限公司", "基金有限责任公司", "管理有限公司", "有限公司", "公司"):
        text = text.replace(suffix, "")
    return text.replace("基金", "")


def resolve_manager_for_company(
    manager: str,
    expected_company: str,
    fetch: Callable[[str], str],
) -> tuple[ManagerCandidate, str]:
    suggest_url = MANAGER_SUGGEST_URL.format(manager=quote(manager.strip()))
    candidates = [row for row in parse_manager_suggestions(fetch(suggest_url)) if row.name == manager.strip()]
    if not candidates:
        raise ValueError(f"天天基金未找到完全同名经理：{manager}")
    matches: list[tuple[ManagerCandidate, str]] = []
    observed: list[str] = []
    for candidate in candidates:
        profile_url = MANAGER_PROFILE_URL.format(manager_id=candidate.manager_id)
        profile_name, company, _ = parse_manager_profile(fetch(profile_url), candidate.manager_id)
        observed.append(f"{candidate.manager_id}:{profile_name or candidate.name}:{company or '公司未解析'}")
        if profile_name and profile_name != manager.strip():
            continue
        if normalize_company(company) == normalize_company(expected_company):
            matches.append((candidate, company))
    if len(matches) != 1:
        details = "；".join(observed)
        raise ValueError(f"{manager} 在 {expected_company} 的唯一匹配数={len(matches)}；候选={details}")
    return matches[0]


def write_manager_roster(path: Path, entries: list[ManagerEntry]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["company", "manager", "manager_id", "active"])
        writer.writeheader()
        for entry in entries:
            writer.writerow({"company": entry.company, "manager": entry.manager, "manager_id": entry.manager_id, "active": "yes"})
    temporary.replace(path)
    return path


def read_manager_roster(path: Path) -> list[ManagerEntry]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"company", "manager", "manager_id", "active"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"经理名单缺少字段：{','.join(sorted(missing))}")
        entries: list[ManagerEntry] = []
        seen_names: set[tuple[str, str]] = set()
        seen_ids: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            active = str(row.get("active", "")).strip().lower()
            if active in {"no", "false", "0", "否", "停用"}:
                continue
            company = str(row.get("company", "")).strip()
            manager = str(row.get("manager", "")).strip()
            manager_id = str(row.get("manager_id", "")).strip()
            if not company or not manager or not manager_id:
                raise ValueError(f"经理名单第 {row_number} 行存在空字段")
            if not manager_id.isdigit():
                raise ValueError(f"经理名单第 {row_number} 行 manager_id 不是数字")
            identity = (company, manager)
            if identity in seen_names or manager_id in seen_ids:
                raise ValueError(f"经理名单第 {row_number} 行存在重复姓名或 ID")
            entries.append(ManagerEntry(company, manager, manager_id))
            seen_names.add(identity)
            seen_ids.add(manager_id)
    if not entries:
        raise ValueError("经理名单没有启用记录")
    return entries


def company_directory_name(company: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", company.strip())
    for suffix in ("基金管理股份有限公司", "基金管理有限公司", "基金有限责任公司"):
        if value.endswith(suffix):
            return value[: -len(suffix)] + "基金"
    return value


def aggregate_portfolio_status(results: list[dict[str, Any]]) -> tuple[str, int]:
    statuses = {str(row.get("overall_status", "failed")) for row in results}
    if "failed" in statuses:
        return "failed", 1
    if "completed_with_errors" in statuses:
        return "completed_with_errors", 3
    if "waiting" in statuses:
        return "waiting", 2
    return "completed", 0


def portfolio_notification(company: str, report_date: str, results: list[dict[str, Any]]) -> str:
    completed = sum(row.get("overall_status") == "completed" for row in results)
    waiting = sum(row.get("overall_status") == "waiting" for row in results)
    attention = sum(row.get("overall_status") in {"failed", "completed_with_errors"} for row in results)
    details = "；".join(f"{row['manager']}={row['overall_status']}" for row in results)
    return (
        f"{company} {report_date}：共 {len(results)} 位经理，完成 {completed}，"
        f"等待披露 {waiting}，需核查 {attention}。{details}"
    )


def portfolio_run_receipt(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    results = payload.get("manager_results", [])
    reports = payload.get("company_reports", [])
    status = str(payload.get("overall_status", "failed"))
    next_action = {
        "completed": "本季度任务已完成，无需人工处理；等待下一季度。",
        "waiting": "公开披露尚未完整；下一检查窗口自动刷新并从持仓阶段续跑。",
        "completed_with_errors": "任务已完成但存在业务异常；查看异常清单，下一检查窗口使用业务错误重试。",
        "failed": "存在技术失败；保留现场并从失败阶段续跑。",
    }.get(status, "检查机器可读摘要中的状态和异常。")
    attention = [
        row for row in results if row.get("overall_status") in {"waiting", "completed_with_errors", "failed"}
    ]
    lines = [
        "基金持仓季度任务运行回执",
        f"运行时区：{payload.get('timezone', 'Asia/Shanghai')}",
        f"生成时间：{payload.get('generated_at_beijing', '')}",
        f"检查日期：{payload.get('as_of', '')}",
        f"目标报告期：{payload.get('report_date', '')}",
        f"总体状态：{status}",
        f"退出码：{payload.get('exit_code', 1)}",
        "",
        "运行结果",
        str(payload.get("notification_summary", "")),
        f"正式基金数：{metrics.get('formal_product_count', 0)}",
        f"正式持仓行数：{metrics.get('formal_holding_rows', 0)}",
        f"管道错误数：{metrics.get('pipeline_error_count', 0)}",
        f"行业映射覆盖率：{float(metrics.get('global_a_industry_coverage', 0.0)):.2%}",
        "",
        "公司正式报告",
    ]
    if reports:
        lines.extend(
            f"- {row.get('company', '')}：{row.get('status', '')}；{row.get('output_path', '')}" for row in reports
        )
    else:
        lines.append("- 本次未生成公司正式报告。")
    lines.extend(["", "待处理项"])
    if attention:
        lines.extend(
            f"- {row.get('company', '')}/{row.get('manager', '')}：{row.get('overall_status', '')}；{row.get('notification_summary', '')}"
            for row in attention
        )
    else:
        lines.append("- 无。")
    lines.extend(["", f"下一步：{next_action}", "模型调用：未调用 DeepSeek 或其他大模型。"])
    return "\n".join(lines) + "\n"


def aggregate_portfolio_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    exclusion_shares: Counter[str] = Counter()
    exclusion_products: dict[str, set[tuple[str, str]]] = {}
    managers_without_products: list[str] = []
    global_stocks: set[str] = set()
    global_a_stocks: set[str] = set()
    global_a_mapped: set[str] = set()
    loaded_managers = 0

    for result in results:
        output_dir = Path(str(result.get("output_dir", "")))
        pool_path = output_dir / "manager_fund_pool_data.json"
        pipeline_path = output_dir / "pipeline_data.json"
        industry_path = output_dir / "industry_analysis_data.json"
        if not (pool_path.exists() and pipeline_path.exists() and industry_path.exists()):
            continue
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        industry = json.loads(industry_path.read_text(encoding="utf-8"))
        loaded_managers += 1

        pool_summary = pool.get("summary", {})
        pipeline_summary = pipeline.get("summary", {})
        quality = industry.get("industry_quality", {})
        totals.update(
            {
                "historical_share_count": int(pool_summary.get("historical_share_count", 0)),
                "active_share_count": int(pool_summary.get("active_share_count", 0)),
                "selected_share_count": int(pool_summary.get("selected_share_count", 0)),
                "selected_product_count": int(pool_summary.get("product_count", 0)),
                "successful_share_count": int(pipeline_summary.get("successful_funds", 0)),
                "formal_product_count": int(pipeline_summary.get("formal_funds", 0)),
                "raw_holding_rows": int(pipeline_summary.get("raw_holding_rows", 0)),
                "formal_holding_rows": int(pipeline_summary.get("formal_holding_rows", 0)),
                "pipeline_error_count": int(pipeline_summary.get("error_count", 0)),
                "pipeline_warning_count": int(pipeline_summary.get("warning_count", 0)),
                "industry_error_count": int(quality.get("error_count", 0)),
                "industry_warning_count": int(quality.get("warning_count", 0)),
            }
        )
        if int(pool_summary.get("selected_share_count", 0)) == 0:
            managers_without_products.append(str(pool_summary.get("manager") or result.get("manager", "")))

        for row in pool.get("all_tenures", []):
            if not row.get("active_on_report_date") or row.get("selected"):
                continue
            reason = str(row.get("selection_reason", "未分类"))
            exclusion_shares[reason] += 1
            product = str(row.get("product_base_name") or row.get("fund_code", ""))
            exclusion_products.setdefault(reason, set()).add((str(row.get("manager", "")), product))

        for row in industry.get("stock_industry_mapping", []):
            code = str(row.get("stock_code", ""))
            if not code:
                continue
            global_stocks.add(code)
            if row.get("market") == "A股":
                global_a_stocks.add(code)
                if row.get("classification_status") == "当前快照已匹配":
                    global_a_mapped.add(code)

    return {
        "loaded_manager_count": loaded_managers,
        **dict(totals),
        "managers_with_applicable_products": loaded_managers - len(managers_without_products),
        "managers_without_applicable_products": managers_without_products,
        "global_unique_stock_count": len(global_stocks),
        "global_unique_a_stock_count": len(global_a_stocks),
        "global_unique_a_stock_mapped": len(global_a_mapped),
        "global_a_industry_coverage": len(global_a_mapped) / len(global_a_stocks) if global_a_stocks else 1.0,
        "exclusions": [
            {
                "reason": reason,
                "share_count": count,
                "product_count": len(exclusion_products.get(reason, set())),
            }
            for reason, count in sorted(exclusion_shares.items())
        ],
    }


def atomic_write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def atomic_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return path
