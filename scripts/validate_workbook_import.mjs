import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [inputPath] = process.argv.slice(2);
if (!inputPath) throw new Error("usage: validate_workbook_import.mjs input.xlsx");

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheets = workbook.worksheets.items.map((sheet) => sheet.name);
const summary = await workbook.inspect({
  kind: "table",
  range: "运行摘要!A1:H14",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 10,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 200 },
  summary: "reimport formula error scan",
});
console.log(JSON.stringify({ inputPath, sheetCount: sheets.length, sheets }));
console.log(summary.ndjson);
console.log(errors.ndjson);
