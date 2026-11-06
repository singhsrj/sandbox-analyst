/** Parsers for the text our backend tools return (api/app/tools/analyst_tools.py). */

export type SqlOutput =
  | {
      kind: "ok";
      rows: number;
      columnCount: number;
      file: string;
      warning: string | null;
      columns: { name: string; type: string }[];
      header: string[];
      preview: string[][];
    }
  | { kind: "rejected" | "error" | "timeout" | "unknown"; message: string };

const OK_LINE = /^OK: ([\d,]+) rows x (\d+) columns saved to (\S+)/;

const EDIT_NOTICE = /^Note: a human reviewer replaced this tool call[\s\S]*?Executed instead: \S+ with arguments (\{[\s\S]*?\})\.(?:\n\nTool response:\n?)?/;

/**
 * When a reviewer edited a query, LangChain prefixes the tool result with a notice naming the call
 * that really ran. Split it off so the result parses normally, and return the SQL that executed.
 */
export function splitEditNotice(text: string): { executedQuery: string | null; rest: string } {
  const match = EDIT_NOTICE.exec(text);
  if (!match) return { executedQuery: null, rest: text };
  let executedQuery: string | null = null;
  try {
    const args = JSON.parse(match[1]) as { query?: unknown };
    if (typeof args.query === "string") executedQuery = args.query;
  } catch {
    /* unexpected shape: still strip the notice */
  }
  return { executedQuery, rest: text.slice(match[0].length) };
}

export function parseSqlOutput(text: string): SqlOutput {
  const trimmed = text.trim();
  for (const [prefix, kind] of [
    ["SQL REJECTED:", "rejected"],
    ["SQL ERROR:", "error"],
    ["SQL TIMEOUT:", "timeout"],
  ] as const) {
    if (trimmed.startsWith(prefix)) return { kind, message: trimmed.slice(prefix.length).trim() };
  }
  const lines = trimmed.split("\n");
  const ok = OK_LINE.exec(lines[0] ?? "");
  if (!ok) return { kind: "unknown", message: trimmed };

  let warning: string | null = null;
  let columns: { name: string; type: string }[] = [];
  let header: string[] = [];
  const preview: string[][] = [];
  let inPreview = false;
  for (const line of lines.slice(1)) {
    if (line.startsWith("WARNING:")) warning = line.slice(8).trim();
    else if (line.startsWith("Columns: ")) {
      columns = line
        .slice(9)
        .split(/,\s(?=[^,]+ \()/)
        .map((c) => {
          const m = /^(.*?) \((.*)\)$/.exec(c.trim()); // type may itself contain parentheses
          return { name: m?.[1] ?? c.trim(), type: m?.[2] ?? "" };
        });
    } else if (line.startsWith("Preview")) inPreview = true;
    else if (inPreview && header.length === 0 && line.trim()) header = line.split(" | "); // one column: no pipe
    else if (inPreview && header.length > 0 && line.trim()) preview.push(line.split(" | "));
  }
  return {
    kind: "ok",
    rows: Number(ok[1].replace(/,/g, "")),
    columnCount: Number(ok[2]),
    file: ok[3],
    warning,
    columns,
    header,
    preview,
  };
}

/** Minimal RFC 4180 CSV parser for previews (quotes, escaped quotes, newlines inside fields). */
export function parseCsv(
  text: string,
  maxRows = 50,
): { header: string[]; rows: string[][]; truncated: boolean } {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let quoted = false;
  let truncated = false;
  const pushRow = () => {
    row.push(field);
    field = "";
    if (row.length > 1 || row[0] !== "") rows.push(row);
    row = [];
  };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      pushRow();
      if (rows.length > maxRows + 1) {
        truncated = true;
        break;
      }
    } else field += c;
  }
  if (!truncated && (field !== "" || row.length > 0)) pushRow();
  const [header = [], ...body] = rows;
  if (body.length > maxRows) truncated = true;
  return { header, rows: body.slice(0, maxRows), truncated };
}
