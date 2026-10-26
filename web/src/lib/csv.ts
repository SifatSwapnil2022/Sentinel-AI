/** CSV for "Download CSV" on every tile: RFC 4180 quoting, a header row, empty for null. */

export type Cell = string | number | boolean | null | undefined;
export type Row = Record<string, Cell>;

function field(value: Cell): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "boolean" ? String(value) : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCsv(rows: readonly Row[], columns?: readonly string[]): string {
  const first = rows[0];
  const header = columns ?? (first ? Object.keys(first) : []);
  if (header.length === 0) return "";
  const lines = [header.map(field).join(",")];
  for (const row of rows) lines.push(header.map((c) => field(row[c])).join(","));
  return `${lines.join("\n")}\n`;
}

/** Save text as a file in the browser. */
export function download(filename: string, text: string, type = "text/csv;charset=utf-8"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** "sentinel_fraud-screen_accuracy_2026-09-25_2026-10-24.csv" */
export function csvName(...parts: string[]): string {
  return `${["sentinel", ...parts].map((p) => p.replace(/[^\w.-]+/g, "-")).join("_")}.csv`;
}
