import csv
from pathlib import Path

from fund_holdings_agent.resource_matching import (
    Person,
    build_resource_matching,
    read_personnel_csv,
)


def _industry_data():
    return {
        "summary": {"report_date": "2026-03-31"},
        "industry_summary": [
            {
                "fund_code": "008274",
                "sw_level1": "电子",
                "holding_count": 4,
                "market_value_10k": 3000.0,
                "nav_ratio": 0.25,
            },
            {
                "fund_code": "014651",
                "sw_level1": "电子",
                "holding_count": 2,
                "market_value_10k": 1200.0,
                "nav_ratio": 0.12,
            },
            {
                "fund_code": "008274",
                "sw_level1": "电力设备",
                "holding_count": 1,
                "market_value_10k": 500.0,
                "nav_ratio": 0.03,
            },
        ],
        "formal_holdings_industry": [
            {
                "fund_code": "008274",
                "stock_code": "688072.SH",
                "stock_name": "拓荆科技",
                "sw_level1": "电子",
                "market_value_10k": 1000.0,
                "nav_ratio": 0.09,
            },
            {
                "fund_code": "014651",
                "stock_code": "688072.SH",
                "stock_name": "拓荆科技",
                "sw_level1": "电子",
                "market_value_10k": 800.0,
                "nav_ratio": 0.06,
            },
            {
                "fund_code": "008274",
                "stock_code": "300750.SZ",
                "stock_name": "宁德时代",
                "sw_level1": "电力设备",
                "market_value_10k": 500.0,
                "nav_ratio": 0.03,
            },
        ],
    }


def test_empty_personnel_template_is_valid(tmp_path: Path):
    path = tmp_path / "people.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "person_name",
                "organization",
                "person_type",
                "sw_level1",
                "covered_stock_codes",
                "expertise_tags",
                "region",
                "current_status",
                "contact_permission",
                "contact_info",
            ]
        )

    people, issues = read_personnel_csv(path)

    assert people == []
    assert issues == []


def test_empty_personnel_list_creates_all_pending_items():
    result = build_resource_matching(_industry_data(), [], [])

    assert len(result["industry_demands"]) == 2
    assert len(result["company_demands"]) == 2
    assert result["summary"]["pending_count"] == 4
    assert result["summary"]["status"] == "待提供内部人员库"


def test_exact_company_match_suppresses_broader_industry_candidates_and_hides_restricted_contact():
    people = [
        Person("甲", "内部", "研究员", ("电子",), (), "半导体", "上海", "在岗", "需审批", "secret-a"),
        Person("乙", "外部", "专家", ("电子",), ("688072.SH",), "设备", "北京", "在岗", "允许", "public-b"),
    ]

    result = build_resource_matching(_industry_data(), people, [])
    company_matches = [row for row in result["matches"] if row["target_code"] == "688072.SH"]

    assert [row["score"] for row in company_matches] == [100]
    assert company_matches[0]["person_name"] == "乙"
    assert company_matches[0]["contact_info"] == "public-b"


def test_invalid_personnel_enum_is_reported(tmp_path: Path):
    path = tmp_path / "people.csv"
    path.write_text(
        "person_name,organization,person_type,sw_level1,covered_stock_codes,expertise_tags,region,current_status,contact_permission,contact_info\n"
        "甲,内部,分析师,电子,,,上海,在岗,允许,123\n",
        encoding="utf-8-sig",
    )

    people, issues = read_personnel_csv(path)

    assert people == []
    assert issues[0]["category"] == "人员类型无效"


def test_person_without_sw_industry_is_retained_as_warning(tmp_path: Path):
    path = tmp_path / "people.csv"
    path.write_text(
        "person_name,organization,person_type,sw_level1,covered_stock_codes,expertise_tags,region,current_status,contact_permission,contact_info\n"
        "甲,内部,研究员,,,,上海,在岗,需审批,\n",
        encoding="utf-8-sig",
    )

    people, issues = read_personnel_csv(path)

    assert len(people) == 1
    assert people[0].sw_level1 == ()
    assert issues[0]["severity"] == "警告"
    assert issues[0]["category"] == "人员未映射申万行业"


def test_research_group_mapping_is_lower_confidence_than_manual_mapping():
    people = [
        Person(
            "甲",
            "示例券商研究所",
            "研究员",
            ("电子",),
            (),
            "电子",
            "上海",
            "在岗",
            "需审批",
            "",
            job_title="分析师",
            source_group="电子",
            coverage_basis="研究分组映射",
            industry_mapping_status="已映射",
        ),
        Person("乙", "内部", "研究员", ("电子",), (), "电子", "北京", "在岗", "需审批", ""),
    ]

    result = build_resource_matching(_industry_data(), people, [])
    matches = [row for row in result["matches"] if row["demand_type"] == "行业" and row["target_code"] == "电子"]

    assert [row["score"] for row in matches] == [50, 40]
    assert matches[1]["match_type"] == "研究分组覆盖"
    assert matches[1]["job_title"] == "分析师"
    assert matches[1]["confirmation_status"] == "组级推定"


def test_candidate_confirmation_registry_changes_status_but_keeps_score_and_match_type():
    people = [
        Person(
            "甲",
            "示例券商研究所",
            "研究员",
            ("电子",),
            (),
            "AI硬件",
            "上海",
            "在岗",
            "需审批",
            "",
            source_group="AI硬件",
            coverage_basis="研究分组映射",
            industry_mapping_status="候选映射",
        )
    ]
    confirmations = {
        ("行业", "电子", "甲", "示例券商研究所"): {
            "confirmed_by": "业务用户",
            "confirmed_at_beijing": "2026-08-15T15:13:10+08:00",
        },
        ("公司", "688072.SH", "甲", "示例券商研究所"): {
            "confirmed_by": "业务用户",
            "confirmed_at_beijing": "2026-08-15T15:13:10+08:00",
        },
    }

    result = build_resource_matching(_industry_data(), people, [], confirmations, [], "confirmations.csv")
    confirmed = [row for row in result["matches"] if row["confirmation_status"] == "业务已确认"]

    assert {(row["demand_type"], row["target_code"]) for row in confirmed} == {("行业", "电子"), ("公司", "688072.SH")}
    assert {row["score"] for row in confirmed} == {30}
    assert {row["match_type"] for row in confirmed} == {"研究分组候选覆盖"}
    assert result["summary"]["source_candidate_match_count"] == 2
    assert result["summary"]["confirmed_candidate_match_count"] == 2
    assert result["summary"]["candidate_match_count"] == 0
    assert result["summary"]["status"] == "匹配完成"


def test_non_applicable_sw_label_does_not_create_industry_demand():
    data = _industry_data()
    data["industry_summary"].append(
        {
            "fund_code": "008274",
            "sw_level1": "不适用",
            "holding_count": 1,
            "market_value_10k": 100.0,
            "nav_ratio": 0.01,
        }
    )
    data["formal_holdings_industry"].append(
        {
            "fund_code": "008274",
            "stock_code": "00700.HK",
            "stock_name": "腾讯控股",
            "sw_level1": "不适用",
            "market_value_10k": 100.0,
            "nav_ratio": 0.01,
        }
    )

    result = build_resource_matching(data, [], [])

    assert {row["sw_level1"] for row in result["industry_demands"]} == {"电子", "电力设备"}
    assert all(row["stock_code"] != "00700.HK" for row in result["company_demands"])
    excluded = next(row for row in result["excluded_demands"] if row["stock_code"] == "00700.HK")
    assert excluded["sw_level1"] == "不适用"
    assert result["summary"]["excluded_non_sw_company_count"] == 1


def test_sw_level2_routes_company_before_broad_level1_match():
    data = _industry_data()
    data["formal_holdings_industry"][0]["sw_level1"] = "石油石化"
    data["formal_holdings_industry"][0]["sw_level2"] = "油服工程"
    people = [
        Person("甲", "内部", "研究员", ("石油石化",), (), "石油", "上海", "在岗", "需审批", "", covered_sw_level2=("油服工程",)),
        Person("乙", "内部", "研究员", ("石油石化",), (), "石化", "上海", "在岗", "需审批", "", covered_sw_level2=("炼化及贸易",)),
    ]

    result = build_resource_matching(data, people, [])
    matches = [row for row in result["matches"] if row["target_code"] == "688072.SH"]

    assert [(row["person_name"], row["score"], row["match_type"]) for row in matches] == [("甲", 70, "申万二级覆盖")]
    assert matches[0]["sw_level2"] == "油服工程"
