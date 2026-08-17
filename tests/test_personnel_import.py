import csv
import zipfile
from pathlib import Path

from fund_holdings_agent.personnel_import import import_research_directory, save_import_summary


def _xlsx(path: Path) -> None:
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="研究所通讯录" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    rows = [
        ["", "示例券商研究所通讯录"],
        ["", "姓 名", "职务", "移动电话", "公司电邮", "所在区域"],
        ["", "甲", "研究所所长", "13000000000", "a@example-broker.com", "上海"],
        ["", "银行"],
        ["", "乙", "分析师", "13100000000", "b@example-broker.com", "北京"],
        ["", "新消费"],
        ["", "丙", "研究员", "13200000000", " c@other-broker.com ", "深圳"],
        ["", "华东销售"],
        ["", "丁", "销售经理", "13300000000", "d@example-broker.com", "上海"],
    ]
    xml_rows = []
    for row_no, row in enumerate(rows, start=1):
        cells = []
        for col_no, value in enumerate(row, start=1):
            if not value:
                continue
            ref = f"{chr(64 + col_no)}{row_no}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{value}</t></is></c>')
        xml_rows.append(f'<row r="{row_no}">{"".join(cells)}</row>')
    worksheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{''.join(xml_rows)}</sheetData>
</worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def test_import_research_directory_excludes_support_and_omits_contact_by_default(tmp_path: Path):
    source = tmp_path / "contacts.xlsx"
    output = tmp_path / "personnel.csv"
    _xlsx(source)

    summary = import_research_directory(
        source, output, organization="示例券商研究所", email_domain="example-broker.com", source_date="2026-06-16"
    )

    assert summary["imported_personnel_count"] == 3
    assert summary["excluded_support_personnel_count"] == 1
    assert summary["sw_level1_covered"] == ["商贸零售", "社会服务", "纺织服饰", "美容护理", "轻工制造", "银行"]
    assert summary["legacy_email_domain_count"] == 1
    assert summary["normalized_email_whitespace_count"] == 1
    assert summary["contact_data_included"] is False
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["person_name"] for row in rows] == ["甲", "乙", "丙"]
    assert rows[0]["sw_level1"] == ""
    assert rows[1]["sw_level1"] == "银行"
    assert rows[2]["industry_mapping_status"] == "候选映射"
    assert all(row["contact_permission"] == "需审批" for row in rows)
    assert all(row["contact_info"] == "" for row in rows)


def test_import_can_include_controlled_contact_and_save_summary(tmp_path: Path):
    source = tmp_path / "contacts.xlsx"
    output = tmp_path / "personnel.csv"
    summary_path = tmp_path / "summary.json"
    _xlsx(source)

    summary = import_research_directory(source, output, organization="示例券商研究所", include_contact=True)
    saved = save_import_summary(summary, summary_path)

    assert saved == summary_path
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "电话：" in rows[1]["contact_info"]
    assert "邮箱：" in rows[1]["contact_info"]


def test_manual_overrides_can_add_and_update_people(tmp_path: Path):
    source = tmp_path / "contacts.xlsx"
    output = tmp_path / "personnel.csv"
    overrides = tmp_path / "overrides.csv"
    _xlsx(source)
    overrides.write_text(
        "person_name,organization,person_type,sw_level1,covered_stock_codes,covered_sw_level2,expertise_tags,current_status,contact_permission,source_date,coverage_basis,industry_mapping_status,mapping_note,status_basis\n"
        "乙,示例券商研究所,研究员,石油石化,,炼化及贸易,石化,在岗,需审批,2026-08-15,用户确认,已确认,用户确认,用户确认\n"
        "戊,示例券商研究所,研究员,石油石化,300164.SZ,油服工程,石油,在岗,需审批,2026-08-15,用户确认,已确认,用户确认,用户确认\n",
        encoding="utf-8-sig",
    )

    summary = import_research_directory(source, output, organization="示例券商研究所", manual_overrides_path=overrides)

    assert summary["manual_override_count"] == 2
    assert summary["manual_added_count"] == 1
    assert summary["manual_updated_count"] == 1
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {row["person_name"]: row for row in csv.DictReader(handle)}
    assert rows["乙"]["sw_level1"] == "银行；石油石化"
    assert rows["乙"]["covered_sw_level2"] == "炼化及贸易"
    assert rows["戊"]["covered_stock_codes"] == "300164.SZ"
