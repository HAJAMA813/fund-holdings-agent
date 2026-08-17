import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) {
  throw new Error("usage: build_resource_report.mjs resource_matching_data.json output.xlsx preview_dir");
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const navy = "#17365D";
const teal = "#1F7A8C";
const pale = "#EAF2F8";
const green = "#E2F0D9";
const amber = "#FFF4CC";
const red = "#FCE8E6";
const blueInput = "#0000FF";

function colName(index) {
  let n = index + 1;
  let out = "";
  while (n) {
    const remainder = (n - 1) % 26;
    out = String.fromCharCode(65 + remainder) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function dateValue(value) {
  return value ? new Date(`${value}T00:00:00Z`) : "";
}

function addTableSheet(name, headers, rows, widths = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [headers, ...rows.map((row) => headers.map((header) => row[header] ?? ""))];
  const endColumn = colName(headers.length - 1);
  const address = `A1:${endColumn}${matrix.length}`;
  sheet.getRange(address).values = matrix;
  sheet.getRange(`A1:${endColumn}1`).format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
    rowHeight: 30,
  };
  sheet.getRange(address).format.borders = {
    insideHorizontal: { style: "thin", color: "#D9E2EC" },
  };
  sheet.freezePanes.freezeRows(1);
  headers.forEach((header, index) => {
    sheet.getRangeByIndexes(0, index, Math.max(matrix.length, 2), 1).format.columnWidth = widths[header] ?? 16;
  });
  if (rows.length) {
    sheet.tables.add(address, true, `T${workbook.worksheets.items.length}${name.replace(/[^A-Za-z0-9]/g, "")}`);
  }
  return sheet;
}

function applyPriorityFormatting(sheet, range) {
  sheet.getRange(range).conditionalFormats.addCustom('=$A2="P1"', { fill: red, font: { color: "#9C0006", bold: true } });
  sheet.getRange(range).conditionalFormats.addCustom('=$A2="P2"', { fill: amber });
}

const s = data.summary;
const summary = workbook.worksheets.add("运行摘要");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["基金重仓研究资源对接准备"]];
summary.getRange("A1:H1").format = {
  fill: navy,
  font: { bold: true, color: "#FFFFFF", size: 18 },
  rowHeight: 34,
  verticalAlignment: "center",
};
summary.getRange("A3:B14").values = [
  ["报告期", dateValue(s.report_date)],
  ["行业对接需求", s.industry_demand_count],
  ["公司对接需求", s.company_demand_count],
  ["人员库记录", s.personnel_count],
  ["在岗人员", s.active_personnel_count],
  ["匹配记录", s.match_count],
  ["待补充项", s.pending_count],
  ["人员库错误", s.personnel_error_count],
  ["人员库警告", s.personnel_warning_count ?? 0],
  ["候选匹配", s.candidate_match_count ?? 0],
  ["排除的非申万公司", s.excluded_non_sw_company_count ?? 0],
  ["运行状态", s.status],
];
const p1Industries = data.industry_demands.filter((row) => row.priority === "P1").length;
const p1Companies = data.company_demands.filter((row) => row.priority === "P1").length;
const pendingP1 = data.pending_items.filter((row) => row.priority === "P1").length;
summary.getRange("D3:E9").values = [
  ["优先处理指标", "数量/结果"],
  ["P1 行业需求", p1Industries],
  ["P1 公司需求", p1Companies],
  ["P1 待补充", pendingP1],
  ["匹配方式", "公司精确覆盖优先"],
  ["人员姓名", s.personnel_count ? "来自人员库" : "未生成/未虚构"],
  ["模型调用", "未调用 DeepSeek"],
];
summary.getRange("A3:A14").format = { fill: pale, font: { bold: true } };
summary.getRange("D3:E3").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A3:B14").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("D3:E9").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("B3").format.numberFormat = "yyyy-mm-dd";
summary.getRange("A16:H18").merge();
const conclusion = s.personnel_count
  ? `当前结论：已使用 ${s.personnel_count} 条人员记录生成行业和公司两层对接建议。研究分组映射属于组级推定，不等于个人已确认覆盖具体公司；候选映射共 ${s.candidate_match_count ?? 0} 条，需人工确认。联系方式仍按权限控制。`
  : "当前结论：已从基金正式持仓生成行业和公司两层对接需求。由于人员库尚未提供，所有需求进入“待补充项”，系统不会猜测或虚构研究员/专家。填写“人员库模板”后另存为 CSV，并重新运行 fund-resources 生成匹配结果。";
summary.getRange("A16").values = [[conclusion]];
summary.getRange("A16:H18").format = { fill: "#F3F6F9", wrapText: true, verticalAlignment: "center" };
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 22;
summary.getRange("C:C").format.columnWidth = 4;
summary.getRange("D:D").format.columnWidth = 23;
summary.getRange("E:E").format.columnWidth = 28;

const targetMatchScores = new Map();
for (const row of data.matches) {
  const key = `${row.demand_type}:${row.target_code}`;
  targetMatchScores.set(key, Math.max(targetMatchScores.get(key) ?? 0, row.score ?? 0));
}
function matchStatus(demandType, targetCode) {
  const score = targetMatchScores.get(`${demandType}:${targetCode}`) ?? 0;
  if (score >= 40) return score >= 50 ? "已匹配" : "已匹配（组级推定）";
  if (score > 0) return "候选匹配（待确认）";
  return "待补充人员";
}
const industryRows = data.industry_demands.map((row) => ({
  "优先级": row.priority,
  "申万一级行业": row.sw_level1,
  "涉及基金数": row.fund_count,
  "基金代码": row.fund_codes,
  "重仓记录数": row.holding_count,
  "持仓市值合计(万元)": row.market_value_10k,
  "净值比例算术合计": row.nav_ratio_sum,
  "匹配状态": matchStatus("行业", row.sw_level1),
}));
const industrySheet = addTableSheet(
  "行业对接需求",
  ["优先级", "申万一级行业", "涉及基金数", "基金代码", "重仓记录数", "持仓市值合计(万元)", "净值比例算术合计", "匹配状态"],
  industryRows,
  { "优先级": 10, "申万一级行业": 18, "涉及基金数": 14, "基金代码": 24, "重仓记录数": 14, "持仓市值合计(万元)": 22, "净值比例算术合计": 20, "匹配状态": 16 },
);
industrySheet.getRange(`F2:F${industryRows.length + 1}`).format.numberFormat = "#,##0.00";
industrySheet.getRange(`G2:G${industryRows.length + 1}`).format.numberFormat = "0.00%";
industrySheet.getRange(`D2:D${industryRows.length + 1}`).format.numberFormat = "000000";
applyPriorityFormatting(industrySheet, `A2:H${industryRows.length + 1}`);

const companyRows = data.company_demands.map((row) => ({
  "优先级": row.priority,
  "股票代码": row.stock_code,
  "股票名称": row.stock_name,
  "申万一级行业": row.sw_level1,
  "申万二级行业": row.sw_level2,
  "涉及基金数": row.fund_count,
  "基金代码": row.fund_codes,
  "持仓出现次数": row.holding_occurrences,
  "持仓市值合计(万元)": row.market_value_10k,
  "单基金最高净值比例": row.max_nav_ratio,
  "匹配状态": matchStatus("公司", row.stock_code),
}));
const companySheet = addTableSheet(
  "公司对接需求",
  ["优先级", "股票代码", "股票名称", "申万一级行业", "申万二级行业", "涉及基金数", "基金代码", "持仓出现次数", "持仓市值合计(万元)", "单基金最高净值比例", "匹配状态"],
  companyRows,
  { "优先级": 10, "股票代码": 16, "股票名称": 18, "申万一级行业": 18, "申万二级行业": 18, "涉及基金数": 14, "基金代码": 24, "持仓出现次数": 16, "持仓市值合计(万元)": 22, "单基金最高净值比例": 22, "匹配状态": 18 },
);
companySheet.getRange(`I2:I${companyRows.length + 1}`).format.numberFormat = "#,##0.00";
companySheet.getRange(`J2:J${companyRows.length + 1}`).format.numberFormat = "0.00%";
companySheet.getRange(`G2:G${companyRows.length + 1}`).format.numberFormat = "000000";
applyPriorityFormatting(companySheet, `A2:K${companyRows.length + 1}`);

const matchRows = data.matches.map((row) => ({
  "需求类型": row.demand_type,
  "优先级": row.priority,
  "目标代码": row.target_code,
  "目标名称": row.target_name,
  "申万一级行业": row.sw_level1,
  "申万二级行业": row.sw_level2,
  "匹配方式": row.match_type,
  "匹配分": row.score,
  "人员姓名": row.person_name,
  "所属机构": row.organization,
  "人员类型": row.person_type,
  "职务": row.job_title,
  "原研究分组": row.source_group,
  "专长标签": row.expertise_tags,
  "地区": row.region,
  "覆盖依据": row.coverage_basis,
  "行业映射状态": row.industry_mapping_status,
  "确认状态": row.confirmation_status,
  "联系权限": row.contact_permission,
  "联系方式": row.contact_info,
}));
const matchSheet = addTableSheet(
  "匹配结果",
  ["需求类型", "优先级", "目标代码", "目标名称", "申万一级行业", "申万二级行业", "匹配方式", "匹配分", "人员姓名", "所属机构", "人员类型", "职务", "原研究分组", "专长标签", "地区", "覆盖依据", "行业映射状态", "确认状态", "联系权限", "联系方式"],
  matchRows,
  { "需求类型": 12, "优先级": 10, "目标代码": 16, "目标名称": 18, "申万一级行业": 18, "申万二级行业": 18, "匹配方式": 18, "匹配分": 12, "人员姓名": 16, "所属机构": 22, "人员类型": 12, "职务": 24, "原研究分组": 20, "专长标签": 24, "地区": 14, "覆盖依据": 18, "行业映射状态": 18, "确认状态": 14, "联系权限": 14, "联系方式": 24 },
);
if (matchRows.length) matchSheet.getRange(`A2:T${matchRows.length + 1}`).format.wrapText = true;

const pendingRows = data.pending_items.map((row) => ({
  "优先级": row.priority,
  "需求类型": row.demand_type,
  "目标代码": row.target_code,
  "目标名称": row.target_name,
  "申万一级行业": row.sw_level1,
  "未匹配原因": row.reason,
  "建议处理": row.action,
}));
const pendingSheet = addTableSheet(
  "待补充项",
  ["优先级", "需求类型", "目标代码", "目标名称", "申万一级行业", "未匹配原因", "建议处理"],
  pendingRows,
  { "优先级": 10, "需求类型": 12, "目标代码": 18, "目标名称": 18, "申万一级行业": 18, "未匹配原因": 52, "建议处理": 34 },
);
pendingSheet.getRange(`A2:G${pendingRows.length + 1}`).format.wrapText = true;
applyPriorityFormatting(pendingSheet, `A2:G${pendingRows.length + 1}`);

const excludedRows = (data.excluded_demands ?? []).map((row) => ({
  "股票代码": row.stock_code,
  "股票名称": row.stock_name,
  "市场": row.market,
  "行业状态": row.sw_level1,
  "涉及基金数": row.fund_count,
  "基金代码": row.fund_codes,
  "持仓出现次数": row.holding_occurrences,
  "排除原因": row.reason,
}));
const excludedSheet = addTableSheet(
  "不纳入资源匹配",
  ["股票代码", "股票名称", "市场", "行业状态", "涉及基金数", "基金代码", "持仓出现次数", "排除原因"],
  excludedRows,
  { "股票代码": 16, "股票名称": 20, "市场": 12, "行业状态": 16, "涉及基金数": 14, "基金代码": 26, "持仓出现次数": 16, "排除原因": 50 },
);
if (excludedRows.length) excludedSheet.getRange(`A2:H${excludedRows.length + 1}`).format.wrapText = true;

const personnelHeaders = ["人员姓名", "所属机构", "人员类型", "覆盖申万一级行业", "覆盖申万二级行业", "覆盖公司代码", "专长标签", "地区", "当前状态", "联系权限", "联系方式", "职务", "原研究分组", "数据日期", "覆盖依据", "行业映射状态", "映射说明", "状态依据", "来源行号"];
const personnelExisting = data.personnel_rows.map((row) => [
  row.person_name,
  row.organization,
  row.person_type,
  row.sw_level1,
  row.covered_sw_level2,
  row.covered_stock_codes,
  row.expertise_tags,
  row.region,
  row.current_status,
  row.contact_permission,
  row.contact_info,
  row.job_title,
  row.source_group,
  row.source_date,
  row.coverage_basis,
  row.industry_mapping_status,
  row.mapping_note,
  row.status_basis,
  row.source_row,
]);
const personnelRowCount = Math.max(30, personnelExisting.length);
const personnelMatrix = [personnelHeaders];
for (let index = 0; index < personnelRowCount; index += 1) {
  personnelMatrix.push(personnelExisting[index] ?? new Array(personnelHeaders.length).fill(""));
}
const personnelSheet = workbook.worksheets.add("人员库模板");
personnelSheet.showGridLines = false;
personnelSheet.getRange(`A1:S${personnelRowCount + 1}`).values = personnelMatrix;
personnelSheet.getRange("A1:S1").format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true, rowHeight: 32, verticalAlignment: "center" };
personnelSheet.getRange(`A2:S${personnelRowCount + 1}`).format = { font: { color: blueInput }, borders: { insideHorizontal: { style: "thin", color: "#D9E2EC" } } };
personnelSheet.getRange(`A1:S${personnelRowCount + 1}`).format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EC" } };
personnelSheet.freezePanes.freezeRows(1);
const personnelWidths = [16, 24, 14, 28, 24, 28, 22, 12, 12, 14, 24, 24, 20, 14, 18, 18, 42, 28, 12];
personnelWidths.forEach((width, index) => { personnelSheet.getRangeByIndexes(0, index, personnelRowCount + 1, 1).format.columnWidth = width; });
personnelSheet.tables.add(`A1:S${personnelRowCount + 1}`, true, "PersonnelTemplateTable");
personnelSheet.getRange(`C2:C${personnelRowCount + 1}`).dataValidation = { rule: { type: "list", values: ["研究员", "专家"] } };
personnelSheet.getRange(`I2:I${personnelRowCount + 1}`).dataValidation = { rule: { type: "list", values: ["在岗", "离岗", "暂停"] } };
personnelSheet.getRange(`J2:J${personnelRowCount + 1}`).dataValidation = { rule: { type: "list", values: ["允许", "需审批", "不允许"] } };
const noteStart = personnelRowCount + 3;
const noteEnd = noteStart + 2;
personnelSheet.getRange(`A${noteStart}:S${noteEnd}`).merge();
personnelSheet.getRange(`A${noteStart}`).values = [["填写说明：人员姓名、所属机构、人员类型、当前状态、联系权限为必填；非股票或跨行业研究人员可暂不填写申万一级行业，但不会参与自动匹配；多个行业/公司代码用中文分号“；”分隔；公司代码使用带市场后缀的标准格式，例如 688072.SH。研究分组导入的覆盖属于组级推定，需保留覆盖依据和映射状态。蓝色字体区域为可输入区。"]];
personnelSheet.getRange(`A${noteStart}:S${noteEnd}`).format = { fill: pale, wrapText: true, verticalAlignment: "center" };

const issueRows = data.personnel_issues.map((row) => ({
  "级别": row.severity,
  "分类": row.category,
  "原始行号": row.row_no,
  "人员姓名": row.person_name,
  "所属机构": row.organization,
  "问题说明": row.message,
  "建议处理": row.action,
}));
const issueSheet = addTableSheet(
  "人员库校验",
  ["级别", "分类", "原始行号", "人员姓名", "所属机构", "问题说明", "建议处理"],
  issueRows,
  { "级别": 10, "分类": 22, "原始行号": 12, "人员姓名": 16, "所属机构": 22, "问题说明": 58, "建议处理": 34 },
);
if (issueRows.length) {
  issueSheet.getRange(`A2:G${issueRows.length + 1}`).format.wrapText = true;
  issueSheet.getRange(`A2:G${issueRows.length + 1}`).conditionalFormats.addCustom('=$A2="错误"', { fill: red, font: { color: "#9C0006" } });
}

const ruleRows = [
  ...data.rules.map((row) => ({ "项目": row.item, "确定性规则": row.rule })),
  { "项目": "需求层级", "确定性规则": "行业层用于安排行业研究资源；公司层用于安排具体重仓公司对接。两层需求分别保留，不互相覆盖。" },
  { "项目": "净值比例说明", "确定性规则": "跨基金净值比例算术合计仅用于排序和勾稽，不代表统一组合的行业暴露。" },
  { "项目": "人员库输入", "确定性规则": "姓名、机构、类型、当前状态、联系权限必填；姓名+机构不得重复。申万行业为空的人员保留但不参与行业匹配；空人员库允许运行。" },
  { "项目": "隐私控制", "确定性规则": "只有联系权限为‘允许’时输出联系方式；‘需审批’或‘不允许’一律显示为已隐藏。" },
];
const rulesSheet = addTableSheet("匹配口径", ["项目", "确定性规则"], ruleRows, { "项目": 26, "确定性规则": 105 });
rulesSheet.getRange(`A2:B${ruleRows.length + 1}`).format.wrapText = true;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const previewSheets = ["运行摘要", "行业对接需求", "公司对接需求", "匹配结果", "待补充项", "不纳入资源匹配", "人员库模板", "人员库校验", "匹配口径"];
for (const sheetName of previewSheets) {
  const image = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}

const summaryCheck = await workbook.inspect({ kind: "table", range: "运行摘要!A1:H18", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 });
console.log(summaryCheck.ndjson);
const industryCheck = await workbook.inspect({ kind: "table", range: `行业对接需求!A1:H${industryRows.length + 1}`, include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 });
console.log(industryCheck.ndjson);
const companyCheck = await workbook.inspect({ kind: "table", range: `公司对接需求!A1:K${companyRows.length + 1}`, include: "values,formulas", tableMaxRows: 30, tableMaxCols: 12 });
console.log(companyCheck.ndjson);
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errorCheck.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX=${outputPath}`);
