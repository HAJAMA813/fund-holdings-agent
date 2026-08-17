import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) throw new Error("usage: build_manager_fund_pool.mjs data.json output.xlsx preview_dir");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const navy = "#17365D", teal = "#1F7A8C", pale = "#EAF2F8", red = "#FCE8E6", amber = "#FFF4CC";

function colName(index) {
  let n = index + 1, out = "";
  while (n) { const rem = (n - 1) % 26; out = String.fromCharCode(65 + rem) + out; n = Math.floor((n - 1) / 26); }
  return out;
}

function addTableSheet(name, headers, rows, widths = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [headers, ...rows.map(row => headers.map(header => row[header] ?? ""))];
  const address = `A1:${colName(headers.length - 1)}${matrix.length}`;
  sheet.getRange(address).values = matrix;
  sheet.getRange(`A1:${colName(headers.length - 1)}1`).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true, verticalAlignment: "center" };
  sheet.getRange(address).format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EC" } };
  sheet.freezePanes.freezeRows(1);
  headers.forEach((header, i) => { sheet.getRangeByIndexes(0, i, matrix.length, 1).format.columnWidth = widths[header] ?? 16; });
  if (rows.length) sheet.tables.add(address, true, `${name.replace(/[^A-Za-z0-9]/g, "")}Table${workbook.worksheets.items.length}`);
  return sheet;
}

function dateValue(value) { return value ? new Date(`${value}T00:00:00Z`) : ""; }
const s = data.summary;
const summary = workbook.worksheets.add("运行摘要");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["基金经理报告期基金池运行摘要"]];
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 32, verticalAlignment: "center" };
summary.getRange("A3:B12").values = [
  ["基金经理", s.manager], ["天天基金经理ID", s.manager_id], ["基金公司", s.company], ["报告期", dateValue(s.report_date)],
  ["历史任职份额数", s.historical_share_count], ["报告期在任份额数", s.active_share_count], ["最终纳入份额数", s.selected_share_count],
  ["基础产品数（未去重）", s.product_count], ["经理历史核验通过", s.verified_count], ["运行状态", s.error_count === 0 ? "通过" : "有错误，需复核"],
];
summary.getRange("D3:E6").values = [["异常指标", "数量"], ["错误", s.error_count], ["警告", s.warning_count], ["异常合计", s.error_count + s.warning_count]];
summary.getRange("A3:A12").format = { fill: pale, font: { bold: true } };
summary.getRange("D3:E3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("B6").format.numberFormat = "yyyy-mm-dd";
summary.getRange("A3:E12").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("A14:H16").merge();
summary.getRange("A14").values = [["口径：以基金经理档案中的完整历史任职区间建立报告期基金池，再用单只基金基本信息与经理变动历史交叉核验。A/C/E 等份额本表全部保留；持仓抓取后再按同一基础产品去重。"]];
summary.getRange("A14:H16").format = { fill: "#F3F6F9", wrapText: true, verticalAlignment: "center" };
summary.getRange("A:A").format.columnWidth = 25; summary.getRange("B:B").format.columnWidth = 28; summary.getRange("C:C").format.columnWidth = 4; summary.getRange("D:D").format.columnWidth = 20; summary.getRange("E:E").format.columnWidth = 18;

const fundHeaders = ["基金代码","基金名称","基础产品名称","产品组","基金类型","任职开始","任职结束","报告期在任","成立日期","报告期核实经理","核验状态","是否纳入","筛选结论","经理档案来源","基本信息来源","经理历史来源"];
function fundRows(rows) { return rows.map(r => ({
  "基金代码":r.fund_code,"基金名称":r.fund_name,"基础产品名称":r.product_base_name,"产品组":r.product_group,"基金类型":r.fund_type,
  "任职开始":dateValue(r.tenure_start),"任职结束":dateValue(r.tenure_end),"报告期在任":r.active_on_report_date?"是":"否","成立日期":dateValue(r.inception_date),
  "报告期核实经理":r.verified_manager,"核验状态":r.manager_verification,"是否纳入":r.selected?"是":"否","筛选结论":r.selection_reason,
  "经理档案来源":r.manager_profile_url,"基本信息来源":r.fund_info_url,"经理历史来源":r.manager_history_url,
})); }
const widths = {"基金代码":12,"基金名称":32,"基础产品名称":30,"产品组":14,"基金类型":20,"任职开始":14,"任职结束":14,"报告期在任":12,"成立日期":14,"报告期核实经理":20,"核验状态":14,"是否纳入":12,"筛选结论":28,"经理档案来源":55,"基本信息来源":55,"经理历史来源":55};
const selected = addTableSheet("报告期基金池", fundHeaders, fundRows(data.selected_funds), widths);
const history = addTableSheet("全部任职历史", fundHeaders, fundRows(data.all_tenures), widths);
for (const sheet of [selected, history]) {
  const count = Math.max(2, sheet.getUsedRange().values.length);
  sheet.getRange(`A2:A${count}`).format.numberFormat = "000000";
  sheet.getRange(`F2:G${count}`).format.numberFormat = "yyyy-mm-dd";
  sheet.getRange(`I2:I${count}`).format.numberFormat = "yyyy-mm-dd";
}

const issueHeaders = ["级别","分类","基金代码","基金名称","基金经理","报告期","问题说明","来源URL","建议处理"];
const issueRows = data.issues.map(r => ({"级别":r.severity,"分类":r.category,"基金代码":r.fund_code,"基金名称":r.fund_name,"基金经理":r.manager,"报告期":dateValue(r.report_date),"问题说明":r.message,"来源URL":r.source_url,"建议处理":r.action}));
const issues = addTableSheet("核验与异常", issueHeaders, issueRows, {"级别":10,"分类":22,"基金代码":12,"基金名称":30,"基金经理":16,"报告期":14,"问题说明":60,"来源URL":65,"建议处理":34});
if (issueRows.length) {
  issues.getRange(`F2:F${issueRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
  issues.getRange(`A2:I${issueRows.length + 1}`).format.wrapText = true;
  issues.getRange(`A2:I${issueRows.length + 1}`).conditionalFormats.addCustom('=$A2="错误"', { fill: red, font: { color: "#9C0006" } });
  issues.getRange(`A2:I${issueRows.length + 1}`).conditionalFormats.addCustom('=$A2="警告"', { fill: amber });
}

const sourceRows = [
  {"来源ID":"口径","来源名称":"报告期基金池规则","用途":"任职开始 ≤ 报告期 ≤ 任职结束；‘至今’视为开放区间。经理档案是主来源，单基金页面用于交叉核验。","URL":""},
  {"来源ID":"去重","来源名称":"份额处理规则","用途":"本步骤保留全部 A/C/E 份额并标注基础产品组；待持仓抓取后再确定代表份额。","URL":""},
  {"来源ID":"模型","来源名称":"确定性执行说明","用途":"本阶段未调用 DeepSeek API 或其他大模型。","URL":""},
  ...data.sources.map(r => ({"来源ID":r.source_id,"来源名称":r.name,"用途":r.purpose,"URL":r.url})),
];
const sources = addTableSheet("来源与口径", ["来源ID","来源名称","用途","URL"], sourceRows, {"来源ID":12,"来源名称":28,"用途":70,"URL":65});
sources.getRange(`A2:D${sourceRows.length + 1}`).format.wrapText = true;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
for (const sheetName of ["运行摘要","报告期基金池","全部任职历史","核验与异常","来源与口径"]) {
  const image = await workbook.render({ sheetName, autoCrop:"all", scale:1, format:"png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}
const check = await workbook.inspect({ kind:"table", range:"运行摘要!A1:H16", include:"values,formulas", tableMaxRows:20, tableMaxCols:10 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind:"match", searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options:{ useRegex:true, maxResults:100 }, summary:"final formula error scan" });
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX=${outputPath}`);
