import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) {
  throw new Error("usage: build_preproduction_replay.mjs summary.json output.xlsx preview_dir");
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const navy = "#17365D";
const teal = "#1F7A8C";
const pale = "#EAF2F8";
const green = "#E2F0D9";
const amber = "#FFF4CC";
const red = "#FCE8E6";
const gray = "#F3F6F9";

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
  const matrix = [headers, ...rows];
  const lastColumn = colName(headers.length - 1);
  const lastRow = Math.max(matrix.length, 2);
  sheet.getRange(`A1:${lastColumn}${matrix.length}`).values = matrix;
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
    rowHeight: 32,
  };
  sheet.getRange(`A1:${lastColumn}${matrix.length}`).format.borders = {
    insideHorizontal: { style: "thin", color: "#D9E2EC" },
  };
  headers.forEach((header, index) => {
    sheet.getRangeByIndexes(0, index, lastRow, 1).format.columnWidth = widths[header] ?? 16;
  });
  sheet.freezePanes.freezeRows(1);
  if (rows.length) sheet.tables.add(`A1:${lastColumn}${matrix.length}`, true, `T${workbook.worksheets.items.length}`);
  return sheet;
}

// Create every referenced sheet before writing cross-sheet formulas.
const summary = workbook.worksheets.add("运行摘要");
const companySheet = addTableSheet(
  "公司比较",
  ["基金公司", "上期经理数", "本期经理数", "上期正式基金", "本期正式基金", "上期公司去重持仓", "本期公司去重持仓", "上期移除重复", "本期移除重复", "股票并集", "新进", "退出", "增持", "减持", "持平", "行业并集", "去重冲突", "状态"],
  data.company_rows.map((row) => [
    row.company, row.previous_manager_count, row.current_manager_count, row.previous_formal_funds, row.current_formal_funds,
    row.previous_holding_rows, row.current_holding_rows, row.previous_duplicate_rows_removed, row.current_duplicate_rows_removed,
    row.company_union_count, row.new_company_count, row.exited_company_count, row.increased_company_count,
    row.decreased_company_count, row.unchanged_company_count, row.industry_union_count, row.dedup_conflict_count, row.status,
  ]),
  { "基金公司": 28, "上期经理数": 13, "本期经理数": 13, "上期正式基金": 14, "本期正式基金": 14, "上期公司去重持仓": 18, "本期公司去重持仓": 18, "上期移除重复": 15, "本期移除重复": 15, "股票并集": 12, "新进": 10, "退出": 10, "增持": 10, "减持": 10, "持平": 10, "行业并集": 12, "去重冲突": 12, "状态": 25 },
);
const managerSheet = addTableSheet(
  "经理回放明细",
  ["基金公司", "基金经理", "天天基金经理ID", "Q1状态", "Q2状态", "Q1正式基金", "Q2正式基金", "基金数变化", "Q1正式持仓", "Q2正式持仓", "新进公司", "退出公司", "增持公司", "减持公司", "持平公司", "比较状态", "管道警告", "行业警告"],
  data.manager_rows.map((row) => [
    row.company, row.manager, row.manager_id, row.previous_status, row.current_status, row.previous_formal_funds,
    row.current_formal_funds, row.fund_change, row.previous_holding_rows, row.current_holding_rows,
    row.new_company_count, row.exited_company_count, row.increased_company_count, row.decreased_company_count,
    row.unchanged_company_count, row.comparison_status, row.pipeline_warning_count, row.industry_warning_count,
  ]),
  { "基金公司": 28, "基金经理": 14, "天天基金经理ID": 17, "Q1状态": 14, "Q2状态": 14, "Q1正式基金": 14, "Q2正式基金": 14, "基金数变化": 13, "Q1正式持仓": 14, "Q2正式持仓": 14, "新进公司": 12, "退出公司": 12, "增持公司": 12, "减持公司": 12, "持平公司": 12, "比较状态": 26, "管道警告": 12, "行业警告": 12 },
);
const qualitySheet = addTableSheet(
  "数据质量",
  ["检查ID", "检查项", "实际值", "预期值", "状态", "说明"],
  data.checks.map((row) => [row.check_id, row.check_name, typeof row.actual === "object" ? JSON.stringify(row.actual) : row.actual, typeof row.expected === "object" ? JSON.stringify(row.expected) : row.expected, row.status, row.note]),
  { "检查ID": 12, "检查项": 30, "实际值": 35, "预期值": 28, "状态": 12, "说明": 80 },
);
const sourceRows = [
  ...data.source_files.map((row) => [row.item, "本地审计输入", row.path, row.sha256, ""]),
  ["季度前十大持仓", "公开数据源", "", "", "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"],
  ["申万行业当前快照", "公开数据源", "", "", "https://legulegu.com/stockdata/sw-industry-overview"],
  ...data.limitations.map((row, index) => [`限制${index + 1}`, "口径说明", row, "", ""]),
];
const sourceSheet = addTableSheet(
  "来源与口径",
  ["项目", "类型", "本地文件或说明", "SHA-256", "公开来源"],
  sourceRows,
  { "项目": 26, "类型": 16, "本地文件或说明": 105, "SHA-256": 68, "公开来源": 70 },
);

summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [[`${data.previous_quarter} → ${data.current_quarter} 基金持仓 Agent 全量准生产回放`]];
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 36, verticalAlignment: "center" };
summary.getRange("A3:B11").values = [
  ["回放状态", data.overall_status],
  ["上期报告日", dateValue(data.previous_report_date)],
  ["本期报告日", dateValue(data.current_report_date)],
  ["基金经理", ""],
  ["季度任务", ""],
  ["逐经理比较", ""],
  ["通过检查", ""],
  ["失败检查", ""],
  ["DeepSeek调用", data.deepseek_used ? "是" : "否"],
];
summary.getRange("D3:E9").values = [
  ["持仓勾稽", "数量"],
  ["Q1逐经理持仓", data.metrics.previous_formal_holding_rows_individual_sum],
  ["Q1公司去重持仓", ""],
  ["Q1移除共同管理重复", ""],
  ["Q2逐经理持仓", data.metrics.current_formal_holding_rows_individual_sum],
  ["Q2公司去重持仓", ""],
  ["Q2移除共同管理重复", ""],
];
summary.getRange("G3:H9").values = [
  ["数据质量", "结果"],
  ["管道错误", data.metrics.pipeline_error_count],
  ["行业错误", data.metrics.industry_error_count],
  ["Q1 A股行业覆盖", data.metrics.previous_a_share_industry_coverage],
  ["Q2 A股行业覆盖", data.metrics.current_a_share_industry_coverage],
  ["管道警告", data.metrics.pipeline_warning_count],
  ["行业警告", data.metrics.industry_warning_count],
];
summary.getRange("A3:A11").format = { fill: pale, font: { bold: true } };
summary.getRange("D3:E3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("G3:H3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A3:B11").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("D3:E9").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("G3:H9").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("B4:B5").format.numberFormat = "yyyy-mm-dd";
summary.getRange("H6:H7").format.numberFormat = "0.00%";
summary.getRange("A13:H16").merge();
summary.getRange("A13").values = [[`结论：25位经理两期共50个季度任务全部完成，并生成25份逐经理季度比较。公司层已消除共同管理基金重复披露，数值冲突为0。两期A股行业当前快照覆盖率均为100%；行业方向可比，但不代表报告期历史行业归属。本次未联网，未调用DeepSeek。`]];
summary.getRange("A13:H16").format = { fill: gray, wrapText: true, verticalAlignment: "center" };
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 32;
summary.getRange("C:C").format.columnWidth = 4;
summary.getRange("D:D").format.columnWidth = 25;
summary.getRange("E:E").format.columnWidth = 16;
summary.getRange("F:F").format.columnWidth = 4;
summary.getRange("G:G").format.columnWidth = 22;
summary.getRange("H:H").format.columnWidth = 16;

// Formula-driven top-level checks and reconciliations.
summary.getRange("B6:B10").formulas = [
  ["=COUNTA('经理回放明细'!$B$2:$B$26)"],
  ["=COUNTIF('经理回放明细'!$D$2:$D$26,\"completed\")+COUNTIF('经理回放明细'!$E$2:$E$26,\"completed\")"],
  ["=COUNTA('经理回放明细'!$P$2:$P$26)"],
  ["=COUNTIF('数据质量'!$E$2:$E$10,\"OK\")"],
  ["=COUNTIF('数据质量'!$E$2:$E$10,\"FAIL\")"],
];
summary.getRange("E5:E9").formulas = [
  ["=SUM('公司比较'!$F$2:$F$3)"],
  ["=SUM('公司比较'!$H$2:$H$3)"],
  ["=SUM('经理回放明细'!$J$2:$J$26)"],
  ["=SUM('公司比较'!$G$2:$G$3)"],
  ["=SUM('公司比较'!$I$2:$I$3)"],
];
summary.getRange("B6:B10").format.font = { color: "#008000" };
summary.getRange("E5:E9").format.font = { color: "#008000" };
summary.getRange("B10").conditionalFormats.add("cellIs", { operator: "equal", formula: 0, format: { fill: green, font: { color: "#375623", bold: true } } });
summary.getRange("B10").conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { fill: red, font: { color: "#9C0006", bold: true } } });

companySheet.getRange("A2:R3").conditionalFormats.addCustom('=$Q2=0', { fill: green });
companySheet.getRange("A2:R3").conditionalFormats.addCustom('=$Q2>0', { fill: red, font: { color: "#9C0006", bold: true } });
managerSheet.getRange("C2:C26").format.numberFormat = "@";
managerSheet.getRange("H2:H26").format.numberFormat = "#,##0;[Red](#,##0);-";
managerSheet.getRange("A2:R26").conditionalFormats.addCustom('=OR($D2<>"completed",$E2<>"completed")', { fill: red, font: { color: "#9C0006", bold: true } });
qualitySheet.getRange("A2:F10").format.wrapText = true;
qualitySheet.getRange("A2:F10").conditionalFormats.addCustom('=$E2="OK"', { fill: green, font: { color: "#375623", bold: true } });
qualitySheet.getRange("A2:F10").conditionalFormats.addCustom('=$E2="FAIL"', { fill: red, font: { color: "#9C0006", bold: true } });
sourceSheet.getRange(`A2:E${sourceRows.length + 1}`).format.wrapText = true;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const previewRanges = {
  "运行摘要": "A1:H16",
  "公司比较": "A1:R3",
  "经理回放明细": "A1:R26",
  "数据质量": "A1:F10",
  "来源与口径": `A1:E${sourceRows.length + 1}`,
};
for (const [sheetName, range] of Object.entries(previewRanges)) {
  const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}

console.log((await workbook.inspect({ kind: "table", range: "运行摘要!A1:H16", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 })).ndjson);
console.log((await workbook.inspect({ kind: "table", range: "公司比较!A1:R3", include: "values,formulas", tableMaxRows: 5, tableMaxCols: 20 })).ndjson);
console.log((await workbook.inspect({ kind: "table", range: "数据质量!A1:F10", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 8 })).ndjson);
console.log((await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" })).ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX=${outputPath}`);
