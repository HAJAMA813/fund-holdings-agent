from __future__ import annotations

import csv
import json
import posixpath
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree

from .io import clean_text
from .resource_matching import OPTIONAL_PERSONNEL_COLUMNS, PERSONNEL_COLUMNS, read_personnel_csv


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

SW_LEVEL1_2021 = (
    "农林牧渔",
    "基础化工",
    "钢铁",
    "有色金属",
    "电子",
    "家用电器",
    "食品饮料",
    "纺织服饰",
    "轻工制造",
    "医药生物",
    "公用事业",
    "交通运输",
    "房地产",
    "商贸零售",
    "社会服务",
    "综合",
    "建筑材料",
    "建筑装饰",
    "电力设备",
    "国防军工",
    "计算机",
    "传媒",
    "通信",
    "银行",
    "非银金融",
    "汽车",
    "机械设备",
    "煤炭",
    "石油石化",
    "环保",
    "美容护理",
)


@dataclass(frozen=True)
class TeamMapping:
    industries: tuple[str, ...]
    status: str
    note: str


TEAM_MAPPINGS: dict[str, TeamMapping] = {
    "研究所管理层": TeamMapping((), "未映射", "管理岗位不直接对应申万一级行业"),
    "固定收益": TeamMapping((), "未映射", "固定收益研究不直接对应股票申万一级行业"),
    "银行": TeamMapping(("银行",), "已映射", "研究分组与申万一级行业直接对应"),
    "非银": TeamMapping(("非银金融",), "已映射", "研究分组与申万一级行业直接对应"),
    "金融工程": TeamMapping((), "未映射", "金融工程研究不直接对应单一申万一级行业"),
    "宏观经济": TeamMapping((), "未映射", "宏观研究不直接对应单一申万一级行业"),
    "公用环保": TeamMapping(("公用事业", "环保"), "组合映射", "公用事业和环保为研究分组覆盖"),
    "电力设备新能源": TeamMapping(("电力设备",), "已映射", "新能源研究并入申万一级电力设备"),
    "医药": TeamMapping(("医药生物",), "已映射", "研究分组与申万一级行业直接对应"),
    "海外研究": TeamMapping((), "未映射", "海外研究需按公司或市场另行维护"),
    "机械/建筑建材": TeamMapping(("机械设备", "建筑材料", "建筑装饰"), "组合映射", "一个研究分组覆盖三个申万一级行业"),
    "金属新材料": TeamMapping(("有色金属", "钢铁"), "组合映射", "按金属研究分组映射，具体个人覆盖仍需确认"),
    "新消费": TeamMapping(("商贸零售", "社会服务", "纺织服饰", "轻工制造", "美容护理"), "候选映射", "分组范围宽，具体个人行业需人工确认"),
    "交运": TeamMapping(("交通运输",), "已映射", "研究分组与申万一级行业直接对应"),
    "传媒互联网": TeamMapping(("传媒",), "候选映射", "互联网公司可能跨传媒、计算机或通信，需人工确认"),
    "北交所": TeamMapping((), "未映射", "市场板块不是申万一级行业"),
    "农业": TeamMapping(("农林牧渔",), "已映射", "研究分组与申万一级行业直接对应"),
    "计算机": TeamMapping(("计算机",), "已映射", "研究分组与申万一级行业直接对应"),
    "AI硬件": TeamMapping(("电子", "通信"), "候选映射", "主题分组跨行业，具体个人覆盖需人工确认"),
    "电子": TeamMapping(("电子",), "已映射", "研究分组与申万一级行业直接对应"),
    "地产": TeamMapping(("房地产",), "已映射", "研究分组与申万一级行业直接对应"),
    "汽车": TeamMapping(("汽车",), "已映射", "研究分组与申万一级行业直接对应"),
    "家电": TeamMapping(("家用电器",), "已映射", "研究分组与申万一级行业直接对应"),
    "食品饮料": TeamMapping(("食品饮料",), "已映射", "研究分组与申万一级行业直接对应"),
    "基础化工": TeamMapping(("基础化工",), "已映射", "研究分组与申万一级行业直接对应"),
    "商业航天": TeamMapping(("国防军工",), "候选映射", "主题分组暂映射国防军工，需人工确认"),
    "产业研究院": TeamMapping((), "未映射", "产业研究院需按个人研究方向另行维护"),
}

EXCLUDED_SUPPORT_SECTIONS = {
    "华东销售",
    "华北销售",
    "华南销售",
    "运营部",
    "业务协同部",
    "合规质控部",
}


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[list[str]]:
    """Read cell text from one XLSX worksheet without Excel-specific runtime dependencies."""
    with zipfile.ZipFile(path) as archive:
        workbook = etree.fromstring(archive.read("xl/workbook.xml"))
        relationships = etree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            rel.get("Id"): rel.get("Target", "")
            for rel in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        sheet_target = ""
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            if sheet.get("name") == sheet_name:
                sheet_target = targets.get(sheet.get(f"{{{DOC_REL_NS}}}id"), "")
                break
        if not sheet_target:
            available = [sheet.get("name", "") for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet")]
            raise ValueError(f"工作簿中找不到工作表 {sheet_name!r}；可用工作表：{', '.join(available)}")
        target_path = sheet_target.lstrip("/")
        if not target_path.startswith("xl/"):
            target_path = posixpath.normpath(posixpath.join("xl", target_path))
        shared_strings = _read_shared_strings(archive)
        worksheet = etree.fromstring(archive.read(target_path))
        rows: list[list[str]] = []
        for row in worksheet.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
            values: dict[int, str] = {}
            for cell in row.findall(f"{{{MAIN_NS}}}c"):
                reference = cell.get("r", "")
                column = _column_index(reference)
                values[column] = _cell_text(cell, shared_strings)
            width = max(values, default=-1) + 1
            rows.append([values.get(index, "") for index in range(width)])
        return rows


def import_research_directory(
    input_path: Path,
    output_path: Path,
    *,
    sheet_name: str = "研究所通讯录",
    organization: str,
    source_date: str = "2026-06-16",
    include_contact: bool = False,
    email_domain: str | None = None,
    manual_overrides_path: Path | None = None,
) -> dict[str, object]:
    raw_rows = read_xlsx_sheet(input_path, sheet_name)
    header_index, columns = _find_header(raw_rows)
    current_section = "研究所管理层"
    imported: list[dict[str, str]] = []
    excluded_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    legacy_email_domain_count = 0
    normalized_email_whitespace_count = 0

    for row_no, raw_row in enumerate(raw_rows[header_index + 1 :], start=header_index + 2):
        name = clean_text(_at(raw_row, columns["姓名"]))
        title = clean_text(_at(raw_row, columns["职务"]))
        mobile = clean_text(_at(raw_row, columns["移动电话"]))
        raw_email = _at(raw_row, columns["公司电邮"])
        email = clean_text(raw_email)
        region = clean_text(_at(raw_row, columns["所在区域"]))
        if name and not any((title, mobile, email, region)):
            current_section = name
            continue
        if not name:
            continue
        if current_section in EXCLUDED_SUPPORT_SECTIONS:
            excluded_counts[current_section] += 1
            continue
        if clean_text(raw_email) != str(raw_email):
            normalized_email_whitespace_count += 1
        if email_domain and email and not email.lower().endswith("@" + email_domain.strip("@").lower()):
            legacy_email_domain_count += 1

        mapping = TEAM_MAPPINGS.get(current_section, TeamMapping((), "未映射", "未知研究分组，需人工维护"))
        group_counts[current_section] += 1
        contact_info = ""
        if include_contact:
            parts = [value for value in (f"电话：{mobile}" if mobile else "", f"邮箱：{email}" if email else "") if value]
            contact_info = "；".join(parts)
        imported.append(
            {
                "person_name": name,
                "organization": organization,
                "person_type": "研究员",
                "sw_level1": "；".join(mapping.industries),
                "covered_stock_codes": "",
                "expertise_tags": current_section,
                "region": region,
                "current_status": "在岗",
                "contact_permission": "需审批",
                "contact_info": contact_info,
                "job_title": title,
                "source_group": current_section,
                "source_date": source_date,
                "covered_sw_level2": "",
                "coverage_basis": "研究分组映射",
                "industry_mapping_status": mapping.status,
                "mapping_note": mapping.note,
                "status_basis": f"{source_date} 通讯录在列",
                "source_row": str(row_no),
            }
        )

    override_summary = _apply_manual_overrides(imported, manual_overrides_path)
    mapping_counts = Counter(row["industry_mapping_status"] or "未填写" for row in imported)

    duplicate_keys = [key for key, count in Counter((row["person_name"], row["organization"]) for row in imported).items() if count > 1]
    if duplicate_keys:
        names = "、".join(name for name, _ in duplicate_keys)
        raise ValueError(f"通讯录存在重复姓名+机构：{names}")

    fieldnames = [*PERSONNEL_COLUMNS, *OPTIONAL_PERSONNEL_COLUMNS]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(imported)
    temp_path.replace(output_path)

    people, validation_issues = read_personnel_csv(output_path)
    validation_errors = [issue for issue in validation_issues if issue["severity"] == "错误"]
    if validation_errors:
        raise ValueError(f"标准人员库校验失败：{validation_errors[0]['message']}")

    covered_industries = sorted({industry for person in people for industry in person.sw_level1})
    confirmed_industries = sorted(
        {
            industry
            for row in imported
            if row["industry_mapping_status"] in {"已映射", "组合映射", "已确认"}
            for industry in row["sw_level1"].split("；")
            if industry
        }
    )
    candidate_industries = sorted(set(covered_industries) - set(confirmed_industries))
    summary: dict[str, object] = {
        "source_file": str(input_path.resolve()),
        "source_sheet": sheet_name,
        "source_date": source_date,
        "organization": organization,
        "output_file": str(output_path.resolve()),
        "imported_personnel_count": len(imported),
        "excluded_support_personnel_count": sum(excluded_counts.values()),
        "excluded_support_group_counts": dict(sorted(excluded_counts.items())),
        "research_group_counts": dict(group_counts),
        "mapping_status_counts": dict(mapping_counts),
        "sw_level1_covered_count": len(covered_industries),
        "sw_level1_confirmed_count": len(confirmed_industries),
        "sw_level1_candidate_count": len(candidate_industries),
        "sw_level1_covered": covered_industries,
        "sw_level1_candidate": candidate_industries,
        "sw_level1_uncovered": sorted(set(SW_LEVEL1_2021) - set(covered_industries)),
        "personnel_validation_error_count": len(validation_errors),
        "personnel_validation_warning_count": sum(issue["severity"] == "警告" for issue in validation_issues),
        "legacy_email_domain_count": legacy_email_domain_count,
        "normalized_email_whitespace_count": normalized_email_whitespace_count,
        "contact_data_included": include_contact,
        "manual_overrides_file": str(manual_overrides_path.resolve()) if manual_overrides_path else "",
        **override_summary,
        "contact_policy": "默认不复制电话和邮箱；联系权限设为需审批，正式报告隐藏联系方式",
        "status_assumption": f"通讯录在列人员暂记为在岗，依据日期为 {source_date}；后续应由人员库维护者确认",
        "matching_policy": "通讯录人员按研究分组映射申万一级行业；人工覆盖表可补充用户确认的申万二级行业和具体公司，未确认人员仍只按组级候选处理",
    }
    return summary


def save_import_summary(summary: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return path


def _apply_manual_overrides(imported: list[dict[str, str]], path: Path | None) -> dict[str, int]:
    if path is None:
        return {"manual_override_count": 0, "manual_added_count": 0, "manual_updated_count": 0}
    by_key = {(row["person_name"], row["organization"]): row for row in imported}
    added = 0
    updated = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"person_name", "organization"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"人工覆盖表缺少列：{', '.join(sorted(missing))}")
        for row_no, raw in enumerate(reader, start=2):
            name = clean_text(raw.get("person_name"))
            organization = clean_text(raw.get("organization"))
            if not name or not organization:
                raise ValueError(f"人工覆盖表第 {row_no} 行缺少姓名或机构")
            key = (name, organization)
            target = by_key.get(key)
            if target is None:
                target = {column: "" for column in [*PERSONNEL_COLUMNS, *OPTIONAL_PERSONNEL_COLUMNS]}
                target.update(
                    {
                        "person_name": name,
                        "organization": organization,
                        "person_type": clean_text(raw.get("person_type")) or "研究员",
                        "current_status": clean_text(raw.get("current_status")) or "在岗",
                        "contact_permission": clean_text(raw.get("contact_permission")) or "需审批",
                        "coverage_basis": clean_text(raw.get("coverage_basis")) or "用户确认",
                        "industry_mapping_status": clean_text(raw.get("industry_mapping_status")) or "已确认",
                        "source_row": f"manual:{row_no}",
                    }
                )
                imported.append(target)
                by_key[key] = target
                added += 1
            else:
                updated += 1
            for field in ("sw_level1", "covered_stock_codes", "covered_sw_level2", "expertise_tags"):
                target[field] = _merge_delimited(target.get(field, ""), raw.get(field, ""))
            for field in (
                "person_type",
                "region",
                "current_status",
                "contact_permission",
                "contact_info",
                "job_title",
                "source_group",
                "source_date",
                "coverage_basis",
                "industry_mapping_status",
                "status_basis",
            ):
                value = clean_text(raw.get(field))
                if value:
                    target[field] = value
            target["mapping_note"] = _merge_delimited(target.get("mapping_note", ""), raw.get("mapping_note", ""))
    return {"manual_override_count": added + updated, "manual_added_count": added, "manual_updated_count": updated}


def _merge_delimited(left: object, right: object) -> str:
    parts: list[str] = []
    for value in (left, right):
        parts.extend(part for part in re.split(r"[,，、;；]+", clean_text(value)) if part)
    return "；".join(dict.fromkeys(parts))


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = etree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")) for item in root.findall(f"{{{MAIN_NS}}}si")]


def _cell_text(cell: etree._Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
    value = cell.find(f"{{{MAIN_NS}}}v")
    text = "" if value is None or value.text is None else value.text
    if cell_type == "s" and text:
        return shared_strings[int(text)]
    if cell_type == "b":
        return "TRUE" if text == "1" else "FALSE"
    return text


def _column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if not match:
        raise ValueError(f"无效的 Excel 单元格引用：{reference}")
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def _find_header(rows: Iterable[list[str]]) -> tuple[int, dict[str, int]]:
    required = {"姓名", "职务", "移动电话", "公司电邮", "所在区域"}
    for row_index, row in enumerate(rows):
        normalized = {re.sub(r"\s+", "", clean_text(value)): index for index, value in enumerate(row)}
        if required <= set(normalized):
            return row_index, {name: normalized[name] for name in required}
    raise ValueError("通讯录中找不到姓名、职务、移动电话、公司电邮、所在区域表头")


def _at(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""
