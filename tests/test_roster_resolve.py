from fund_holdings_agent.portfolio import normalize_company, resolve_manager_for_company


def test_normalize_company_ignores_legal_suffixes():
    assert normalize_company("广发基金管理有限公司") == normalize_company("广发基金") == "广发"


def test_resolver_filters_same_name_by_company():
    suggestion = 'var r = (["测试经理,CSJL,111","测试经理,CSJL,222"]);'
    profiles = {
        "https://fund.eastmoney.com/manager/111.html": """
          <div class='fundManger'><h3>测试经理基金经理</h3></div>
          <span>现任基金公司</span><a href='/company/1.html'>其他基金管理有限公司</a>
          <table><tr><th>基金代码</th><th>基金名称</th><th>基金类型</th><th>任职时间</th></tr>
          <tr><td>000001</td><td>测试A</td><td>混合型</td><td>2020-01-01 ~ 至今</td></tr></table>
        """,
        "https://fund.eastmoney.com/manager/222.html": """
          <div class='fundManger'><h3>测试经理基金经理</h3></div>
          <span>现任基金公司</span><a href='/company/2.html'>广发基金管理有限公司</a>
          <table><tr><th>基金代码</th><th>基金名称</th><th>基金类型</th><th>任职时间</th></tr>
          <tr><td>000002</td><td>测试B</td><td>混合型</td><td>2020-01-01 ~ 至今</td></tr></table>
        """,
    }

    def fetch(url):
        return suggestion if "FundDataPortfolio" in url else profiles[url]

    candidate, company = resolve_manager_for_company("测试经理", "广发基金", fetch)

    assert candidate.manager_id == "222"
    assert company == "广发基金管理有限公司"
