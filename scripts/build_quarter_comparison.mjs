import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) {
  throw new Error("usage: build_quarter_comparison.mjs quarter_comparison_data.json output.xlsx preview_dir");
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const navy = "#17365D";
const teal = "#1F7A8C";
const pale = "#EAF2F8";
const green = "#E2F0D9";
const red = "#FCE8E6";
const amber = "#FFF4CC";
const blue = "#DDEBF7";

function colName(index) {
  let n = index + 1;
  let output = "";
  while (n) {
    const remainder = (n - 1) % 26;
    output = String.fromCharCode(65 + remainder) + output;
    n = Math.floor((n - 1) / 26);
  }
  return output;
}

function dateValue(value) {
  return value ? new Date(`${value}T00:00:00Z`) : "";
}

function addTableSheet(name, headers, rows, widths = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [headers, ...rows.map((row) => headers.map((header) => row[header] ?? ""))];
  const lastColumn = colName(headers.length - 1);
  const address = `A1:${lastColumn}${matrix.length}`;
  sheet.getRange(address).values = matrix;
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
    rowHeight: 32,
  };
  sheet.getRange(address).format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EC" } };
  sheet.freezePanes.freezeRows(1);
  headers.forEach((header, index) => {
    sheet.getRangeByIndexes(0, index, Math.max(matrix.length, 2), 1).format.columnWidth = widths[header] ?? 16;
  });
  if (rows.length) sheet.tables.add(address, true, `T${workbook.worksheets.items.length}${name.replace(/[^A-Za-z0-9]/g, "")}`);
  return sheet;
}

function applyChangeFormatting(sheet, range, column = "A") {
  const target = sheet.getRange(range);
  target.conditionalFormats.addCustom(`=$${column}2="新进"`, { fill: green, font: { color: "#375623", bold: true } });
  target.conditionalFormats.addCustom(`=$${column}2="增持"`, { fill: blue, font: { color: "#1F4E78" } });
  target.conditionalFormats.addCustom(`=$${column}2="减持"`, { fill: amber, font: { color: "#7F6000" } });
  target.conditionalFormats.addCustom(`=$${column}2="退出"`, { fill: red, font: { color: "#9C0006" } });
}

const s = data.summary;
const subject = s.company || s.manager;
const fundScopeText = s.formal_fund_scope_same === false
  ? `两期正式基金范围发生变化（上期 ${s.previous_formal_funds} 只，本期 ${s.current_formal_funds} 只）`
  : `两期正式基金范围一致（均为 ${s.current_formal_funds} 只）`;
const dedupText = s.analysis_type === "company_portfolio"
  ? `公司层已按基金代码+股票代码去重，上期移除 ${s.previous_duplicate_rows_removed ?? 0} 行、本期移除 ${s.current_duplicate_rows_removed ?? 0} 行共同管理重复记录，数值冲突 ${s.dedup_conflict_count ?? 0} 项。`
  : "";
const companyEnd = data.company_changes.length + 1;
const fundEnd = data.fund_stock_changes.length + 1;
const industryEnd = data.industry_changes.length + 1;

const summary = workbook.worksheets.add("运行摘要");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [[`${subject} ${s.previous_report_date} 至 ${s.current_report_date} 前十大持仓变化分析`]];
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 34, verticalAlignment: "center" };
summary.getRange("A3:B10").values = [
  ["分析主体", subject],
  ["上期报告日", dateValue(s.previous_report_date)],
  ["本期报告日", dateValue(s.current_report_date)],
  ["上期正式基金", s.previous_formal_funds],
  ["本期正式基金", s.current_formal_funds],
  ["上期正式持仓行", s.previous_holding_rows],
  ["本期正式持仓行", s.current_holding_rows],
  ["运行状态", s.status],
];
summary.getRange("D3:E9").values = [
  ["公司变化", "数量"],
  ["公司并集", ""],
  ["新进", ""],
  ["退出", ""],
  ["增持", ""],
  ["减持", ""],
  ["持平", ""],
];
summary.getRange("G3:H9").values = [
  ["行业变化", "数量"],
  ["行业并集", ""],
  ["新进入", ""],
  ["退出", ""],
  ["上升", ""],
  ["下降", ""],
  ["持平", ""],
];
summary.getRange("A3:A10").format = { fill: pale, font: { bold: true } };
summary.getRange("D3:E3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("G3:H3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A3:B10").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("D3:E9").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("G3:H9").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("B4:B5").format.numberFormat = "yyyy-mm-dd";
summary.getRange("A12:H14").merge();
summary.getRange("A12").values = [[`结论：${fundScopeText}。${dedupText}股票并集 ${s.company_union_count} 家；变化标签按披露持股数量计算。行业比较使用 ${s.industry_snapshot_date} 同一当前快照，方向可比，但不等同于报告期历史行业成分。全流程未调用 DeepSeek。`]];
summary.getRange("A12:H14").format = { fill: "#F3F6F9", wrapText: true, verticalAlignment: "center" };
summary.getRange("A:A").format.columnWidth = 23;
summary.getRange("B:B").format.columnWidth = 34;
summary.getRange("C:C").format.columnWidth = 4;
summary.getRange("D:D").format.columnWidth = 17;
summary.getRange("E:E").format.columnWidth = 14;
summary.getRange("F:F").format.columnWidth = 4;
summary.getRange("G:G").format.columnWidth = 17;
summary.getRange("H:H").format.columnWidth = 14;

const companyHeaders = ["变化类型", "股票代码", "股票名称", "申万一级行业", "上期持有基金数", "本期持有基金数", "上期持股(万股)", "本期持股(万股)", "持股变化(万股)", "持股变化率", "上期市值(万元)", "本期市值(万元)", "市值变化(万元)", "市值变化率", "上期净值比例合计", "本期净值比例合计", "净值比例变化", "上期最佳排名", "本期最佳排名", "排名提升", "上期基金代码", "本期基金代码"];
const companyRows = data.company_changes.map((row) => ({
  "变化类型": "",
  "股票代码": row.stock_code,
  "股票名称": row.stock_name,
  "申万一级行业": row.sw_level1,
  "上期持有基金数": row.previous_fund_count,
  "本期持有基金数": row.current_fund_count,
  "上期持股(万股)": row.previous_shares_10k,
  "本期持股(万股)": row.current_shares_10k,
  "持股变化(万股)": "",
  "持股变化率": "",
  "上期市值(万元)": row.previous_market_value_10k,
  "本期市值(万元)": row.current_market_value_10k,
  "市值变化(万元)": "",
  "市值变化率": "",
  "上期净值比例合计": row.previous_nav_ratio_sum,
  "本期净值比例合计": row.current_nav_ratio_sum,
  "净值比例变化": "",
  "上期最佳排名": row.previous_best_rank ?? "",
  "本期最佳排名": row.current_best_rank ?? "",
  "排名提升": "",
  "上期基金代码": row.previous_fund_codes,
  "本期基金代码": row.current_fund_codes,
}));
const companySheet = addTableSheet("公司变化汇总", companyHeaders, companyRows, {
  "变化类型": 12, "股票代码": 16, "股票名称": 18, "申万一级行业": 18, "上期持有基金数": 15, "本期持有基金数": 15,
  "上期持股(万股)": 17, "本期持股(万股)": 17, "持股变化(万股)": 17, "持股变化率": 15,
  "上期市值(万元)": 17, "本期市值(万元)": 17, "市值变化(万元)": 17, "市值变化率": 15,
  "上期净值比例合计": 19, "本期净值比例合计": 19, "净值比例变化": 17, "上期最佳排名": 15, "本期最佳排名": 15, "排名提升": 13,
  "上期基金代码": 24, "本期基金代码": 24,
});
if (companyRows.length) {
  const changeFormulas = [];
  const sharesChange = [];
  const sharesPct = [];
  const marketChange = [];
  const marketPct = [];
  const navChange = [];
  const rankChange = [];
  for (let row = 2; row <= companyEnd; row += 1) {
    changeFormulas.push([`=IF(E${row}=0,"新进",IF(F${row}=0,"退出",IF(I${row}>0.01,"增持",IF(I${row}<-0.01,"减持","持平"))))`]);
    sharesChange.push([`=H${row}-G${row}`]);
    sharesPct.push([`=IF(G${row}=0,"",I${row}/ABS(G${row}))`]);
    marketChange.push([`=L${row}-K${row}`]);
    marketPct.push([`=IF(K${row}=0,"",M${row}/ABS(K${row}))`]);
    navChange.push([`=P${row}-O${row}`]);
    rankChange.push([`=IF(OR(R${row}="",S${row}=""),"",R${row}-S${row})`]);
  }
  companySheet.getRange(`A2:A${companyEnd}`).formulas = changeFormulas;
  companySheet.getRange(`I2:I${companyEnd}`).formulas = sharesChange;
  companySheet.getRange(`J2:J${companyEnd}`).formulas = sharesPct;
  companySheet.getRange(`M2:M${companyEnd}`).formulas = marketChange;
  companySheet.getRange(`N2:N${companyEnd}`).formulas = marketPct;
  companySheet.getRange(`Q2:Q${companyEnd}`).formulas = navChange;
  companySheet.getRange(`T2:T${companyEnd}`).formulas = rankChange;
  companySheet.getRange(`G2:I${companyEnd}`).format.numberFormat = "#,##0.00;[Red](#,##0.00);-";
  companySheet.getRange(`J2:J${companyEnd}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  companySheet.getRange(`K2:M${companyEnd}`).format.numberFormat = "#,##0.00;[Red](#,##0.00);-";
  companySheet.getRange(`N2:Q${companyEnd}`).format.numberFormat = "0.00%;[Red](0.00%);-";
  companySheet.getRange(`U2:V${companyEnd}`).format.numberFormat = "000000";
  applyChangeFormatting(companySheet, `A2:V${companyEnd}`);
}

const fundHeaders = ["基金代码", "基金名称", "变化类型", "股票代码", "股票名称", "申万一级行业", "上期排名", "本期排名", "排名提升", "上期持股(万股)", "本期持股(万股)", "持股变化(万股)", "持股变化率", "上期市值(万元)", "本期市值(万元)", "市值变化(万元)", "上期净值比例", "本期净值比例", "净值比例变化"];
const fundRows = data.fund_stock_changes.map((row) => ({
  "基金代码": row.fund_code,
  "基金名称": row.fund_name,
  "变化类型": "",
  "股票代码": row.stock_code,
  "股票名称": row.stock_name,
  "申万一级行业": row.sw_level1,
  "上期排名": row.previous_rank ?? "",
  "本期排名": row.current_rank ?? "",
  "排名提升": "",
  "上期持股(万股)": row.previous_shares_10k,
  "本期持股(万股)": row.current_shares_10k,
  "持股变化(万股)": "",
  "持股变化率": "",
  "上期市值(万元)": row.previous_market_value_10k,
  "本期市值(万元)": row.current_market_value_10k,
  "市值变化(万元)": "",
  "上期净值比例": row.previous_nav_ratio,
  "本期净值比例": row.current_nav_ratio,
  "净值比例变化": "",
}));
const fundSheet = addTableSheet("基金内持仓变化", fundHeaders, fundRows, {
  "基金代码": 12, "基金名称": 30, "变化类型": 12, "股票代码": 16, "股票名称": 18, "申万一级行业": 18,
  "上期排名": 12, "本期排名": 12, "排名提升": 12, "上期持股(万股)": 17, "本期持股(万股)": 17, "持股变化(万股)": 17,
  "持股变化率": 15, "上期市值(万元)": 17, "本期市值(万元)": 17, "市值变化(万元)": 17,
  "上期净值比例": 16, "本期净值比例": 16, "净值比例变化": 16,
});
if (fundRows.length) {
  const changeFormulas = [], rankChange = [], sharesChange = [], sharesPct = [], marketChange = [], navChange = [];
  for (let row = 2; row <= fundEnd; row += 1) {
    changeFormulas.push([`=IF(G${row}="","新进",IF(H${row}="","退出",IF(L${row}>0.01,"增持",IF(L${row}<-0.01,"减持","持平"))))`]);
    rankChange.push([`=IF(OR(G${row}="",H${row}=""),"",G${row}-H${row})`]);
    sharesChange.push([`=K${row}-J${row}`]);
    sharesPct.push([`=IF(J${row}=0,"",L${row}/ABS(J${row}))`]);
    marketChange.push([`=O${row}-N${row}`]);
    navChange.push([`=R${row}-Q${row}`]);
  }
  fundSheet.getRange(`C2:C${fundEnd}`).formulas = changeFormulas;
  fundSheet.getRange(`I2:I${fundEnd}`).formulas = rankChange;
  fundSheet.getRange(`L2:L${fundEnd}`).formulas = sharesChange;
  fundSheet.getRange(`M2:M${fundEnd}`).formulas = sharesPct;
  fundSheet.getRange(`P2:P${fundEnd}`).formulas = marketChange;
  fundSheet.getRange(`S2:S${fundEnd}`).formulas = navChange;
  fundSheet.getRange(`A2:A${fundEnd}`).format.numberFormat = "000000";
  fundSheet.getRange(`J2:L${fundEnd}`).format.numberFormat = "#,##0.00;[Red](#,##0.00);-";
  fundSheet.getRange(`M2:M${fundEnd}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  fundSheet.getRange(`N2:P${fundEnd}`).format.numberFormat = "#,##0.00;[Red](#,##0.00);-";
  fundSheet.getRange(`Q2:S${fundEnd}`).format.numberFormat = "0.00%;[Red](0.00%);-";
  applyChangeFormatting(fundSheet, `A2:S${fundEnd}`, "C");
}

const industryHeaders = ["变化类型", "申万一级行业", "上期涉及基金数", "本期涉及基金数", "上期重仓记录数", "本期重仓记录数", "记录数变化", "上期市值(万元)", "本期市值(万元)", "市值变化(万元)", "上期净值比例合计", "本期净值比例合计", "净值比例变化", "上期基金代码", "本期基金代码"];
const industryRows = data.industry_changes.map((row) => ({
  "变化类型": "",
  "申万一级行业": row.sw_level1,
  "上期涉及基金数": row.previous_fund_count,
  "本期涉及基金数": row.current_fund_count,
  "上期重仓记录数": row.previous_holding_count,
  "本期重仓记录数": row.current_holding_count,
  "记录数变化": "",
  "上期市值(万元)": row.previous_market_value_10k,
  "本期市值(万元)": row.current_market_value_10k,
  "市值变化(万元)": "",
  "上期净值比例合计": row.previous_nav_ratio_sum,
  "本期净值比例合计": row.current_nav_ratio_sum,
  "净值比例变化": "",
  "上期基金代码": row.previous_fund_codes,
  "本期基金代码": row.current_fund_codes,
}));
const industrySheet = addTableSheet("行业变化", industryHeaders, industryRows, {
  "变化类型": 18, "申万一级行业": 18, "上期涉及基金数": 16, "本期涉及基金数": 16, "上期重仓记录数": 16, "本期重仓记录数": 16, "记录数变化": 14,
  "上期市值(万元)": 18, "本期市值(万元)": 18, "市值变化(万元)": 18, "上期净值比例合计": 20, "本期净值比例合计": 20, "净值比例变化": 18,
  "上期基金代码": 24, "本期基金代码": 24,
});
if (industryRows.length) {
  const changeFormulas = [], countChange = [], marketChange = [], navChange = [];
  for (let row = 2; row <= industryEnd; row += 1) {
    changeFormulas.push([`=IF(E${row}=0,"新进入前十行业",IF(F${row}=0,"退出前十行业",IF(M${row}>0.0001,"上升",IF(M${row}<-0.0001,"下降","持平"))))`]);
    countChange.push([`=F${row}-E${row}`]);
    marketChange.push([`=I${row}-H${row}`]);
    navChange.push([`=L${row}-K${row}`]);
  }
  industrySheet.getRange(`A2:A${industryEnd}`).formulas = changeFormulas;
  industrySheet.getRange(`G2:G${industryEnd}`).formulas = countChange;
  industrySheet.getRange(`J2:J${industryEnd}`).formulas = marketChange;
  industrySheet.getRange(`M2:M${industryEnd}`).formulas = navChange;
  industrySheet.getRange(`H2:J${industryEnd}`).format.numberFormat = "#,##0.00;[Red](#,##0.00);-";
  industrySheet.getRange(`K2:M${industryEnd}`).format.numberFormat = "0.00%;[Red](0.00%);-";
  industrySheet.getRange(`N2:O${industryEnd}`).format.numberFormat = "000000";
  const range = industrySheet.getRange(`A2:O${industryEnd}`);
  range.conditionalFormats.addCustom('=$A2="新进入前十行业"', { fill: green, font: { color: "#375623", bold: true } });
  range.conditionalFormats.addCustom('=$A2="上升"', { fill: blue, font: { color: "#1F4E78" } });
  range.conditionalFormats.addCustom('=$A2="下降"', { fill: amber, font: { color: "#7F6000" } });
  range.conditionalFormats.addCustom('=$A2="退出前十行业"', { fill: red, font: { color: "#9C0006" } });
}

const checkRows = data.checks.map((row) => ({ "检查项": row.item, "实际值": row.actual, "预期值": row.expected, "状态": row.status, "说明": row.note }));
const checksSheet = addTableSheet("数据质量", ["检查项", "实际值", "预期值", "状态", "说明"], checkRows, { "检查项": 28, "实际值": 20, "预期值": 18, "状态": 14, "说明": 80 });
checksSheet.getRange(`A2:E${checkRows.length + 1}`).format.wrapText = true;
checksSheet.getRange(`A2:E${checkRows.length + 1}`).conditionalFormats.addCustom('=$D2="OK"', { fill: green, font: { color: "#375623", bold: true } });
checksSheet.getRange(`A2:E${checkRows.length + 1}`).conditionalFormats.addCustom('=$D2="限制"', { fill: amber, font: { color: "#7F6000", bold: true } });
checksSheet.getRange(`A2:E${checkRows.length + 1}`).conditionalFormats.addCustom('=$D2="CHECK"', { fill: red, font: { color: "#9C0006", bold: true } });

const ruleRows = data.rules.map((row) => ({ "项目": row.item, "确定性规则": row.rule }));
const rulesSheet = addTableSheet("比较口径", ["项目", "确定性规则"], ruleRows, { "项目": 28, "确定性规则": 110 });
rulesSheet.getRange(`A2:B${ruleRows.length + 1}`).format.wrapText = true;

const sourceRows = [
  ...data.sources.map((row) => ({ "来源项目": row.item, "报告期": dateValue(row.report_date), "本地审计文件": row.path, "公开来源": "" })),
  { "来源项目": "季度前十大持仓", "报告期": "", "本地审计文件": "", "公开来源": "https://fundf10.eastmoney.com/FundArchivesDatas.aspx" },
  { "来源项目": "申万行业当前快照", "报告期": dateValue(s.industry_snapshot_date), "本地审计文件": "", "公开来源": "https://legulegu.com/stockdata/sw-industry-overview" },
];
const sourceSheet = addTableSheet("来源与审计", ["来源项目", "报告期", "本地审计文件", "公开来源"], sourceRows, { "来源项目": 28, "报告期": 16, "本地审计文件": 105, "公开来源": 70 });
sourceSheet.getRange(`B2:B${sourceRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
sourceSheet.getRange(`A2:D${sourceRows.length + 1}`).format.wrapText = true;

// Cross-sheet formulas are written only after all referenced worksheets exist.
summary.getRange("E4:E9").formulas = [
  [`=COUNTA('公司变化汇总'!$B$2:$B$${companyEnd})`],
  [`=COUNTIF('公司变化汇总'!$A$2:$A$${companyEnd},"新进")`],
  [`=COUNTIF('公司变化汇总'!$A$2:$A$${companyEnd},"退出")`],
  [`=COUNTIF('公司变化汇总'!$A$2:$A$${companyEnd},"增持")`],
  [`=COUNTIF('公司变化汇总'!$A$2:$A$${companyEnd},"减持")`],
  [`=COUNTIF('公司变化汇总'!$A$2:$A$${companyEnd},"持平")`],
];
summary.getRange("H4:H9").formulas = [
  [`=COUNTA('行业变化'!$B$2:$B$${industryEnd})`],
  [`=COUNTIF('行业变化'!$A$2:$A$${industryEnd},"新进入前十行业")`],
  [`=COUNTIF('行业变化'!$A$2:$A$${industryEnd},"退出前十行业")`],
  [`=COUNTIF('行业变化'!$A$2:$A$${industryEnd},"上升")`],
  [`=COUNTIF('行业变化'!$A$2:$A$${industryEnd},"下降")`],
  [`=COUNTIF('行业变化'!$A$2:$A$${industryEnd},"持平")`],
];

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const previewRanges = {
  "运行摘要": "A1:H14",
  "公司变化汇总": `A1:V${Math.min(companyEnd, 25)}`,
  "基金内持仓变化": `A1:S${Math.min(fundEnd, 25)}`,
  "行业变化": `A1:O${Math.min(industryEnd, 35)}`,
  "数据质量": `A1:E${Math.min(checkRows.length + 1, 25)}`,
  "比较口径": `A1:B${Math.min(ruleRows.length + 1, 20)}`,
  "来源与审计": `A1:D${Math.min(sourceRows.length + 1, 30)}`,
};
for (const [sheetName, range] of Object.entries(previewRanges)) {
  const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}

const summaryCheck = await workbook.inspect({ kind: "table", range: "运行摘要!A1:H14", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 });
console.log(summaryCheck.ndjson);
const companyCheck = await workbook.inspect({ kind: "table", range: `公司变化汇总!A1:V${Math.min(companyEnd, 12)}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 24 });
console.log(companyCheck.ndjson);
const industryCheck = await workbook.inspect({ kind: "table", range: `行业变化!A1:O${industryEnd}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 18 });
console.log(industryCheck.ndjson);
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errorCheck.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX=${outputPath}`);
