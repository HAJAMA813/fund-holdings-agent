import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [outputRoot, ...inputPaths] = process.argv.slice(2);
if (!outputRoot || inputPaths.length === 0) {
  throw new Error("usage: verify_python_workbooks.mjs output-root input1.xlsx [input2.xlsx ...]");
}

await fs.mkdir(outputRoot, { recursive: true });
const results = [];
for (const inputPath of inputPaths) {
  const input = await FileBlob.load(inputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const workbookName = path.basename(inputPath, path.extname(inputPath));
  const previewRoot = path.join(outputRoot, workbookName);
  await fs.mkdir(previewRoot, { recursive: true });
  const sheets = workbook.worksheets.items.map((sheet) => sheet.name);
  for (const sheetName of sheets) {
    const image = await workbook.render({ sheetName, range: "A1:Z30", scale: 0.8, format: "png" });
    await fs.writeFile(path.join(previewRoot, `${sheetName}.png`), new Uint8Array(await image.arrayBuffer()));
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 500 },
    summary: "pure Python workbook formula error scan",
  });
  results.push({ inputPath, sheetCount: sheets.length, sheets, errorScan: errors.ndjson });
}
console.log(JSON.stringify(results));
