from fund_holdings_agent.industry import parse_stock_sw_industry, parse_sw_level2_map


def test_parse_stock_sw_industry():
    page = '<span>所属申万行业：</span><span class="tip f14">半导体</span>'
    assert parse_stock_sw_industry(page) == "半导体"


def test_parse_sw_level2_map():
    page = """
    <div id="level2Items">
      <div class="lg-industries-item-chinese-title">801081.SI</div>
      <div class="lg-industries-item-number">半导体(180)<span>[电子]</span></div>
      <div class="lg-industries-item-chinese-title">801737.SI</div>
      <div class="lg-industries-item-number">电池(97)<span>[电力设备]</span></div>
    </div>
    """
    mapping = parse_sw_level2_map(page)
    assert mapping["半导体"] == {"sw_level1": "电子", "sw_level2_code": "801081.SI"}
    assert mapping["电池"]["sw_level1"] == "电力设备"
