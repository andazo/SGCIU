import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const artifactModules = process.env.SGCIU_ARTIFACT_NODE_MODULES;
if (!artifactModules) {
  throw new Error("Defina SGCIU_ARTIFACT_NODE_MODULES con el runtime de artifact-tool.");
}
const requireFromRuntime = createRequire(path.join(artifactModules, "artifact-loader.cjs"));
const { SpreadsheetFile, Workbook } = requireFromRuntime("@oai/artifact-tool");

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("Uso: node build_hybrid_workbook.mjs <reporte.json> <salida.xlsx>");
}

const report = JSON.parse(await fs.readFile(inputPath, "utf8"));
const executions = report.executions ?? [];
const incidentLastRow = 5 + executions.length;
const font = "Arial";
const headerFill = "#1F4E78";
const lightBlue = "#D9EAF7";
const inputFill = "#FFF2CC";
const muted = "#F3F6F8";

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Resumen");
const incidents = workbook.worksheets.add("Incidentes");
const conversations = workbook.worksheets.add("Conversaciones");
const clustering = workbook.worksheets.add("Clustering");
const rawMetrics = workbook.worksheets.add("Metricas raw");
const rubric = workbook.worksheets.add("Rubrica");

for (const sheet of [summary, incidents, conversations, clustering, rawMetrics, rubric]) {
  sheet.showGridLines = false;
  sheet.getRange("A1:AZ300").format.font = { name: font, size: 10, color: "#1F2937" };
}

function title(sheet, text, endColumn) {
  sheet.getRange("A2").values = [[text]];
  sheet.getRange(`A2:${endColumn}2`).format.font = { name: font, size: 14, bold: true };
  sheet.getRange(`A3:${endColumn}3`).format.borders = {
    bottom: { style: "thin", color: "#7F8C8D" },
  };
}

function header(sheet, range) {
  const target = sheet.getRange(range);
  target.format = {
    fill: headerFill,
    font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#FFFFFF" },
  };
}

title(summary, "Métricas híbridas de SGCIU", "H");
summary.getRange("A5:B10").values = [
  ["ID de corrida", report.run_id],
  ["Versión del dataset", report.dataset_version],
  ["Hash del dataset", report.dataset_sha256],
  ["Entorno", report.execution_environment],
  ["Modelo actor", report.actor_model],
  ["Coste del actor incluido", report.actor_cost_included_in_metrics ? "Sí" : "No"],
];
summary.getRange("A5:A10").format.font = { name: font, bold: true };
summary.getRange("A5:B10").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };

summary.getRange("A13:C13").values = [["Métrica", "Valor", "Definición"]];
header(summary, "A13:C13");
const metricRows = [
  ["Casos", `=COUNTA(Incidentes!A6:A${incidentLastRow})`, "Escenarios ejecutados"],
  ["Validaciones manuales de categoría", `=COUNTIFS(Incidentes!L6:L${incidentLastRow},\"<>\")`, "Filas revisadas por la persona evaluadora"],
  [
    "Exactitud manual de categoría",
    `=IF(COUNTIFS(Incidentes!L6:L${incidentLastRow},\"<>\")=0,\"n.a.\",COUNTIFS(Incidentes!L6:L${incidentLastRow},\"SÍ\")/COUNTIFS(Incidentes!L6:L${incidentLastRow},\"<>\"))`,
    "Solo sobre casos con SÍ o NO manual",
  ],
  ["Exactitud automática de categoría", report.metrics.field_accuracy.category, "Etiqueta esperada vs. extracción"],
  ["Exactitud de distrito", report.metrics.field_accuracy.district, "Etiqueta esperada vs. extracción"],
  ["Exactitud de relación", report.metrics.field_accuracy.relation, "Etiqueta esperada vs. extracción"],
  ["Exactitud de tipo de lugar", report.metrics.field_accuracy.place_type, "Etiqueta esperada vs. extracción"],
  ["Exactitud de fecha", report.metrics.field_accuracy.event_date, "Coincidencia de día normalizado"],
  ["Latencia media (ms)", report.metrics.latency_ms.average, "Suma de llamadas de intake por caso"],
  ["Latencia p50 (ms)", report.metrics.latency_ms.p50, "Percentil 50 por caso"],
  ["Latencia p95 (ms)", report.metrics.latency_ms.p95, "Percentil 95 por caso"],
  ["Coste SGCIU (USD)", report.metrics.application_usage.estimated_cost_usd, "No incluye el actor ciudadano"],
  ["Coste SGCIU por caso (USD)", report.metrics.application_usage.estimated_cost_per_case_usd, "No incluye el actor ciudadano"],
  ["Clustering F1", report.metrics.clustering.pairwise_f1, "Pares esperados contra pares predichos"],
];
summary.getRange(`A14:C${13 + metricRows.length}`).values = metricRows;
summary.getRange(`A14:C${13 + metricRows.length}`).format.borders = {
  preset: "inside",
  style: "thin",
  color: "#E5E7EB",
};
summary.getRange("B16:B21").format.numberFormat = "0.0%";
summary.getRange("B22:B24").format.numberFormat = "#,##0.00";
summary.getRange("B25:B26").format.numberFormat = "0.000000";
summary.getRange("B27").format.numberFormat = "0.0%";
summary.getRange("A14:C16").format.fill = lightBlue;
summary.getRange("A30:C35").values = [
  ["Clustering", "Valor", ""],
  ["Pares esperados", report.metrics.clustering.expected_pairs, ""],
  ["Pares predichos", report.metrics.clustering.predicted_pairs, ""],
  ["Precisión", report.metrics.clustering.pairwise_precision, ""],
  ["Recall", report.metrics.clustering.pairwise_recall, ""],
  ["F1", report.metrics.clustering.pairwise_f1, ""],
];
header(summary, "A30:C30");
summary.getRange("B33:B34").format.numberFormat = "0.0%";
summary.getRange("B35").format.numberFormat = "0.0%";
summary.getRange("A30:C35").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
summary.getRange("A:A").format.columnWidth = 31;
summary.getRange("B:B").format.columnWidth = 22;
summary.getRange("C:C").format.columnWidth = 43;

title(incidents, "Incidentes híbridos y validación manual", "AE");
const incidentHeaders = [
  "Caso", "ID incidente", "Canal", "Persona", "Grupo esperado", "Cluster obtenido",
  "Fecha del hecho", "Fecha de registro", "Relato inicial", "Categoría esperada",
  "Categoría obtenida", "Validación categoría (SÍ/NO)", "Distrito esperado",
  "Distrito obtenido", "Validación distrito (SÍ/NO)", "Relación esperada",
  "Relación obtenida", "Validación relación (SÍ/NO)", "Lugar esperado", "Lugar obtenido",
  "Validación lugar (SÍ/NO)", "Fecha esperada", "Fecha obtenida", "Validación fecha (SÍ/NO)",
  "Dirección esperada", "Dirección obtenida", "Resumen generado", "Precisión temporal",
  "Turnos intake", "Latencia (ms)", "Tokens entrada", "Tokens salida", "Coste SGCIU (USD)",
  "Cierre forzado", "Notas manuales",
];
incidents.getRange(`A5:AI5`).values = [incidentHeaders];
header(incidents, "A5:AI5");
const incidentRows = executions.map((item) => [
  item.case_id,
  item.incident_id,
  item.channel,
  item.persona,
  item.cluster_group,
  item.actual_cluster_id,
  item.occurred_at,
  item.recorded_at,
  item.facts,
  item.expected.category,
  item.actual.category,
  null,
  item.expected.district,
  item.actual.district,
  null,
  item.expected.relation,
  item.actual.relation,
  null,
  item.expected.place_type,
  item.actual.place_type,
  null,
  item.expected.event_date,
  item.actual.event_date,
  null,
  item.expected.address,
  item.actual.address,
  item.actual.summary,
  item.actual.temporal_precision,
  item.application_usage.turns,
  item.application_usage.latency_ms,
  item.application_usage.input_tokens,
  item.application_usage.output_tokens,
  item.application_usage.estimated_cost_usd,
  item.forced_finish ? "Sí" : "No",
  null,
]);
incidents.getRange(`A6:AI${5 + incidentRows.length}`).values = incidentRows;
incidents.tables.add(`A5:AI${5 + incidentRows.length}`, true, "HybridIncidents");
for (const column of ["L", "O", "R", "U", "X"]) {
  incidents.getRange(`${column}6:${column}${5 + incidentRows.length}`).dataValidation = {
    rule: { type: "list", values: ["SÍ", "NO"] },
  };
  incidents.getRange(`${column}6:${column}${5 + incidentRows.length}`).format.fill = inputFill;
}
incidents.getRange(`AI6:AI${5 + incidentRows.length}`).format.fill = inputFill;
incidents.getRange(`G6:H${5 + incidentRows.length}`).format.numberFormat = "yyyy-mm-dd hh:mm";
incidents.getRange(`AD6:AD${5 + incidentRows.length}`).format.numberFormat = "#,##0.00";
incidents.getRange(`AG6:AG${5 + incidentRows.length}`).format.numberFormat = "0.000000";
incidents.getRange(`I6:I${5 + incidentRows.length}`).format.wrapText = true;
incidents.getRange(`AA6:AA${5 + incidentRows.length}`).format.wrapText = true;
incidents.freezePanes.freezeRows(5);
incidents.freezePanes.freezeColumns(2);
for (const column of ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "AB", "AC", "AD", "AE", "AF", "AG", "AH"]) {
  incidents.getRange(`${column}:${column}`).format.columnWidth = 15;
}
for (const column of ["I", "Y", "Z", "AA", "AI"]) {
  incidents.getRange(`${column}:${column}`).format.columnWidth = 34;
}

title(conversations, "Conversaciones registradas", "E");
conversations.getRange("A5:E5").values = [["Caso", "ID incidente", "Secuencia", "Rol", "Mensaje"]];
header(conversations, "A5:E5");
const conversationRows = [];
for (const item of executions) {
  for (const [index, message] of (item.conversation ?? []).entries()) {
    conversationRows.push([item.case_id, item.incident_id, index + 1, message.role, message.content]);
  }
}
conversations.getRange(`A6:E${5 + conversationRows.length}`).values = conversationRows;
conversations.tables.add(`A5:E${5 + conversationRows.length}`, true, "HybridConversations");
conversations.getRange(`E6:E${5 + conversationRows.length}`).format.wrapText = true;
conversations.freezePanes.freezeRows(5);
conversations.getRange("A:A").format.columnWidth = 14;
conversations.getRange("B:B").format.columnWidth = 13;
conversations.getRange("C:D").format.columnWidth = 12;
conversations.getRange("E:E").format.columnWidth = 80;

title(clustering, "Grupos de clustering", "F");
clustering.getRange("A5:F5").values = [[
  "Caso", "ID incidente", "Grupo esperado", "Cluster obtenido", "Categoría", "Fecha del hecho",
]];
header(clustering, "A5:F5");
const clusterRows = executions.map((item) => [
  item.case_id,
  item.incident_id,
  item.cluster_group ?? "Sin grupo",
  item.actual_cluster_id ?? "Sin cluster",
  item.actual.category,
  item.occurred_at,
]);
clustering.getRange(`A6:F${5 + clusterRows.length}`).values = clusterRows;
clustering.tables.add(`A5:F${5 + clusterRows.length}`, true, "HybridClustering");
clustering.getRange(`F6:F${5 + clusterRows.length}`).format.numberFormat = "yyyy-mm-dd hh:mm";
clustering.freezePanes.freezeRows(5);
clustering.getRange("A:F").format.columnWidth = 18;

title(rawMetrics, "Métricas automáticas de la corrida", "C");
rawMetrics.getRange("A5:C5").values = [["Métrica", "Valor", "Unidad"]];
header(rawMetrics, "A5:C5");
const rawRows = [
  ["Casos", report.metrics.cases, "casos"],
  ["Latencia media", report.metrics.latency_ms.average, "ms"],
  ["Latencia p50", report.metrics.latency_ms.p50, "ms"],
  ["Latencia p95", report.metrics.latency_ms.p95, "ms"],
  ["Tokens de entrada", report.metrics.application_usage.input_tokens, "tokens"],
  ["Tokens de salida", report.metrics.application_usage.output_tokens, "tokens"],
  ["Coste SGCIU", report.metrics.application_usage.estimated_cost_usd, "USD"],
  ["Coste por caso", report.metrics.application_usage.estimated_cost_per_case_usd, "USD"],
  ["Precisión clustering", report.metrics.clustering.pairwise_precision, "proporción"],
  ["Recall clustering", report.metrics.clustering.pairwise_recall, "proporción"],
  ["F1 clustering", report.metrics.clustering.pairwise_f1, "proporción"],
];
rawMetrics.getRange(`A6:C${5 + rawRows.length}`).values = rawRows;
rawMetrics.getRange(`A5:C${5 + rawRows.length}`).format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
rawMetrics.getRange("B7:B9").format.numberFormat = "#,##0.00";
rawMetrics.getRange("B12:B13").format.numberFormat = "0.000000";
rawMetrics.getRange("B14:B16").format.numberFormat = "0.0%";
rawMetrics.getRange("A:C").format.columnWidth = 28;

title(rubric, "Rúbrica de revisión manual", "C");
rubric.getRange("A5:C5").values = [["Campo", "Marcar SÍ cuando", "Marcar NO cuando"]];
header(rubric, "A5:C5");
rubric.getRange("A6:C10").values = [
  ["Categoría", "La clasificación representa correctamente el hecho principal.", "Clasifica otro tipo de incidente o no hay base suficiente."],
  ["Distrito", "El distrito coincide con la referencia dada por la persona.", "Asigna un distrito diferente o inventa uno."],
  ["Relación", "Distingue correctamente víctima, testigo, vecino, comerciante u otra.", "Confunde a quien reporta con una tercera persona."],
  ["Tipo de lugar", "Representa el lugar donde ocurrió el hecho.", "Confunde el punto de referencia con el lugar del incidente."],
  ["Fecha", "El día normalizado coincide con el hecho reportado.", "Cambia el día o no normaliza una fecha expresada con claridad."],
];
rubric.getRange("A5:C10").format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
rubric.getRange("B6:C10").format.wrapText = true;
rubric.getRange("A:A").format.columnWidth = 18;
rubric.getRange("B:C").format.columnWidth = 62;
rubric.getRange("A6:C10").format.fill = muted;

workbook.recalculate();
const summaryCheck = await workbook.inspect({
  kind: "table",
  range: "Resumen!A5:C35",
  include: "values,formulas",
  tableMaxRows: 35,
  tableMaxCols: 3,
});
console.log(summaryCheck.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "hybrid workbook formula error scan",
});
console.log(formulaErrors.ndjson);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
for (const [sheetName, range, fileName] of [
  ["Resumen", "A1:C35", "preview-resumen.png"],
  ["Incidentes", "A1:AI15", "preview-incidentes.png"],
  ["Conversaciones", "A1:E25", "preview-conversaciones.png"],
  ["Clustering", "A1:F20", "preview-clustering.png"],
  ["Metricas raw", "A1:C17", "preview-metricas.png"],
  ["Rubrica", "A1:C10", "preview-rubrica.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(
    path.join(path.dirname(outputPath), fileName),
    new Uint8Array(await preview.arrayBuffer()),
  );
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
