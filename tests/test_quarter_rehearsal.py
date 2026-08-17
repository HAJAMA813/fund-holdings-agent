import json
from pathlib import Path

from fund_holdings_agent.quarter_rehearsal import run_quarter_rehearsal


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    data = project / "data"
    data.mkdir(parents=True)
    roster = data / "managers_portfolio.csv"
    roster.write_text(
        "company,manager,manager_id,active\n" + "\n".join(
            [
                *(f"长安基金管理有限公司,长安{i},{1000 + i},yes" for i in range(5)),
                *(f"广发基金管理有限公司,广发{i},{2000 + i},yes" for i in range(20)),
            ]
        ),
        encoding="utf-8",
    )
    personnel = data / "personnel_internal_20260616.csv"
    header = (
        "person_name,organization,person_type,sw_level1,covered_stock_codes,expertise_tags,region,"
        "current_status,contact_permission,contact_info,coverage_basis,industry_mapping_status\n"
    )
    rows = [
        "示例研究员,示例券商研究所,研究员,电子,,电子,上海,在岗,需审批,,研究分组映射,候选映射",
        *(f"测试{i},示例券商研究所,研究员,电子,,电子,上海,在岗,需审批,,人工维护,已确认" for i in range(4)),
    ]
    personnel.write_text(header + "\n".join(rows), encoding="utf-8")
    confirmations = data / "resource_candidate_confirmations.csv"
    confirmations.write_text(
        "demand_type,target_code,target_name,person_name,organization,decision,confirmed_by,confirmed_at_beijing,"
        "source_report_date,source_companies,source_managers,source_candidate_snapshot_sha256,original_score,match_type\n"
        + "\n".join(
            [
                "公司,000100.SZ,TCL科技,示例研究员,示例券商研究所,已确认,测试,2026-08-15T00:00:00+08:00,"
                "2026-06-30,广发基金管理有限公司,测试经理,abc,30,研究分组候选覆盖",
                *(f"公司,{i:06d}.SZ,测试{i},测试{i},示例券商研究所,已确认,测试,2026-08-15T00:00:00+08:00,2026-06-30,广发基金管理有限公司,测试经理,abc,30,研究分组候选覆盖" for i in range(1, 5)),
            ]
        ),
        encoding="utf-8",
    )
    return project, roster, personnel, confirmations


def test_offline_quarter_rehearsal_passes_all_controls(tmp_path: Path):
    project, roster, personnel, confirmations = _write_inputs(tmp_path)
    output = project / "outputs" / "rehearsal"

    result = run_quarter_rehearsal(project, output, roster, personnel, confirmations)

    assert result["overall_status"] == "passed"
    assert result["passed_check_count"] == 9
    assert result["failed_check_count"] == 0
    assert result["network_used"] is False
    assert result["deepseek_used"] is False
    assert result["simulated_runs"]["first_run"]["overall_status"] == "waiting"
    assert result["simulated_runs"]["second_run"]["stage_attempts"]["fund_pool"] == 1
    assert result["simulated_runs"]["second_run"]["stage_attempts"]["holdings"] == 2
    assert Path(result["outputs"]["checklist"]).exists()
    saved = json.loads(Path(result["outputs"]["summary"]).read_text(encoding="utf-8"))
    assert saved["overall_status"] == "passed"
