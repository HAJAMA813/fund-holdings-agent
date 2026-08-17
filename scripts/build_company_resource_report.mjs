import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) {
  throw new Error("usage: build_company_resource_report.mjs company_resource_data.json output.xlsx preview_dir");
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const NAVY = "#17365D";
const TEAL = "#1F7A8C";
const PALE = "#EAF2F8";
const GREEN = "#E2F0D9";
const AMBER = "#FFF4CC";
const RED = "#FCE8E6";
const GRAY = "#F3F6F9";
let tableCounter = 0;

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

function beijingTimestampText(value) {
  if (!value) return "";
  const compact = String(value).replace(/\+08:00$/, "");
  const match = compact.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})$/);
  return match ? `${match[1]}年${match[2]}月${match[3]}日 ${match[4]}` : compact;
}

function shortCompany(value) {
  return String(value || "基金公司")
    .replace(/基金管理股份有限公司$/, "基金")
    .replace(/基金管理有限公司$/, "基金")
    .replace(/基金有限责任公司$/, "基金");
}

function addTableSheet(name, title, headers, rows, widths = {}, freezeColumns = 0) {
  const sheet = workbook.worksheets.add(name);
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
    const table = sheet.tables.add(address, true, `CompanyResourcesTable${tableCounter}`);
    table.style = "TableStyleMedium2";
  }
  return { sheet, endRow, lastCol };
}

function applyPriorityFormatting(sheet, range) {
  sheet.getRange(range).conditionalFormats.addCustom('=$A3="P1"', { fill: RED, font: { color: "#9C0006", bold: true } });
  sheet.getRange(range).conditionalFormats.addCustom('=$A3="P2"', { fill: AMBER });
}

const s = data.summary;
const companyLabel = shortCompany(s.company);
const summary = workbook.worksheets.add("运行摘要");

const managerRows = data.manager_overview.map((row) => ({
  "基金经理": row.manager,
  "天天基金经理ID": row.manager_id,
  "状态": row.status,
  "行业需求数": row.industry_demand_count,
  "公司需求数": row.company_demand_count,
  "匹配记录数": row.match_count,
  "原候选匹配数": row.source_candidate_match_count,
  "业务已确认候选数": row.confirmed_candidate_match_count,
  "待确认候选数": row.candidate_match_count,
  "待补充数": row.pending_count,
  "排除公司数": row.excluded_non_sw_company_count,
  "错误说明": row.error,
}));
const managerBlock = addTableSheet(
  "基金经理概览",
  `${companyLabel} ${s.quarter} 基金经理研究资源概览`,
  ["基金经理", "天天基金经理ID", "状态", "行业需求数", "公司需求数", "匹配记录数", "原候选匹配数", "业务已确认候选数", "待确认候选数", "待补充数", "排除公司数", "错误说明"],
  managerRows,
  { "基金经理": 16, "天天基金经理ID": 18, "状态": 14, "行业需求数": 14, "公司需求数": 14, "匹配记录数": 14, "原候选匹配数": 16, "业务已确认候选数": 18, "待确认候选数": 16, "待补充数": 14, "排除公司数": 14, "错误说明": 40 },
  1,
);
managerBlock.sheet.getRange(`B3:B${managerBlock.endRow}`).format.numberFormat = "@";
managerBlock.sheet.getRange(`C3:C${managerBlock.endRow}`).conditionalFormats.addCustom('=$C3="completed"', { fill: GREEN });
managerBlock.sheet.getRange(`C3:C${managerBlock.endRow}`).conditionalFormats.addCustom('=$C3<>"completed"', { fill: RED, font: { color: "#9C0006" } });

const industryRows = data.industry_rollup.map((row) => ({
  "最高优先级": row.priority,
  "申万一级行业": row.sw_level1,
  "覆盖经理数": row.manager_count,
  "基金经理": row.managers,
  "P1经理数": row.p1_manager_count,
  "经理需求次数": row.demand_occurrences,
  "不同基金代码数": row.unique_fund_count,
  "基金代码": row.fund_codes,
  "持仓记录算术合计": row.holding_count_sum,
  "披露市值算术合计(万元)": row.market_value_10k_sum,
  "净值比例算术合计": row.nav_ratio_sum,
}));
const industryBlock = addTableSheet(
  "行业需求汇总",
  `${companyLabel} ${s.quarter} 行业研究资源需求`,
  ["最高优先级", "申万一级行业", "覆盖经理数", "基金经理", "P1经理数", "经理需求次数", "不同基金代码数", "基金代码", "持仓记录算术合计", "披露市值算术合计(万元)", "净值比例算术合计"],
  industryRows,
  { "最高优先级": 12, "申万一级行业": 18, "覆盖经理数": 14, "基金经理": 34, "P1经理数": 12, "经理需求次数": 16, "不同基金代码数": 16, "基金代码": 34, "持仓记录算术合计": 18, "披露市值算术合计(万元)": 24, "净值比例算术合计": 20 },
  2,
);
industryBlock.sheet.getRange(`J3:J${industryBlock.endRow}`).format.numberFormat = "#,##0.00";
industryBlock.sheet.getRange(`K3:K${industryBlock.endRow}`).format.numberFormat = "0.00%";
industryBlock.sheet.getRange(`D3:D${industryBlock.endRow}`).format.wrapText = true;
applyPriorityFormatting(industryBlock.sheet, `A3:K${industryBlock.endRow}`);

const companyRows = data.company_rollup.map((row) => ({
  "最高优先级": row.priority,
  "股票代码": row.stock_code,
  "股票名称": row.stock_name,
  "申万一级行业": row.sw_level1,
  "申万二级行业": row.sw_level2,
  "覆盖经理数": row.manager_count,
  "基金经理": row.managers,
  "P1经理数": row.p1_manager_count,
  "经理需求次数": row.demand_occurrences,
  "不同基金代码数": row.unique_fund_count,
  "基金代码": row.fund_codes,
  "持仓出现次数算术合计": row.holding_occurrences_sum,
  "披露市值算术合计(万元)": row.market_value_10k_sum,
  "单基金最高净值比例": row.max_nav_ratio,
  "最高匹配分": row.best_match_score,
  "匹配状态": row.match_status,
  "建议对接人员": row.matched_people,
}));
const companyBlock = addTableSheet(
  "公司需求汇总",
  `${companyLabel} ${s.quarter} 重仓公司研究资源需求`,
  ["最高优先级", "股票代码", "股票名称", "申万一级行业", "申万二级行业", "覆盖经理数", "基金经理", "P1经理数", "经理需求次数", "不同基金代码数", "基金代码", "持仓出现次数算术合计", "披露市值算术合计(万元)", "单基金最高净值比例", "最高匹配分", "匹配状态", "建议对接人员"],
  companyRows,
  { "最高优先级": 12, "股票代码": 16, "股票名称": 18, "申万一级行业": 18, "申万二级行业": 20, "覆盖经理数": 14, "基金经理": 30, "P1经理数": 12, "经理需求次数": 16, "不同基金代码数": 16, "基金代码": 32, "持仓出现次数算术合计": 20, "披露市值算术合计(万元)": 24, "单基金最高净值比例": 22, "最高匹配分": 14, "匹配状态": 20, "建议对接人员": 34 },
  3,
);
companyBlock.sheet.getRange(`B3:B${companyBlock.endRow}`).format.numberFormat = "@";
companyBlock.sheet.getRange(`M3:M${companyBlock.endRow}`).format.numberFormat = "#,##0.00";
companyBlock.sheet.getRange(`N3:N${companyBlock.endRow}`).format.numberFormat = "0.00%";
companyBlock.sheet.getRange(`G3:G${companyBlock.endRow}`).format.wrapText = true;
companyBlock.sheet.getRange(`Q3:Q${companyBlock.endRow}`).format.wrapText = true;
companyBlock.sheet.getRange(`P3:P${companyBlock.endRow}`).conditionalFormats.addCustom('=$P3="公司精确匹配"', { fill: GREEN, font: { bold: true } });
companyBlock.sheet.getRange(`P3:P${companyBlock.endRow}`).conditionalFormats.addCustom('=$P3="候选已确认"', { fill: GREEN, font: { bold: true } });
companyBlock.sheet.getRange(`P3:P${companyBlock.endRow}`).conditionalFormats.addCustom('=$P3="候选待确认"', { fill: AMBER });
applyPriorityFormatting(companyBlock.sheet, `A3:Q${companyBlock.endRow}`);

const personRows = data.person_rollup.map((row) => ({
  "人员姓名": row.person_name,
  "所属机构": row.organization,
  "职务": row.job_title,
  "原研究分组": row.source_group,
  "专长标签": row.expertise_tags,
  "地区": row.region,
  "覆盖经理数": row.manager_count,
  "基金经理": row.managers,
  "行业目标数": row.industry_target_count,
  "公司目标数": row.company_target_count,
  "公司精确匹配次数": row.exact_company_match_count,
  "二级行业匹配次数": row.level2_match_count,
  "业务已确认候选次数": row.confirmed_candidate_match_count,
  "待确认候选次数": row.candidate_match_count,
  "最高匹配分": row.max_score,
  "匹配方式": row.match_types,
  "联系权限": row.contact_permission,
  "联系方式": row.contact_info,
}));
const personBlock = addTableSheet(
  "人员对接汇总",
  `${companyLabel} ${s.quarter} 研究人员对接汇总`,
  ["人员姓名", "所属机构", "职务", "原研究分组", "专长标签", "地区", "覆盖经理数", "基金经理", "行业目标数", "公司目标数", "公司精确匹配次数", "二级行业匹配次数", "业务已确认候选次数", "待确认候选次数", "最高匹配分", "匹配方式", "联系权限", "联系方式"],
  personRows,
  { "人员姓名": 16, "所属机构": 22, "职务": 24, "原研究分组": 20, "专长标签": 24, "地区": 12, "覆盖经理数": 14, "基金经理": 34, "行业目标数": 14, "公司目标数": 14, "公司精确匹配次数": 18, "二级行业匹配次数": 18, "业务已确认候选次数": 20, "待确认候选次数": 18, "最高匹配分": 14, "匹配方式": 30, "联系权限": 14, "联系方式": 18 },
  1,
);
personBlock.sheet.getRange(`H3:H${personBlock.endRow}`).format.wrapText = true;
personBlock.sheet.getRange(`M3:M${personBlock.endRow}`).conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { fill: GREEN } });
personBlock.sheet.getRange(`N3:N${personBlock.endRow}`).conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { fill: AMBER } });

const detailHeaders = ["基金经理", "需求类型", "优先级", "目标代码", "目标名称", "申万一级行业", "申万二级行业", "匹配方式", "匹配分", "人员姓名", "所属机构", "职务", "原研究分组", "专长标签", "地区", "确认状态", "原确认状态", "确认人/来源", "确认时间（北京时间）", "联系权限", "联系方式"];
function detailRow(row) {
  return {
    "基金经理": row.manager,
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
    "职务": row.job_title,
    "原研究分组": row.source_group,
    "专长标签": row.expertise_tags,
    "地区": row.region,
    "确认状态": row.confirmation_status,
    "原确认状态": row.original_confirmation_status || "",
    "确认人/来源": row.confirmed_by || "",
    "确认时间（北京时间）": beijingTimestampText(row.confirmed_at_beijing),
    "联系权限": row.contact_permission,
    "联系方式": row.contact_info,
  };
}
const detailWidths = { "基金经理": 16, "需求类型": 12, "优先级": 10, "目标代码": 16, "目标名称": 18, "申万一级行业": 18, "申万二级行业": 20, "匹配方式": 18, "匹配分": 12, "人员姓名": 16, "所属机构": 22, "职务": 24, "原研究分组": 20, "专长标签": 24, "地区": 12, "确认状态": 16, "原确认状态": 14, "确认人/来源": 18, "确认时间（北京时间）": 24, "联系权限": 14, "联系方式": 18 };
const detailRows = data.match_details.map(detailRow);
const detailBlock = addTableSheet("匹配明细", `${companyLabel} ${s.quarter} 全量研究资源匹配明细`, detailHeaders, detailRows, detailWidths, 1);
detailBlock.sheet.getRange(`D3:D${detailBlock.endRow}`).format.numberFormat = "@";
detailBlock.sheet.getRange(`S3:S${detailBlock.endRow}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
detailBlock.sheet.getRange(`P3:P${detailBlock.endRow}`).conditionalFormats.addCustom('=$P3="待确认"', { fill: AMBER });
detailBlock.sheet.getRange(`P3:P${detailBlock.endRow}`).conditionalFormats.addCustom('=$P3="业务已确认"', { fill: GREEN, font: { bold: true } });

const candidateSource = data.confirmed_candidate_items?.length ? data.confirmed_candidate_items : data.candidate_items;
const candidateRows = candidateSource.map(detailRow);
const candidateTitle = data.confirmed_candidate_items?.length
  ? `${companyLabel} ${s.quarter} 原宽口径候选（业务已全部确认）`
  : `${companyLabel} ${s.quarter} 宽口径候选匹配`;
const candidateBlock = addTableSheet("待确认事项", candidateTitle, detailHeaders, candidateRows, detailWidths, 1);
candidateBlock.sheet.getRange(`D3:D${candidateBlock.endRow}`).format.numberFormat = "@";
candidateBlock.sheet.getRange(`S3:S${candidateBlock.endRow}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
if (candidateRows.length) candidateBlock.sheet.getRange(`A3:U${candidateBlock.endRow}`).format.fill = data.confirmed_candidate_items?.length ? GREEN : AMBER;

const pendingRows = data.pending_items.map((row) => ({
  "基金经理": row.manager,
  "优先级": row.priority,
  "需求类型": row.demand_type,
  "目标代码": row.target_code,
  "目标名称": row.target_name,
  "申万一级行业": row.sw_level1,
  "未匹配原因": row.reason,
  "建议处理": row.action,
}));
const pendingBlock = addTableSheet(
  "待补充项",
  `${companyLabel} ${s.quarter} 尚未匹配的研究资源需求`,
  ["基金经理", "优先级", "需求类型", "目标代码", "目标名称", "申万一级行业", "未匹配原因", "建议处理"],
  pendingRows,
  { "基金经理": 16, "优先级": 10, "需求类型": 12, "目标代码": 18, "目标名称": 18, "申万一级行业": 18, "未匹配原因": 48, "建议处理": 40 },
  1,
);
if (pendingRows.length) pendingBlock.sheet.getRange(`A3:H${pendingBlock.endRow}`).format.fill = RED;

const excludedRows = data.excluded_rollup.map((row) => ({
  "股票代码": row.stock_code,
  "股票名称": row.stock_name,
  "市场": row.market,
  "行业状态": row.sw_level1,
  "覆盖经理数": row.manager_count,
  "基金经理": row.managers,
  "不同基金代码数": row.unique_fund_count,
  "基金代码": row.fund_codes,
  "持仓出现次数算术合计": row.holding_occurrences_sum,
  "排除原因": row.reason,
}));
const excludedBlock = addTableSheet(
  "不纳入资源匹配",
  `${companyLabel} ${s.quarter} 港股及申万不适用公司排除审计`,
  ["股票代码", "股票名称", "市场", "行业状态", "覆盖经理数", "基金经理", "不同基金代码数", "基金代码", "持仓出现次数算术合计", "排除原因"],
  excludedRows,
  { "股票代码": 16, "股票名称": 20, "市场": 12, "行业状态": 16, "覆盖经理数": 14, "基金经理": 28, "不同基金代码数": 16, "基金代码": 34, "持仓出现次数算术合计": 20, "排除原因": 52 },
  2,
);
excludedBlock.sheet.getRange(`A3:A${excludedBlock.endRow}`).format.numberFormat = "@";
excludedBlock.sheet.getRange(`F3:F${excludedBlock.endRow}`).format.wrapText = true;
excludedBlock.sheet.getRange(`J3:J${excludedBlock.endRow}`).format.wrapText = true;

// Create the checks worksheet before summary formulas reference it.
const checks = workbook.worksheets.add("数据校验");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [[`${companyLabel} ${s.quarter} 研究资源对接汇总`]];
summary.getRange("A1:H1").format = { fill: NAVY, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 34, verticalAlignment: "center" };
summary.getRange("A3:B17").values = [
  ["报告期", dateValue(s.report_date)],
  ["基金经理数", ""],
  ["完成经理数", ""],
  ["行业需求（逐经理合计）", ""],
  ["公司需求（逐经理合计）", ""],
  ["公司唯一行业数", ""],
  ["公司唯一A股数", ""],
  ["匹配记录数", ""],
  ["原候选匹配数", ""],
  ["业务已确认候选数", ""],
  ["尚待确认候选数", ""],
  ["待补充项", ""],
  ["排除记录（逐经理合计）", ""],
  ["排除的不同公司数", ""],
  ["数据校验", ""],
];
const managerLast = managerBlock.endRow;
const industryLast = industryBlock.endRow;
const companyLast = companyBlock.endRow;
const excludedLast = excludedBlock.endRow;
summary.getRange("B4:B17").formulas = [
  [`=COUNTA('基金经理概览'!$A$3:$A$${managerLast})`],
  [`=COUNTIF('基金经理概览'!$C$3:$C$${managerLast},"completed")`],
  [`=SUM('基金经理概览'!$D$3:$D$${managerLast})`],
  [`=SUM('基金经理概览'!$E$3:$E$${managerLast})`],
  [`=COUNTA('行业需求汇总'!$B$3:$B$${industryLast})`],
  [`=COUNTA('公司需求汇总'!$B$3:$B$${companyLast})`],
  [`=SUM('基金经理概览'!$F$3:$F$${managerLast})`],
  [`=SUM('基金经理概览'!$G$3:$G$${managerLast})`],
  [`=SUM('基金经理概览'!$H$3:$H$${managerLast})`],
  [`=SUM('基金经理概览'!$I$3:$I$${managerLast})`],
  [`=SUM('基金经理概览'!$J$3:$J$${managerLast})`],
  [`=SUM('基金经理概览'!$K$3:$K$${managerLast})`],
  [`=COUNTA('不纳入资源匹配'!$A$3:$A$${excludedLast})`],
  [`=IF(COUNTIF('数据校验'!$E$3:$E$17,"FAIL")=0,"通过","失败")`],
];
summary.getRange("D3:E11").values = [
  ["决策指标", "数量/结论"],
  ["需要对接的研究人员", s.matched_person_count],
  ["公司精确/二级匹配公司", data.company_rollup.filter((row) => row.best_match_score >= 70).length],
  ["组级推定公司", data.company_rollup.filter((row) => row.best_match_score >= 40 && row.best_match_score < 70).length],
  ["候选已确认公司", data.company_rollup.filter((row) => row.match_status === "候选已确认").length],
  ["尚待确认公司", data.company_rollup.filter((row) => row.match_status === "候选待确认").length],
  ["待补人员公司", data.company_rollup.filter((row) => row.best_match_score === 0).length],
  ["人员联系方式", "全部按权限控制"],
  ["模型调用", "未调用 DeepSeek"],
];
summary.getRange("A3:A17").format = { fill: PALE, font: { bold: true } };
summary.getRange("D3:E3").format = { fill: TEAL, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A3:B17").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("D3:E11").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("B3").format.numberFormat = "yyyy-mm-dd";
summary.getRange("A19:H21").merge();
summary.getRange("A19").values = [[`使用说明：公司级报告用于安排研究资源。公司唯一行业/股票按代码去重；需求数、匹配数、市值和净值比例来自逐基金经理结果算术合计，共同管理基金可能重复，因此不代表公司统一组合暴露。当前港股不进入研究资源需求，但保留排除审计。原候选 ${s.source_candidate_match_count_sum} 条，业务已确认 ${s.confirmed_candidate_match_count_sum} 条，尚待确认 ${s.candidate_match_count_sum} 条；确认只改变状态，不提高原始匹配分。`]];
summary.getRange("A19:H21").format = { fill: GRAY, wrapText: true, verticalAlignment: "center" };
summary.getRange("A:A").format.columnWidth = 28;
summary.getRange("B:B").format.columnWidth = 20;
summary.getRange("C:C").format.columnWidth = 4;
summary.getRange("D:D").format.columnWidth = 28;
summary.getRange("E:E").format.columnWidth = 28;
summary.getRange("B17").conditionalFormats.addCustom('=$B$17="通过"', { fill: GREEN, font: { bold: true } });
summary.getRange("B17").conditionalFormats.addCustom('=$B$17="失败"', { fill: RED, font: { color: "#9C0006", bold: true } });

checks.showGridLines = false;
checks.getRange("A1:F1").merge();
checks.getRange("A1").values = [[`${companyLabel} ${s.quarter} 聚合校验`]];
checks.getRange("A1:F1").format = { fill: NAVY, font: { bold: true, color: "#FFFFFF", size: 15 }, rowHeight: 30 };
checks.getRange("A2:F2").values = [["校验项目", "实际值", "预期值", "差异", "状态", "说明"]];
checks.getRange("A2:F2").format = { fill: TEAL, font: { bold: true, color: "#FFFFFF" }, rowHeight: 28 };
const checkRows = [
  ["经理数", "='运行摘要'!B4", s.manager_count, "名单与经理概览行数一致"],
  ["完成经理数", "='运行摘要'!B5", s.completed_manager_count, "全部经理资源文件成功载入"],
  ["行业需求逐经理合计", "='运行摘要'!B6", s.industry_demand_count_sum, "与源资源摘要勾稽"],
  ["公司需求逐经理合计", "='运行摘要'!B7", s.company_demand_count_sum, "与源资源摘要勾稽"],
  ["匹配记录逐经理合计", "='运行摘要'!B10", s.match_count_sum, "与匹配明细行数勾稽"],
  ["原候选匹配逐经理合计", "='运行摘要'!B11", s.source_candidate_match_count_sum, "与源资源摘要勾稽"],
  ["业务已确认候选", "='运行摘要'!B12", s.confirmed_candidate_match_count_sum, "与本次确认快照勾稽"],
  ["尚待确认候选", "='运行摘要'!B13", s.candidate_match_count_sum, "全部确认后应为0"],
  ["候选状态勾稽", "='运行摘要'!B12+'运行摘要'!B13", s.source_candidate_match_count_sum, "已确认与待确认之和等于原候选"],
  ["待补充项", "='运行摘要'!B14", s.pending_count_sum, "当前应为0"],
  ["排除记录逐经理合计", "='运行摘要'!B15", s.excluded_non_sw_company_count_sum, "与源资源摘要勾稽"],
  ["公司唯一行业数", "='运行摘要'!B8", s.unique_industry_count, "行业代码去重"],
  ["公司唯一A股数", "='运行摘要'!B9", s.unique_company_count, "公司代码去重"],
  ["可见联系方式异常", `=COUNTIF('匹配明细'!$U$3:$U$${detailBlock.endRow},"<>已隐藏")`, 0, "需审批/不允许不得显示联系方式"],
  ["非港股排除异常", `=COUNTIF('不纳入资源匹配'!$C$3:$C$${excludedLast},"<>港股")`, 0, "当前排除清单应仅包含港股"],
];
checks.getRange("A3:A17").values = checkRows.map((row) => [row[0]]);
checks.getRange("B3:B17").formulas = checkRows.map((row) => [row[1]]);
checks.getRange("C3:C17").values = checkRows.map((row) => [row[2]]);
checks.getRange("D3:D17").formulas = checkRows.map((_, index) => [`=B${index + 3}-C${index + 3}`]);
checks.getRange("E3:E17").formulas = checkRows.map((_, index) => [`=IF(D${index + 3}=0,"OK","FAIL")`]);
checks.getRange("F3:F17").values = checkRows.map((row) => [row[3]]);
checks.getRange("A2:F17").format.borders = { insideHorizontal: { style: "thin", color: "#D9E2EC" } };
checks.getRange("E3:E17").conditionalFormats.addCustom('=$E3="OK"', { fill: GREEN, font: { bold: true } });
checks.getRange("E3:E17").conditionalFormats.addCustom('=$E3="FAIL"', { fill: RED, font: { color: "#9C0006", bold: true } });
checks.getRange("A:A").format.columnWidth = 28;
checks.getRange("B:E").format.columnWidth = 15;
checks.getRange("F:F").format.columnWidth = 46;
checks.freezePanes.freezeRows(2);

const sources = workbook.worksheets.add("来源与口径");
sources.showGridLines = false;
sources.getRange("A1:D1").merge();
sources.getRange("A1").values = [[`${companyLabel} ${s.quarter} 来源与口径`]];
sources.getRange("A1:D1").format = { fill: NAVY, font: { bold: true, color: "#FFFFFF", size: 15 }, rowHeight: 30 };
sources.getRange("A3:B3").values = [["项目", "确定性规则"]];
sources.getRange("A3:B3").format = { fill: TEAL, font: { bold: true, color: "#FFFFFF" } };
const ruleEnd = data.rules.length + 3;
sources.getRange(`A4:B${ruleEnd}`).values = data.rules.map((row) => [row.item, row.rule]);
sources.getRange(`A4:B${ruleEnd}`).format.wrapText = true;
const sourceStart = ruleEnd + 3;
sources.getRange(`A${sourceStart}:D${sourceStart}`).values = [["基金经理", "源文件状态", "源文件SHA-256", "源文件路径"]];
sources.getRange(`A${sourceStart}:D${sourceStart}`).format = { fill: TEAL, font: { bold: true, color: "#FFFFFF" } };
const sourceEnd = sourceStart + data.source_files.length;
sources.getRange(`A${sourceStart + 1}:D${sourceEnd}`).values = data.source_files.map((row) => [row.manager, row.status, row.sha256, row.path]);
sources.getRange(`A${sourceStart + 1}:D${sourceEnd}`).format.wrapText = true;
const noteStart = sourceEnd + 3;
const registryFile = data.candidate_confirmation?.registry_files?.[0] || {};
sources.getRange(`A${noteStart}:D${noteStart + 6}`).merge();
sources.getRange(`A${noteStart}`).values = [[`人员库：${data.personnel_file || "未记录"}\n人员库SHA-256：${data.personnel_sha256 || "未记录"}\n生成时间（北京时间）：${data.generated_at_beijing}\n业务确认：${data.candidate_confirmation?.decision || "未记录"}；确认来源：${data.candidate_confirmation?.confirmed_by || "未记录"}；确认时间：${data.candidate_confirmation?.confirmed_at_beijing || "未记录"}\n候选快照SHA-256：${data.candidate_confirmation?.candidate_snapshot_sha256 || "未记录"}\n确认规则库：${registryFile.path || "未记录"}\n确认规则库SHA-256：${registryFile.sha256 || "未记录"}`]];
sources.getRange(`A${noteStart}:D${noteStart + 6}`).format = { fill: PALE, wrapText: true, verticalAlignment: "center" };
sources.getRange("A:A").format.columnWidth = 24;
sources.getRange("B:B").format.columnWidth = 96;
sources.getRange("C:C").format.columnWidth = 68;
sources.getRange("D:D").format.columnWidth = 96;
sources.freezePanes.freezeRows(3);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const previewRanges = [
  ["运行摘要", "A1:H21"],
  ["基金经理概览", `A1:J${Math.min(managerBlock.endRow, 30)}`],
  ["行业需求汇总", `A1:K${Math.min(industryBlock.endRow, 35)}`],
  ["公司需求汇总", `A1:Q${Math.min(companyBlock.endRow, 45)}`],
  ["人员对接汇总", `A1:Q${Math.min(personBlock.endRow, 45)}`],
  ["匹配明细", `A1:U${Math.min(detailBlock.endRow, 45)}`],
  ["待确认事项", `A1:U${Math.min(candidateBlock.endRow, 45)}`],
  ["待补充项", `A1:H${Math.min(pendingBlock.endRow, 20)}`],
  ["不纳入资源匹配", `A1:J${Math.min(excludedBlock.endRow, 35)}`],
  ["数据校验", "A1:F17"],
  ["来源与口径", `A1:D${Math.min(noteStart + 6, 45)}`],
];
for (const [sheetName, range] of previewRanges) {
  const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
}

const summaryCheck = await workbook.inspect({ kind: "table", range: "运行摘要!A1:H21", include: "values,formulas", tableMaxRows: 24, tableMaxCols: 10 });
console.log(summaryCheck.ndjson);
const checksCheck = await workbook.inspect({ kind: "table", range: "数据校验!A1:F17", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 8 });
console.log(checksCheck.ndjson);
const oilCheck = await workbook.inspect({ kind: "match", searchTerm: "中国石油|通源石油", options: { useRegex: true, maxResults: 50 }, summary: "petroleum routing audit" });
console.log(oilCheck.ndjson);
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 200 }, summary: "final formula error scan" });
console.log(errorCheck.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`XLSX=${outputPath}`);
