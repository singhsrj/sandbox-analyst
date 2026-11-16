import type { ColumnKind } from "./types";

/** The dataset whose profile the workspace shows (uploads add more ids later). */
export const SAMPLE_DATASET = "sample";

export const KIND_LABEL: Record<ColumnKind, string> = {
  id: "Identifier",
  pii: "Personal data",
  boolean: "Yes / no",
  datetime: "Date",
  numeric: "Number",
  categorical: "Category",
  text: "Free text",
};

/** How strong a correlation is, in words (Spearman's rho). */
export function correlationStrength(r: number | null): string {
  if (r === null) return "not defined";
  const a = Math.abs(r);
  const size = a >= 0.7 ? "strong" : a >= 0.4 ? "moderate" : a >= 0.2 ? "weak" : "none";
  return size === "none" ? "no clear link" : `${size} ${r > 0 ? "positive" : "negative"}`;
}
