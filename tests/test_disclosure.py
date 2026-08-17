from fund_holdings_agent.disclosure import assess_disclosure


def _pipeline(*, second_status="已抓取", second_rows=True):
    rows = [
        {"fund_code": "000001", "report_date": "2026-03-31"},
        *([{"fund_code": "000002", "report_date": "2026-03-31"}] if second_rows else []),
    ]
    return {
        "summary": {"report_date": "2026-03-31"},
        "funds": [
            {"fund_code": "000001", "fund_name": "成长精选", "selected": True, "fetch_status": "已抓取"},
            {"fund_code": "000002", "fund_name": "价值优选", "selected": True, "fetch_status": second_status},
            {"fund_code": "000003", "fund_name": "已排除", "selected": False, "fetch_status": "已排除"},
        ],
        "all_holdings": rows,
        "issues": [] if second_rows else [{"fund_code": "000002", "category": "持仓为空"}],
    }


def test_all_selected_funds_must_have_target_quarter_holdings():
    result = assess_disclosure(_pipeline())

    assert result["summary"]["is_ready"] is True
    assert result["summary"]["ready_fund_count"] == 2
    assert result["summary"]["selected_fund_count"] == 2


def test_empty_selected_fund_is_waiting_and_retryable():
    result = assess_disclosure(_pipeline(second_status="无持仓/待核实", second_rows=False))
    pending = next(row for row in result["fund_readiness"] if row["fund_code"] == "000002")

    assert result["summary"]["is_ready"] is False
    assert result["summary"]["pending_fund_count"] == 1
    assert pending["readiness_status"] == "待披露"
    assert pending["retryable"] is True


def test_duplicate_share_without_holdings_does_not_block_ready_product():
    pipeline = _pipeline(second_status="无持仓/待核实", second_rows=False)
    pipeline["funds"][0]["fund_name"] = "测试混合A"
    pipeline["funds"][1]["fund_name"] = "测试混合C"
    result = assess_disclosure(pipeline)

    assert result["summary"]["selected_share_count"] == 2
    assert result["summary"]["selected_product_count"] == 1
    assert result["summary"]["is_ready"] is True
    duplicate = next(row for row in result["fund_readiness"] if row["fund_code"] == "000002")
    assert duplicate["gate_status"] == "份额重复不阻断"


def test_no_applicable_products_is_ready_with_explicit_status():
    result = assess_disclosure({"summary": {"report_date": "2026-03-31"}, "funds": [], "all_holdings": [], "issues": []})

    assert result["summary"]["is_ready"] is True
    assert result["summary"]["status"] == "无适用产品"
