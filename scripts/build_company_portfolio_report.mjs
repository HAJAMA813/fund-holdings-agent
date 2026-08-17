import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [portfolioSummaryPath, outputPath, previewDir] = process.argv.slice(2);
if (!portfolioSummaryPath || !outputPath || !previewDir) {
  throw new Error("usage: build_company_portfolio_report.mjs portfolio_summary.json output.xlsx preview_dir");
}

const portfolio = JSON.parse(await fs.readFile(portfolioSummaryPath, "utf8"));
const workbook = Workbook.create();
const NAVY = "#17365D";
const TEAL = "#1F7A8C";
const PALE = "#EAF2F8";
const GREEN = "#E2F0D9";
const AMBER = "#FFF4CC";
const RED = "#FCE8E6";
const GRAY = "#F3F6F9";
let tableCounter = 0;

function shortCompanyName(value) {
  return String(value || "基金公司")
    .replace(/基金管理股份有限公司$/, "基金")
    .replace(/基金管理有限公司$/, "基金")
    .replace(/基金有限责任公司$/, "基金")
    .replace(/管理有限公司$/, "")
    .replace(/有限公司$/, "");
}

function reportQuarter(value) {
  const date = new Date(`${value}T00:00:00Z`);
  return `${date.getUTCFullYear()}Q${Math.floor(date.getUTCMonth() / 3) + 1}`;
}

const companyNames = (portfolio.companies || [portfolio.company]).filter(Boolean);
const companyLabel = companyNames.map(shortCompanyName).join("、") || "基金公司";
const reportDate = portfolio.report_date;
const snapshotDate = portfolio.as_of;
const quarterLabel = reportQuarter(reportDate);

function colName(index) {
  let n = index + 1;
  let out = "";
  while (n) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function dateValue(value) {
  return value ? new Date(`${value}T00:00:00Z`) : "";
}

function splitManagers(value) {
  return String(value || "").split(/[,，、;；\s]+/).filter(Boolean);
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0);
}

function unique(rows, key) {
  return new Set(rows.map((row) => row[key]).filter(Boolean));
}

function addTableSheet(name, title, headers, rows, widths = {}, freezeColumns = 0) {
  const sheet = workbook.worksheets.getItem(name);
  sheet.showGridLines = false;
  const lastCol = colName(headers.length - 1);
  sheet.getRange(`A1:${lastCol}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${lastCol}1`).format = {
    fill: NAVY,
    font: { bold: true, color: "#FFFFFF", size: 15 },
    rowHeight: 30,
    verticalAlignment: "center",
  };
  const matrix = [headers, ...rows.map((row) => headers.map((header) => row[header] ?? ""))];
  const endRow = matrix.length + 1;
  const address = `A2:${lastCol}${endRow}`;
  sheet.getRange(address).values = matrix;
  sheet.getRange(`A2:${lastCol}2`).format = {
    fill: TEAL,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
    rowHeight: 30,
  };
  sheet.getRange(address).format.borders = {
    insideHorizontal: { style: "thin", color: "#D9E2EC" },
  };
  headers.forEach((header, index) => {
    sheet.getRangeByIndexes(0, index, endRow, 1).format.columnWidth = widths[header] ?? 16;
  });
  sheet.freezePanes.freezeRows(2);
  if (freezeColumns) sheet.freezePanes.freezeColumns(freezeColumns);
  if (rows.length) {
    tableCounter += 1;
    const table = sheet.tables.add(address, true, `T${String(tableCounter).padStart(2, "0")}`);
    table.style = "TableStyleMedium2";
  }
  return { sheet, endRow, lastCol };
}

const managerData = [];
for (const result of portfolio.manager_results) {
  const outputDir = result.output_dir;
  const [pool, pipeline, industry, readiness, manifest] = await Promise.all([
    fs.readFile(path.join(outputDir, "manager_fund_pool_data.json"), "utf8").then(JSON.parse),
    fs.readFile(path.join(outputDir, "pipeline_data.json"), "utf8").then(JSON.parse),
    fs.readFile(path.join(outputDir, "industry_analysis_data.json"), "utf8").then(JSON.parse),
    fs.readFile(path.join(outputDir, "disclosure_readiness.json"), "utf8").then(JSON.parse),
    fs.readFile(path.join(outputDir, "batch_manifest.json"), "utf8").then(JSON.parse),
  ]);
  managerData.push({ result, pool, pipeline, industry, readiness, manifest });
}

const managerRows = [];
const fundPoolRows = [];
const managerHoldingRows = [];
const anomalyRows = [];

for (const item of managerData) {
  const targetManager = item.pool.summary.manager;
  const selectedShares = Number(item.pool.summary.selected_share_count || 0);
  const formal = item.industry.formal_holdings_industry || [];
  const aStocks = new Set(formal.filter((row) => row.market === "A股").map((row) => row.stock_code));
  const mappedAStocks = new Set(formal.filter((row) => row.market === "A股" && row.industry_status === "当前快照已匹配").map((row) => row.stock_code));
  managerRows.push({
    "目标基金经理": targetManager,
    "天天基金经理ID": item.pool.summary.manager_id,
    "分析状态": selectedShares ? "有适用产品" : "无适用产品",
    "报告期在任份额": item.pool.summary.active_share_count,
    "纳入份额": selectedShares,
    "经理-产品数": item.pool.summary.product_count,
    "成功份额": item.pipeline.summary.successful_funds,
    "正式代表产品": item.pipeline.summary.formal_funds,
    "正式持仓行数": item.pipeline.summary.formal_holding_rows,
    "持仓错误": item.pipeline.summary.error_count,
    "持仓警告": item.pipeline.summary.warning_count,
    "唯一重仓股": unique(formal, "stock_code").size,
    "A股行业覆盖率": aStocks.size ? mappedAStocks.size / aStocks.size : "",
    "工作流状态": item.manifest.overall_status,
    "披露状态": item.readiness.summary.status,
  });

  for (const row of item.pool.all_tenures.filter((entry) => entry.active_on_report_date)) {
    fundPoolRows.push({
      "目标基金经理": targetManager,
      "基金代码": row.fund_code,
      "基金名称": row.fund_name,
      "基础产品名称": row.product_base_name,
      "产品组": row.product_group,
      "基金类型": row.fund_type,
      "任职开始": dateValue(row.tenure_start),
      "任职结束": dateValue(row.tenure_end),
      "成立日期": dateValue(row.inception_date),
      "报告期核实经理": row.verified_manager,
      "核验状态": row.manager_verification,
      "是否纳入": row.selected ? "是" : "否",
      "筛选结论": row.selection_reason,
      "经理档案URL": row.manager_profile_url,
      "基金信息URL": row.fund_info_url,
      "经理历史URL": row.manager_history_url,
    });
    if (!row.selected) {
      anomalyRows.push({
        "目标基金经理": targetManager,
        "类型": "产品筛选",
        "级别": "提示",
        "分类": "报告期不适用",
        "基金/股票代码": row.fund_code,
        "基金/股票名称": row.fund_name,
        "报告期": dateValue(portfolio.report_date),
        "问题说明": row.selection_reason,
        "是否阻断": "否",
        "建议处理": "保留审计记录，不进入直接股票持仓口径",
        "来源URL": row.fund_info_url || row.manager_profile_url,
      });
    }
  }

  for (const row of formal) {
    managerHoldingRows.push({
      "目标基金经理": targetManager,
      "基金代码": row.fund_code,
      "基金名称": row.fund_name,
      "报告期核实经理": row.manager,
      "报告期": dateValue(row.report_date),
      "排名": row.rank,
      "股票代码": row.stock_code,
      "股票名称": row.stock_name,
      "市场": row.market,
      "持股数量(万股)": row.shares_10k,
      "持仓市值(万元)": row.market_value_10k,
      "占基金净值比例": row.nav_ratio,
      "申万一级行业": row.sw_level1,
      "申万二级行业": row.sw_level2,
      "行业匹配状态": row.industry_status,
      "重复组": row.duplicate_group,
      "代表份额": row.representative,
      "持仓来源URL": row.source_url,
      "行业来源URL": row.industry_source_url,
    });
  }

  for (const issue of item.pipeline.issues || []) {
    anomalyRows.push({
      "目标基金经理": targetManager,
      "类型": "持仓数据",
      "级别": issue.severity,
      "分类": issue.category,
      "基金/股票代码": issue.fund_code,
      "基金/股票名称": issue.fund_name,
      "报告期": dateValue(issue.report_date),
      "问题说明": issue.message,
      "是否阻断": issue.severity === "错误" ? "是" : "否",
      "建议处理": issue.action,
      "来源URL": issue.source_url,
    });
  }
  for (const issue of item.industry.industry_issues || []) {
    anomalyRows.push({
      "目标基金经理": targetManager,
      "类型": "行业分类",
      "级别": issue.severity,
      "分类": issue.category,
      "基金/股票代码": issue.stock_code,
      "基金/股票名称": issue.stock_name,
      "报告期": dateValue(portfolio.report_date),
      "问题说明": issue.message,
      "是否阻断": issue.severity === "错误" ? "是" : "否",
      "建议处理": issue.action,
      "来源URL": issue.source_url,
    });
  }
}

const managerDataEnd = managerRows.length + 2;

const uniqueFundMap = new Map();
for (const row of managerHoldingRows) {
  const key = `${row["基金代码"]}|${row["股票代码"]}`;
  if (!uniqueFundMap.has(key)) {
    uniqueFundMap.set(key, { ...row, _targetManagers: new Set([row["目标基金经理"]]) });
  } else {
    uniqueFundMap.get(key)._targetManagers.add(row["目标基金经理"]);
  }
}
const uniqueFundRows = [...uniqueFundMap.values()].map((row) => ({
  "基金代码": row["基金代码"],
  "基金名称": row["基金名称"],
  "本名单涉及经理": [...row._targetManagers].sort().join("、"),
  "报告期核实经理": row["报告期核实经理"],
  "报告期": row["报告期"],
  "排名": row["排名"],
  "股票代码": row["股票代码"],
  "股票名称": row["股票名称"],
  "市场": row["市场"],
  "持股数量(万股)": row["持股数量(万股)"],
  "持仓市值(万元)": row["持仓市值(万元)"],
  "占基金净值比例": row["占基金净值比例"],
  "申万一级行业": row["申万一级行业"],
  "申万二级行业": row["申万二级行业"],
  "行业匹配状态": row["行业匹配状态"],
  "持仓来源URL": row["持仓来源URL"],
  "行业来源URL": row["行业来源URL"],
})).sort((a, b) => String(a["基金代码"]).localeCompare(String(b["基金代码"])) || a["排名"] - b["排名"]);

const companyStockMap = new Map();
for (const row of uniqueFundRows) {
  const code = row["股票代码"];
  if (!companyStockMap.has(code)) {
    companyStockMap.set(code, {
      code,
      name: row["股票名称"],
      market: row["市场"],
      industry1: row["申万一级行业"],
      industry2: row["申万二级行业"],
      industryStatus: row["行业匹配状态"],
      funds: new Set(),
      managers: new Set(),
      holdingRows: 0,
      shares: 0,
      marketValue: 0,
      navRatio: 0,
      source: row["行业来源URL"],
    });
  }
  const item = companyStockMap.get(code);
  item.funds.add(row["基金代码"]);
  splitManagers(row["本名单涉及经理"]).forEach((manager) => item.managers.add(manager));
  item.holdingRows += 1;
  item.shares += Number(row["持股数量(万股)"] || 0);
  item.marketValue += Number(row["持仓市值(万元)"] || 0);
  item.navRatio += Number(row["占基金净值比例"] || 0);
}
const companyStockRows = [...companyStockMap.values()].map((row) => ({
  "股票代码": row.code,
  "市场": row.market,
  "股票名称": row.name,
  "涉及基金数": row.funds.size,
  "涉及经理数": row.managers.size,
  "本名单涉及经理": [...row.managers].sort().join("、"),
  "基金-股票记录数": row.holdingRows,
  "持股数量合计(万股)": row.shares,
  "持仓市值合计(万元)": row.marketValue,
  "净值比例合计(非加权)": row.navRatio,
  "行业匹配状态": row.industryStatus,
  "申万一级行业": row.industry1,
  "申万二级行业": row.industry2,
  "行业来源URL": row.source,
})).sort((a, b) => b["持仓市值合计(万元)"] - a["持仓市值合计(万元)"] || String(a["股票代码"]).localeCompare(String(b["股票代码"])));

const industryMap = new Map();
for (const row of uniqueFundRows) {
  const label = row["市场"] === "A股" ? row["申万一级行业"] : `${row["市场"]}（申万不适用）`;
  if (!industryMap.has(label)) {
    industryMap.set(label, { label, market: row["市场"], stocks: new Set(), funds: new Set(), managers: new Set(), rows: 0, marketValue: 0, navRatio: 0 });
  }
  const item = industryMap.get(label);
  item.stocks.add(row["股票代码"]);
  item.funds.add(row["基金代码"]);
  splitManagers(row["本名单涉及经理"]).forEach((manager) => item.managers.add(manager));
  item.rows += 1;
  item.marketValue += Number(row["持仓市值(万元)"] || 0);
  item.navRatio += Number(row["占基金净值比例"] || 0);
}
const industryRows = [...industryMap.values()].map((row) => ({
  "行业/市场分类": row.label,
  "适用市场": row.market,
  "唯一股票数": row.stocks.size,
  "涉及基金数": row.funds.size,
  "涉及经理数": row.managers.size,
  "基金-股票记录数": row.rows,
  "持仓市值合计(万元)": row.marketValue,
  "净值比例合计(非加权)": row.navRatio,
  "行业快照日期": dateValue(portfolio.as_of),
  "说明": row.market === "A股" ? "申万行业分类标准2021，当前公开快照" : "非A股不适用申万行业分类",
})).sort((a, b) => b["持仓市值合计(万元)"] - a["持仓市值合计(万元)"]);

const summary = workbook.worksheets.add("运行摘要");
for (const sheetName of ["基金经理概览", "基金池明细", "经理持仓明细", "公司唯一基金持仓", "重仓公司汇总", "申万行业汇总", "异常与排除", "来源与口径"]) {
  workbook.worksheets.add(sheetName);
}
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [[`${companyLabel} ${quarterLabel} 基金经理前十大持仓分析`]];
summary.getRange("A1:H1").format = { fill: NAVY, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 34, verticalAlignment: "center" };
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [[`报告期：${reportDate}　数据快照：${snapshotDate}　生成口径：确定性规则，未调用 DeepSeek`]];
summary.getRange("A2:H2").format = { fill: GRAY, font: { color: "#44546A" }, rowHeight: 22 };
summary.getRange("A4:A9").values = [["基金经理数"], ["有适用产品经理"], ["无适用产品经理"], ["报告期在任份额"], ["纳入份额"], ["经理-产品数"]];
summary.getRange("B4:B9").formulas = [
  [`=COUNTA('基金经理概览'!$A$3:$A$${managerDataEnd})`],
  [`=COUNTIF('基金经理概览'!$C$3:$C$${managerDataEnd},\"有适用产品\")`],
  [`=COUNTIF('基金经理概览'!$C$3:$C$${managerDataEnd},\"无适用产品\")`],
  [`=SUM('基金经理概览'!$D$3:$D$${managerDataEnd})`],
  [`=SUM('基金经理概览'!$E$3:$E$${managerDataEnd})`],
  [`=SUM('基金经理概览'!$F$3:$F$${managerDataEnd})`],
];
summary.getRange("D4:D10").values = [["公司唯一基金数"], ["经理口径持仓行"], ["公司唯一基金持仓行"], ["唯一重仓股票"], ["唯一A股"], ["已匹配申万A股"], ["A股行业覆盖率"]];
summary.getRange("E4:E10").formulas = [
  [`=COUNTA(UNIQUE('公司唯一基金持仓'!$A$3:$A$${uniqueFundRows.length + 2}))`],
  [`=COUNTA('经理持仓明细'!$A$3:$A$${managerHoldingRows.length + 2})`],
  [`=COUNTA('公司唯一基金持仓'!$A$3:$A$${uniqueFundRows.length + 2})`],
  [`=COUNTA('重仓公司汇总'!$A$3:$A$${companyStockRows.length + 2})`],
  [`=COUNTIF('重仓公司汇总'!$B$3:$B$${companyStockRows.length + 2},\"A股\")`],
  [`=COUNTIFS('重仓公司汇总'!$B$3:$B$${companyStockRows.length + 2},\"A股\",'重仓公司汇总'!$K$3:$K$${companyStockRows.length + 2},\"当前快照已匹配\")`],
  ["=IF(E8=0,1,E9/E8)"],
];
for (const range of ["A4:B9", "D4:E10"]) {
  summary.getRange(range).format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
}
summary.getRange("A4:A9").format = { fill: PALE, font: { bold: true } };
summary.getRange("D4:D10").format = { fill: PALE, font: { bold: true } };
summary.getRange("B4:B9").format = { font: { color: "#008000", bold: true }, numberFormat: "#,##0" };
summary.getRange("E4:E9").format = { font: { color: "#008000", bold: true }, numberFormat: "#,##0" };
summary.getRange("E10").format = { font: { color: "#008000", bold: true }, numberFormat: "0.0%" };
summary.getRange("A12:H13").merge();
summary.getRange("A12").values = [[`口径说明：经理视角按“经理－代表产品”保留 ${managerHoldingRows.length} 条前十大持仓；公司总体视角再按“基金代码＋股票代码”去重为 ${uniqueFundRows.length} 条，避免共同管理的同一基金重复计算。行业为 ${snapshotDate} 当前公开快照，不代表 ${reportDate} 历史成分。`]];
summary.getRange("A12:H13").format = { fill: AMBER, wrapText: true, verticalAlignment: "center", rowHeight: 28 };
summary.getRange("A15:F15").merge();
summary.getRange("A15").values = [["质量检查"]];
summary.getRange("A15:F15").format = { fill: NAVY, font: { bold: true, color: "#FFFFFF" }, rowHeight: 24 };
summary.getRange("A16:F23").values = [
  ["检查项", "实际值", "预期值", "差异", "状态", "说明"],
  ["经理名单完整", "", managerRows.length, "", "", `名单应包含${managerRows.length}位${companyLabel}经理`],
  ["工作流全部完成", "", managerRows.length, "", "", "所有经理状态应为completed"],
  ["经理持仓行数衔接", "", "", "", "", "持仓明细行数应等于经理概览合计"],
  ["公司唯一持仓无重复", "", uniqueFundRows.length, "", "", "按基金代码＋股票代码去重"],
  ["A股申万行业覆盖", "", "", "", "", "唯一A股均应匹配当前申万快照"],
  ["持仓错误", "", 0, "", "", "错误为0才可正式交付"],
  ["行业历史时点", "当前快照", "历史时点", "不适用", "限制", "生产历史口径需接入带纳入/剔除日期的数据源"],
];
summary.getRange("A16:F16").format = { fill: TEAL, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("B17:B22").formulas = [
  [`=COUNTA('基金经理概览'!$A$3:$A$${managerDataEnd})`],
  [`=COUNTIF('基金经理概览'!$N$3:$N$${managerDataEnd},\"completed\")`],
  [`=COUNTA('经理持仓明细'!$A$3:$A$${managerHoldingRows.length + 2})`],
  [`=COUNTA('公司唯一基金持仓'!$A$3:$A$${uniqueFundRows.length + 2})`],
  [`=COUNTIFS('重仓公司汇总'!$B$3:$B$${companyStockRows.length + 2},\"A股\",'重仓公司汇总'!$K$3:$K$${companyStockRows.length + 2},\"当前快照已匹配\")`],
  [`=SUM('基金经理概览'!$J$3:$J$${managerDataEnd})`],
];
summary.getRange("C19").formulas = [["=SUM('基金经理概览'!$I$3:$I$22)"]];
summary.getRange("C21").formulas = [[`=COUNTIF('重仓公司汇总'!$B$3:$B$${companyStockRows.length + 2},\"A股\")`]];
summary.getRange("D17:D22").formulas = [["=B17-C17"], ["=B18-C18"], ["=B19-C19"], ["=B20-C20"], ["=B21-C21"], ["=B22-C22"]];
summary.getRange("E17:E22").formulas = [["=IF(ABS(D17)<0.000001,\"OK\",\"CHECK\")"], ["=IF(ABS(D18)<0.000001,\"OK\",\"CHECK\")"], ["=IF(ABS(D19)<0.000001,\"OK\",\"CHECK\")"], ["=IF(ABS(D20)<0.000001,\"OK\",\"CHECK\")"], ["=IF(ABS(D21)<0.000001,\"OK\",\"CHECK\")"], ["=IF(ABS(D22)<0.000001,\"OK\",\"CHECK\")"]];
summary.getRange("B17:E22").format.font = { color: "#008000" };
summary.getRange("A16:F23").format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EC" }, outside: { style: "thin", color: "#B8C4CE" } };
summary.getRange("E17:E23").conditionalFormats.addCustom('=$E17="OK"', { fill: GREEN, font: { color: "#375623", bold: true } });
summary.getRange("E17:E23").conditionalFormats.addCustom('=$E17="CHECK"', { fill: RED, font: { color: "#9C0006", bold: true } });
summary.getRange("E17:E23").conditionalFormats.addCustom('=$E17="限制"', { fill: AMBER, font: { bold: true } });
summary.getRange("A:A").format.columnWidth = 26;
summary.getRange("B:B").format.columnWidth = 16;
summary.getRange("C:C").format.columnWidth = 16;
summary.getRange("D:D").format.columnWidth = 24;
summary.getRange("E:E").format.columnWidth = 16;
summary.getRange("F:F").format.columnWidth = 62;
summary.getRange("G:H").format.columnWidth = 12;

const managerSheet = addTableSheet("基金经理概览", "基金经理覆盖与运行状态", Object.keys(managerRows[0]), managerRows, {
  "目标基金经理": 14, "天天基金经理ID": 16, "分析状态": 16, "报告期在任份额": 16, "纳入份额": 12, "经理-产品数": 14,
  "成功份额": 12, "正式代表产品": 15, "正式持仓行数": 15, "持仓错误": 12, "持仓警告": 12, "唯一重仓股": 14,
  "A股行业覆盖率": 16, "工作流状态": 18, "披露状态": 16,
}, 1);
managerSheet.sheet.getRange(`D3:L${managerSheet.endRow}`).format.numberFormat = "#,##0";
managerSheet.sheet.getRange(`M3:M${managerSheet.endRow}`).format.numberFormat = "0.0%";
managerSheet.sheet.getRange(`A3:O${managerSheet.endRow}`).conditionalFormats.addCustom('=$C3="无适用产品"', { fill: GRAY, font: { color: "#666666" } });
managerSheet.sheet.getRange(`N3:N${managerSheet.endRow}`).conditionalFormats.addCustom('=$N3="completed"', { fill: GREEN, font: { color: "#375623", bold: true } });

const poolHeaders = Object.keys(fundPoolRows[0]);
const poolSheet = addTableSheet("基金池明细", "报告期基金池、产品筛选与经理核验", poolHeaders, fundPoolRows, {
  "目标基金经理": 14, "基金代码": 12, "基金名称": 32, "基础产品名称": 30, "产品组": 13, "基金类型": 20,
  "任职开始": 14, "任职结束": 14, "成立日期": 14, "报告期核实经理": 24, "核验状态": 12, "是否纳入": 12,
  "筛选结论": 38, "经理档案URL": 50, "基金信息URL": 50, "经理历史URL": 50,
}, 2);
poolSheet.sheet.getRange(`B3:B${poolSheet.endRow}`).format.numberFormat = "000000";
poolSheet.sheet.getRange(`G3:I${poolSheet.endRow}`).format.numberFormat = "yyyy-mm-dd";
poolSheet.sheet.getRange(`M3:M${poolSheet.endRow}`).format.wrapText = true;
poolSheet.sheet.getRange(`A3:P${poolSheet.endRow}`).conditionalFormats.addCustom('=$L3="否"', { fill: GRAY, font: { color: "#666666" } });

const holdingHeaders = Object.keys(managerHoldingRows[0]);
const holdingSheet = addTableSheet("经理持仓明细", "经理口径正式持仓（经理－代表产品）", holdingHeaders, managerHoldingRows, {
  "目标基金经理": 14, "基金代码": 12, "基金名称": 32, "报告期核实经理": 24, "报告期": 14, "排名": 8,
  "股票代码": 16, "股票名称": 18, "市场": 12, "持股数量(万股)": 17, "持仓市值(万元)": 18, "占基金净值比例": 18,
  "申万一级行业": 16, "申万二级行业": 20, "行业匹配状态": 18, "重复组": 12, "代表份额": 12,
  "持仓来源URL": 65, "行业来源URL": 58,
}, 3);
holdingSheet.sheet.getRange(`B3:B${holdingSheet.endRow}`).format.numberFormat = "000000";
holdingSheet.sheet.getRange(`E3:E${holdingSheet.endRow}`).format.numberFormat = "yyyy-mm-dd";
holdingSheet.sheet.getRange(`J3:K${holdingSheet.endRow}`).format.numberFormat = "#,##0.00";
holdingSheet.sheet.getRange(`L3:L${holdingSheet.endRow}`).format.numberFormat = "0.00%";

const uniqueHeaders = Object.keys(uniqueFundRows[0]);
const uniqueSheet = addTableSheet("公司唯一基金持仓", "公司口径持仓（跨经理按基金代码＋股票代码去重）", uniqueHeaders, uniqueFundRows, {
  "基金代码": 12, "基金名称": 32, "本名单涉及经理": 22, "报告期核实经理": 26, "报告期": 14, "排名": 8,
  "股票代码": 16, "股票名称": 18, "市场": 12, "持股数量(万股)": 17, "持仓市值(万元)": 18, "占基金净值比例": 18,
  "申万一级行业": 16, "申万二级行业": 20, "行业匹配状态": 18, "持仓来源URL": 65, "行业来源URL": 58,
}, 2);
uniqueSheet.sheet.getRange(`A3:A${uniqueSheet.endRow}`).format.numberFormat = "000000";
uniqueSheet.sheet.getRange(`E3:E${uniqueSheet.endRow}`).format.numberFormat = "yyyy-mm-dd";
uniqueSheet.sheet.getRange(`J3:K${uniqueSheet.endRow}`).format.numberFormat = "#,##0.00";
uniqueSheet.sheet.getRange(`L3:L${uniqueSheet.endRow}`).format.numberFormat = "0.00%";

const companyHeaders = Object.keys(companyStockRows[0]);
const companySheet = addTableSheet("重仓公司汇总", "公司口径重仓股票汇总（唯一基金）", companyHeaders, companyStockRows, {
  "股票代码": 16, "市场": 12, "股票名称": 18, "涉及基金数": 13, "涉及经理数": 13, "本名单涉及经理": 36,
  "基金-股票记录数": 17, "持股数量合计(万股)": 20, "持仓市值合计(万元)": 21, "净值比例合计(非加权)": 22,
  "行业匹配状态": 18, "申万一级行业": 16, "申万二级行业": 20, "行业来源URL": 58,
}, 3);
companySheet.sheet.getRange(`D3:I${companySheet.endRow}`).format.numberFormat = "#,##0.00";
companySheet.sheet.getRange(`D3:G${companySheet.endRow}`).format.numberFormat = "#,##0";
companySheet.sheet.getRange(`J3:J${companySheet.endRow}`).format.numberFormat = "0.00%";
companySheet.sheet.getRange(`I3:I${companySheet.endRow}`).conditionalFormats.add("dataBar", { color: "#5B9BD5", gradient: true });

const industryHeaders = Object.keys(industryRows[0]);
const industrySheet = addTableSheet("申万行业汇总", "公司口径行业与市场暴露汇总（唯一基金）", industryHeaders, industryRows, {
  "行业/市场分类": 26, "适用市场": 14, "唯一股票数": 14, "涉及基金数": 14, "涉及经理数": 14,
  "基金-股票记录数": 18, "持仓市值合计(万元)": 21, "净值比例合计(非加权)": 22, "行业快照日期": 16, "说明": 48,
}, 2);
industrySheet.sheet.getRange(`C3:G${industrySheet.endRow}`).format.numberFormat = "#,##0";
industrySheet.sheet.getRange(`G3:G${industrySheet.endRow}`).format.numberFormat = "#,##0.00";
industrySheet.sheet.getRange(`H3:H${industrySheet.endRow}`).format.numberFormat = "0.00%";
industrySheet.sheet.getRange(`I3:I${industrySheet.endRow}`).format.numberFormat = "yyyy-mm-dd";

const anomalyHeaders = Object.keys(anomalyRows[0]);
const anomalySheet = addTableSheet("异常与排除", "异常、提示、产品排除与行业时点限制", anomalyHeaders, anomalyRows, {
  "目标基金经理": 14, "类型": 14, "级别": 10, "分类": 24, "基金/股票代码": 16, "基金/股票名称": 30,
  "报告期": 14, "问题说明": 62, "是否阻断": 12, "建议处理": 48, "来源URL": 65,
}, 2);
anomalySheet.sheet.getRange(`G3:G${anomalySheet.endRow}`).format.numberFormat = "yyyy-mm-dd";
anomalySheet.sheet.getRange(`E3:E${anomalySheet.endRow}`).format.numberFormat = "000000";
anomalySheet.sheet.getRange(`H3:J${anomalySheet.endRow}`).format.wrapText = true;
anomalySheet.sheet.getRange(`A3:K${anomalySheet.endRow}`).conditionalFormats.addCustom('=$C3="错误"', { fill: RED, font: { color: "#9C0006" } });
anomalySheet.sheet.getRange(`A3:K${anomalySheet.endRow}`).conditionalFormats.addCustom('=$C3="警告"', { fill: AMBER });

const sourceRows = [
  { "来源ID": "S01", "来源/口径": "天天基金基金经理档案", "用途与限制": "完整历史任职基金池及报告期切片", "URL或路径": "https://fund.eastmoney.com/manager/{基金经理ID}.html" },
  { "来源ID": "S02", "来源/口径": "天天基金基金基本概况", "用途与限制": "成立日期与基金类型交叉核验", "URL或路径": "https://fundf10.eastmoney.com/jbgk_{基金代码}.html" },
  { "来源ID": "S03", "来源/口径": "天天基金基金经理变动", "用途与限制": "核验报告期在任经理；共同管理采用包含关系", "URL或路径": "https://fundf10.eastmoney.com/jjjl_{基金代码}.html" },
  { "来源ID": "S04", "来源/口径": "东方财富季度持仓接口", "用途与限制": "指定自然季度前十大股票持仓", "URL或路径": "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc" },
  { "来源ID": "S05", "来源/口径": "申万行业分类标准2021", "用途与限制": "A股一级、二级行业标准", "URL或路径": "https://wxweb.swsresearch.com/swsreport/2021_08/328340.pdf" },
  { "来源ID": "S06", "来源/口径": "公开行业当前快照", "用途与限制": `${snapshotDate}当前快照，不等同于${reportDate}报告期历史成分`, "URL或路径": "https://legulegu.com/stockdata/sw-industry-overview" },
  { "来源ID": "S07", "来源/口径": "股票行业页面", "用途与限制": "逐只A股识别当前申万二级行业", "URL或路径": "https://basic.10jqka.com.cn/{股票代码}/index.html" },
  { "来源ID": "S08", "来源/口径": "公募基金信息披露管理办法第十九条", "用途与限制": "基金合同生效不足两个月时，当期定期报告可不编制", "URL或路径": "https://www.csrc.gov.cn/csrc/c106256/c1653985/content.shtml" },
  { "来源ID": "R01", "来源/口径": "产品范围", "用途与限制": "默认排除FOF、货币、固收指数、非二级债基和商品/期货；二级债基与可转债可纳入", "URL或路径": "需求文档 V1.6" },
  { "来源ID": "R02", "来源/口径": "份额去重", "用途与限制": "底稿保留A/C/E；正式口径按基础产品与股票序列选代表份额", "URL或路径": "需求文档 V1.6" },
  { "来源ID": "R03", "来源/口径": "公司级去重", "用途与限制": "跨经理按基金代码＋股票代码去重，避免共同管理基金重复计算", "URL或路径": "本工作簿确定性汇总规则" },
  { "来源ID": "R04", "来源/口径": "数值解释", "用途与限制": "持仓市值单位为万元；跨基金净值比例合计为非加权审计指标，不代表组合权重", "URL或路径": "本工作簿口径说明" },
  { "来源ID": "R05", "来源/口径": "公式颜色", "用途与限制": "绿色字为工作簿内跨表公式；黑色字为导入或确定性汇总值", "URL或路径": "工作簿格式约定" },
  { "来源ID": "R06", "来源/口径": "模型使用", "用途与限制": "本阶段未调用DeepSeek或其他大模型，不生成投资建议", "URL或路径": "需求文档 V1.6" },
  { "来源ID": "A01", "来源/口径": "批量审计摘要", "用途与限制": `${managerRows.length}位${companyLabel}经理任务状态与公司级指标`, "URL或路径": path.resolve(portfolioSummaryPath) },
];
const sourceSheet = addTableSheet("来源与口径", "数据来源、业务规则与审计说明", Object.keys(sourceRows[0]), sourceRows, {
  "来源ID": 12, "来源/口径": 32, "用途与限制": 82, "URL或路径": 90,
}, 1);
sourceSheet.sheet.getRange(`A3:D${sourceSheet.endRow}`).format.wrapText = true;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const previewRanges = {
  "运行摘要": "A1:H23",
  "基金经理概览": `A1:O${managerDataEnd}`,
  "基金池明细": "A1:P30",
  "经理持仓明细": "A1:S30",
  "公司唯一基金持仓": "A1:Q30",
  "重仓公司汇总": "A1:N30",
  "申万行业汇总": `A1:J${Math.min(industryRows.length + 2, 38)}`,
  "异常与排除": "A1:K30",
  "来源与口径": `A1:D${sourceRows.length + 2}`,
};
for (const [sheetName, range] of Object.entries(previewRanges)) {
  const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}

const summaryInspect = await workbook.inspect({ kind: "table", range: "运行摘要!A1:H23", include: "values,formulas", tableMaxRows: 30, tableMaxCols: 10 });
console.log(summaryInspect.ndjson);
const companyInspect = await workbook.inspect({ kind: "table", range: "重仓公司汇总!A1:N12", include: "values,formulas", tableMaxRows: 15, tableMaxCols: 16 });
console.log(companyInspect.ndjson);
const errorScan = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
console.log(errorScan.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({
  output: path.resolve(outputPath),
  managers: managerRows.length,
  manager_holding_rows: managerHoldingRows.length,
  unique_fund_holding_rows: uniqueFundRows.length,
  company_stock_rows: companyStockRows.length,
  industry_rows: industryRows.length,
  anomaly_rows: anomalyRows.length,
}, null, 2));
