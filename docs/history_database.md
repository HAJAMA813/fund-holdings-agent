# SQLite 历史数据库

## 目标

历史库保存每个报告期可审计的基金、持仓、行业分类、异常和相邻季度比较结果。写入以“基金经理 + 报告期”以及“基金经理 + 上期 + 本期”为唯一键，同一批结果重复执行时更新原记录，不新增重复季度。

## 核心表

- `quarter_runs`：季度运行状态、数据质量指标、来源文件路径和 SHA-256。
- `funds`：报告期基金池和抓取状态。
- `holdings`：所有原始基金份额的持仓；`representative='是'` 为去重后正式口径。
- `run_issues`：持仓抓取、经理核验和份额去重异常。
- `stock_industry`：每期唯一股票的行业快照。
- `holding_industries`：持仓行与行业结果的关联。
- `industry_summary`：基金与申万一级行业汇总。
- `industry_issues`：行业匹配异常和时点限制。
- `comparisons`：相邻季度比较运行状态。
- `company_changes`：基金经理公司层变化。
- `fund_stock_changes`：单基金股票变化。
- `industry_changes`：申万一级行业变化。
- `comparison_checks`、`comparison_rules`、`comparison_sources`：比较的质量检查、口径和来源。

## 视图

- `v_formal_holdings`：只读取去重后的正式持仓，并附带基金经理和报告期。
- `v_company_changes`：公司变化记录，并附带基金经理和比较区间。

## 写入命令

```bash
PYTHONPATH=src python -m fund_holdings_agent.history_cli ingest-quarter \
  --db outputs/history.sqlite \
  --pipeline outputs/2026Q1/pipeline_data.json \
  --industry outputs/2026Q1/industry_analysis_data.json

PYTHONPATH=src python -m fund_holdings_agent.history_cli ingest-comparison \
  --db outputs/history.sqlite \
  --comparison outputs/comparison/quarter_comparison_data.json

PYTHONPATH=src python -m fund_holdings_agent.history_cli status \
  --db outputs/history.sqlite
```

## 查询示例

```sql
-- 某基金经理各季度正式持仓
SELECT report_date, fund_code, stock_code, stock_name, shares_10k, nav_ratio
FROM v_formal_holdings
WHERE manager = '于威业'
ORDER BY report_date, fund_code, rank;

-- 相邻季度新进和退出公司
SELECT previous_report_date, current_report_date, change_type, stock_code, stock_name
FROM v_company_changes
WHERE manager = '于威业' AND change_type IN ('新进', '退出')
ORDER BY change_type, stock_code;

-- 数据库完整性
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

## 当前限制

- 行业数据仍为当前快照，库中保存了快照日期和历史时点标志，不能据此冒充历史行业成分。
- “新进／退出”表示进入或退出季度前十大披露名单，不等于首次建仓或完全清仓。
- 当前数据库保存确定性结果，不保存或依赖 DeepSeek 输出。
