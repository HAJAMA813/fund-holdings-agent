import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) throw new Error("usage: build_report.mjs data.json output.xlsx preview_dir");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const navy = "#17365D";
const teal = "#1F7A8C";
const pale = "#EAF2F8";
const red = "#FCE8E6";
const amber = "#FFF4CC";

function colName(index) {
  let n = index + 1, out = "";
  while (n) { const rem = (n - 1) % 26; out = String.fromCharCode(65 + rem) + out; n = Math.floor((n - 1) / 26); }
  return out;
}

function dateValue(value) { return value ? new Date(`${value}T00:00:00Z`) : ""; }

function addTableSheet(name, headers, rows, widths = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [headers, ...rows.map(row => headers.map(header => row[header] ?? ""))];
  const address = `A1:${colName(headers.length - 1)}${matrix.length}`;
  sheet.getRange(address).values = matrix;
  sheet.getRange(`A1:${colName(headers.length - 1)}1`).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true, verticalAlignment: "center" };
  sheet.getRange(address).format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EC" } };
  sheet.freezePanes.freezeRows(1);
  headers.forEach((header, index) => { sheet.getRangeByIndexes(0, index, matrix.length, 1).format.columnWidth = widths[header] ?? 15; });
  if (rows.length) sheet.tables.add(address, true, `${name.replace(/[^A-Za-z0-9]/g, "")}Table${workbook.worksheets.items.length}`);
  return sheet;
}

const s = data.summary;
const iq = data.industry_quality;
const hasIndustry = Boolean(iq && data.formal_holdings_industry);
const summary = workbook.worksheets.add("运行摘要");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["基金季度前十大重仓运行摘要"]];
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 32, verticalAlignment: "center" };
summary.getRange("A3:B10").values = [
  ["报告期", new Date(`${s.report_date}T00:00:00Z`)], ["输入基金数", s.input_funds], ["筛选后基金数", s.selected_funds], ["成功抓取基金数", s.successful_funds],
  ["正式版代表基金数", s.formal_funds], ["全量持仓行数", s.raw_holding_rows], ["正式版持仓行数", s.formal_holding_rows], ["成功率", s.success_rate],
];
summary.getRange(hasIndustry ? "D3:E11" : "D3:E7").values = hasIndustry ? [
  ["质量指标", "结果"], ["持仓错误", s.error_count], ["持仓警告", s.warning_count], ["行业错误", iq.error_count], ["行业警告", iq.warning_count],
  ["行业覆盖率", iq.holding_coverage], ["唯一股票覆盖", `${iq.unique_stock_mapped}/${iq.unique_stock_count}`], ["行业时点", iq.historical_point_in_time ? "报告期历史口径" : "当前快照（有限制）"], ["运行结论", s.error_count === 0 && iq.error_count === 0 ? "持仓通过；行业快照需留意时点" : "存在错误，需核查"],
] : [["质量指标", "数量"], ["错误", s.error_count], ["警告", s.warning_count], ["全部异常/提示", s.issue_count], ["运行结论", s.error_count === 0 && s.successful_funds === s.selected_funds ? "基础管道通过" : "存在未完成项，需核查"]];
summary.getRange("A3:A10").format = { fill: pale, font: { bold: true } };
summary.getRange("D3:E3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
if (hasIndustry) summary.getRange("E8").format.numberFormat = "0.0%";
summary.getRange("B10").format.numberFormat = "0.0%";
summary.getRange("B3").format.numberFormat = "yyyy-mm-dd";
summary.getRange("A3:E10").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("A12:H13").merge();
summary.getRange("A12").values = [[hasIndustry ? "说明：正式版只保留重复份额中的代表份额。行业分类采用申万行业分类标准2021，但本次为当前公开快照，不等同于报告期历史成分；详见“行业数据质量”和“行业异常”。" : "说明：正式版只保留 A/C/E 等重复份额中的代表份额；全量底稿保留所有原始份额。错误与警告请到“异常清单”核查。"]];
summary.getRange("A12:H13").format = { fill: "#F3F6F9", wrapText: true, verticalAlignment: "center" };
summary.getRange("A:A").format.columnWidth = 24; summary.getRange("B:B").format.columnWidth = 18; summary.getRange("C:C").format.columnWidth = 4; summary.getRange("D:D").format.columnWidth = 24; summary.getRange("E:E").format.columnWidth = 22;

const holdingHeaders = ["fund_code","fund_name","manager","report_date","rank","stock_code","stock_name","shares_10k","market_value_10k","nav_ratio","market","duplicate_group","representative","source_url"];
const holdingLabels = {fund_code:"基金代码",fund_name:"基金名称",manager:"基金经理",report_date:"报告期",rank:"序号",stock_code:"股票代码",stock_name:"股票名称",shares_10k:"持股数量(万股)",market_value_10k:"持仓市值(万元)",nav_ratio:"占基金净值比例",market:"市场/地区",duplicate_group:"重复组",representative:"去重代表",source_url:"数据来源URL"};
function labeled(rows) { return rows.map(row => Object.fromEntries(holdingHeaders.map(key => [holdingLabels[key], key === "report_date" && row[key] ? new Date(`${row[key]}T00:00:00Z`) : (row[key] ?? "")]))); }
const labeledHeaders = holdingHeaders.map(key => holdingLabels[key]);
const widths = {"基金代码":12,"基金名称":30,"基金经理":16,"报告期":14,"序号":8,"股票代码":16,"股票名称":22,"持股数量(万股)":16,"持仓市值(万元)":18,"占基金净值比例":16,"市场/地区":14,"重复组":12,"去重代表":12,"数据来源URL":70};
const formal = addTableSheet("正式版_持仓明细", labeledHeaders, labeled(data.formal_holdings), widths);
const raw = addTableSheet("全量抓取底稿", labeledHeaders, labeled(data.all_holdings), widths);
for (const sheet of [formal, raw]) {
  const rows = Math.max(2, sheet.getUsedRange().values.length);
  sheet.getRange(`A2:A${rows}`).format.numberFormat = "000000";
  sheet.getRange(`H2:I${rows}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`J2:J${rows}`).format.numberFormat = "0.00%";
  sheet.getRange(`D2:D${rows}`).format.numberFormat = "yyyy-mm-dd";
}

const fundHeaders = ["manager","fund_code","fund_name","fund_type","inception_date","selected","selection_reason","verified_manager","manager_status","fetch_status","manager_source_url"];
const fundLabels = {manager:"名单基金经理",fund_code:"基金代码",fund_name:"基金名称",fund_type:"基金类型",inception_date:"成立日期",selected:"是否纳入",selection_reason:"筛选原因",verified_manager:"报告期核实经理",manager_status:"经理核实状态",fetch_status:"抓取状态",manager_source_url:"经理核实URL"};
const fundRows = data.funds.map(row => Object.fromEntries(fundHeaders.map(key => [fundLabels[key], key === "selected" ? (row[key] ? "是" : "否") : (key === "inception_date" && row[key] ? new Date(`${row[key]}T00:00:00Z`) : (row[key] ?? ""))])));
const fundSheet = addTableSheet("基金名单与筛选", fundHeaders.map(key => fundLabels[key]), fundRows, {"名单基金经理":16,"基金代码":12,"基金名称":32,"基金类型":20,"成立日期":14,"是否纳入":12,"筛选原因":32,"报告期核实经理":20,"经理核实状态":16,"抓取状态":16,"经理核实URL":65});
if (fundRows.length) fundSheet.getRange(`E2:E${fundRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
if (fundRows.length) fundSheet.getRange(`B2:B${fundRows.length + 1}`).format.numberFormat = "000000";
if (fundRows.length) fundSheet.getRange(`G2:G${fundRows.length + 1}`).format.wrapText = true;

const issueLabels = {severity:"级别",category:"分类",fund_code:"基金代码",fund_name:"基金名称",manager:"名单基金经理",report_date:"报告期",message:"问题说明",source_url:"来源URL",action:"建议处理"};
const issueKeys = Object.keys(issueLabels);
const issueRows = data.issues.map(row => Object.fromEntries(issueKeys.map(key => [issueLabels[key], row[key] ?? ""])));
const issues = addTableSheet("异常清单", issueKeys.map(key => issueLabels[key]), issueRows, {"级别":10,"分类":22,"基金代码":12,"基金名称":30,"名单基金经理":18,"报告期":14,"问题说明":55,"来源URL":65,"建议处理":36});
if (issueRows.length) {
  issues.getRange(`C2:C${issueRows.length + 1}`).format.numberFormat = "000000";
  issues.getRange(`A2:I${issueRows.length + 1}`).format.wrapText = true;
  issues.getRange(`A2:I${issueRows.length + 1}`).conditionalFormats.addCustom('=$A2="错误"', { fill: red, font: { color: "#9C0006" } });
  issues.getRange(`A2:I${issueRows.length + 1}`).conditionalFormats.addCustom('=$A2="警告"', { fill: amber });
}

if (hasIndustry) {
  const detailHeaders = ["基金代码","基金名称","报告期","序号","股票代码","股票名称","市场/地区","持仓市值(万元)","占基金净值比例","申万一级行业","申万二级行业","分类快照日期","行业来源ID"];
  const detailRows = data.formal_holdings_industry.map(r => ({
    "基金代码":r.fund_code,"基金名称":r.fund_name,"报告期":dateValue(r.report_date),"序号":r.rank,"股票代码":r.stock_code,"股票名称":r.stock_name,"市场/地区":r.market,
    "持仓市值(万元)":r.market_value_10k,"占基金净值比例":r.nav_ratio,"申万一级行业":r.sw_level1,"申万二级行业":r.sw_level2,"分类快照日期":dateValue(r.industry_snapshot_date),"行业来源ID":r.industry_source_id,
  }));
  const detail = addTableSheet("正式持仓与行业", detailHeaders, detailRows, {"基金代码":12,"基金名称":30,"报告期":14,"序号":8,"股票代码":16,"股票名称":18,"市场/地区":12,"持仓市值(万元)":18,"占基金净值比例":18,"申万一级行业":16,"申万二级行业":20,"分类快照日期":16,"行业来源ID":14});
  detail.getRange(`A2:A${detailRows.length + 1}`).format.numberFormat = "000000";
  detail.getRange(`C2:C${detailRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
  detail.getRange(`H2:H${detailRows.length + 1}`).format.numberFormat = "#,##0.00";
  detail.getRange(`I2:I${detailRows.length + 1}`).format.numberFormat = "0.00%";
  detail.getRange(`L2:L${detailRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";

  const summaryHeaders = ["基金代码","基金名称","申万一级行业","重仓股数量","持仓市值合计(万元)","净值比例合计","前十持仓市值占比"];
  const industryRows = data.industry_summary.map(r => ({"基金代码":r.fund_code,"基金名称":r.fund_name,"申万一级行业":r.sw_level1,"重仓股数量":"","持仓市值合计(万元)":"","净值比例合计":"","前十持仓市值占比":""}));
  const industrySummary = addTableSheet("基金行业汇总", summaryHeaders, industryRows, {"基金代码":12,"基金名称":30,"申万一级行业":18,"重仓股数量":14,"持仓市值合计(万元)":20,"净值比例合计":18,"前十持仓市值占比":20});
  const detailEnd = detailRows.length + 1;
  const summaryEnd = industryRows.length + 1;
  const formulas = industryRows.map((_, index) => {
    const row = index + 2;
    return [
      `=COUNTIFS('正式持仓与行业'!$A$2:$A$${detailEnd},A${row},'正式持仓与行业'!$J$2:$J$${detailEnd},C${row})`,
      `=SUMIFS('正式持仓与行业'!$H$2:$H$${detailEnd},'正式持仓与行业'!$A$2:$A$${detailEnd},A${row},'正式持仓与行业'!$J$2:$J$${detailEnd},C${row})`,
      `=SUMIFS('正式持仓与行业'!$I$2:$I$${detailEnd},'正式持仓与行业'!$A$2:$A$${detailEnd},A${row},'正式持仓与行业'!$J$2:$J$${detailEnd},C${row})`,
      `=E${row}/SUMIF($A$2:$A$${summaryEnd},A${row},$E$2:$E$${summaryEnd})`,
    ];
  });
  industrySummary.getRange(`D2:G${summaryEnd}`).formulas = formulas;
  industrySummary.getRange(`A2:A${summaryEnd}`).format.numberFormat = "000000";
  industrySummary.getRange(`D2:D${summaryEnd}`).format.numberFormat = "#,##0";
  industrySummary.getRange(`E2:E${summaryEnd}`).format.numberFormat = "#,##0.00";
  industrySummary.getRange(`F2:G${summaryEnd}`).format.numberFormat = "0.00%";

  const mappingHeaders = ["行业来源ID","股票代码","股票名称","市场/地区","申万一级行业","申万二级行业","申万二级代码","分类快照日期","匹配状态","来源URL"];
  const mappingRows = data.stock_industry_mapping.map(r => ({"行业来源ID":r.industry_source_id,"股票代码":r.stock_code,"股票名称":r.stock_name,"市场/地区":r.market,"申万一级行业":r.sw_level1,"申万二级行业":r.sw_level2,"申万二级代码":r.sw_level2_code,"分类快照日期":dateValue(r.industry_snapshot_date),"匹配状态":r.classification_status,"来源URL":r.source_url}));
  const mapping = addTableSheet("股票行业映射", mappingHeaders, mappingRows, {"行业来源ID":14,"股票代码":16,"股票名称":18,"市场/地区":12,"申万一级行业":16,"申万二级行业":20,"申万二级代码":18,"分类快照日期":16,"匹配状态":18,"来源URL":60});
  mapping.getRange(`H2:H${mappingRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";

  const industryIssueRows = data.industry_issues.map(r => ({"级别":r.severity,"分类":r.category,"股票代码":r.stock_code,"股票名称":r.stock_name,"问题说明":r.message,"来源URL":r.source_url,"建议处理":r.action}));
  const industryIssues = addTableSheet("行业异常", ["级别","分类","股票代码","股票名称","问题说明","来源URL","建议处理"], industryIssueRows, {"级别":10,"分类":24,"股票代码":16,"股票名称":18,"问题说明":65,"来源URL":60,"建议处理":60});
  industryIssues.getRange(`A2:G${industryIssueRows.length + 1}`).format.wrapText = true;
  industryIssues.getRange(`A2:G${industryIssueRows.length + 1}`).conditionalFormats.addCustom('=$A2="错误"', { fill: red, font: { color: "#9C0006" } });
  industryIssues.getRange(`A2:G${industryIssueRows.length + 1}`).conditionalFormats.addCustom('=$A2="警告"', { fill: amber });

  const detailNav = data.formal_holdings_industry.reduce((sum, row) => sum + (row.nav_ratio || 0), 0);
  const summaryNav = data.industry_summary.reduce((sum, row) => sum + (row.nav_ratio || 0), 0);
  const qualityRows = [
    {"检查项":"正式持仓行业覆盖","实际值":iq.mapped_holding_rows,"预期值":iq.eligible_holding_rows,"差异":"","状态":"","说明":"A股正式持仓均应匹配申万行业"},
    {"检查项":"唯一股票行业覆盖","实际值":iq.unique_stock_mapped,"预期值":iq.unique_stock_count,"差异":"","状态":"","说明":"唯一股票代码不得因重复持仓重复计算"},
    {"检查项":"正式持仓行数衔接","实际值":data.formal_holdings_industry.length,"预期值":s.formal_holding_rows,"差异":"","状态":"","说明":"行业增强前后正式持仓行数应一致"},
    {"检查项":"行业明细/汇总净值比例勾稽","实际值":summaryNav,"预期值":detailNav,"差异":"","状态":"","说明":"跨基金净值比例相加仅用于明细与汇总勾稽，不代表组合行业暴露"},
    {"检查项":"报告期历史行业口径","实际值":iq.historical_point_in_time?"是":"否","预期值":"是","差异":"不适用","状态":"限制","说明":"本次采用当前快照；生产历史口径需使用带纳入/剔除日期的数据源"},
  ];
  const quality = addTableSheet("行业数据质量", ["检查项","实际值","预期值","差异","状态","说明"], qualityRows, {"检查项":28,"实际值":18,"预期值":18,"差异":16,"状态":14,"说明":70});
  quality.getRange("D2:D5").formulas = [["=B2-C2"],["=B3-C3"],["=B4-C4"],["=B5-C5"]];
  quality.getRange("E2:E5").formulas = [["=IF(ABS(D2)<0.000001,\"OK\",\"CHECK\")"],["=IF(ABS(D3)<0.000001,\"OK\",\"CHECK\")"],["=IF(ABS(D4)<0.000001,\"OK\",\"CHECK\")"],["=IF(ABS(D5)<0.000001,\"OK\",\"CHECK\")"]];
  quality.getRange("B5:D5").format.numberFormat = "0.00%";
  quality.getRange("A2:F6").format.wrapText = true;
  quality.getRange("E2:E6").conditionalFormats.addCustom('=$E2="OK"', { fill: "#E2F0D9", font: { color: "#375623", bold: true } });
  quality.getRange("E2:E6").conditionalFormats.addCustom('=$E2="限制"', { fill: amber, font: { bold: true } });
}

const sourceRows = [
  {项目:"报告期",说明:s.report_date},
  {项目:"持仓口径",说明:"正式版为全市场有效持仓口径，包含A股、港股和美股/海外；原始份额均保留在全量抓取底稿。"},
  {项目:"份额去重",说明:"按基础基金名称 + 前十大股票代码序列分组；A > 无后缀 > E/D/H/I/Y/Z/B > C。"},
  {项目:"异常规则",说明:"请求失败、空持仓、经理不一致、字段缺失进入异常清单；1-9条按实际披露保留并提示。"},
  {项目:"模型调用",说明:"本阶段未调用 DeepSeek 或其他大模型，全部结论由确定性规则产生。"},
  ...data.sources.map(row => ({项目:row.item,说明:`${row.note}；${row.url}`})),
  ...(data.industry_sources ?? []).map(row => ({项目:row.item,说明:`${row.note}；${row.url}`})),
];
const sources = addTableSheet("来源与口径", ["项目","说明"], sourceRows, {项目:24,说明:105});
sources.getRange(`A2:B${sourceRows.length + 1}`).format.wrapText = true;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const previewSheets = ["运行摘要","正式版_持仓明细","全量抓取底稿","基金名单与筛选","异常清单",...(hasIndustry?["正式持仓与行业","基金行业汇总","股票行业映射","行业异常","行业数据质量"]:[]),"来源与口径"];
for (const sheetName of previewSheets) {
  const image = await workbook.render({sheetName, autoCrop:"all", scale:1, format:"png"});
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}
const check = await workbook.inspect({kind:"table", range:"运行摘要!A1:H13", include:"values,formulas", tableMaxRows:20, tableMaxCols:10});
console.log(check.ndjson);
if (hasIndustry) {
  const industryCheck = await workbook.inspect({kind:"table", range:`基金行业汇总!A1:G${data.industry_summary.length + 1}`, include:"values,formulas", tableMaxRows:20, tableMaxCols:10});
  console.log(industryCheck.ndjson);
  const qualityCheck = await workbook.inspect({kind:"table", range:"行业数据质量!A1:F6", include:"values,formulas", tableMaxRows:10, tableMaxCols:8});
  console.log(qualityCheck.ndjson);
}
const errors = await workbook.inspect({kind:"match", searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options:{useRegex:true,maxResults:100}, summary:"final formula error scan"});
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX=${outputPath}`);
