import type { DisplayPayload } from "../types/api";
import { barLength } from "./scales";

export interface RankedBar {
  label: string;
  value: number;
  column: string;
}

export function rankChartRows(display: Extract<DisplayPayload, { kind: "chart" }>, limit = 500): {
  bars: RankedBar[];
  hidden: number;
  column: string | null;
} {
  const column = numericColumn(display);
  if (!column) return { bars: [], hidden: 0, column: null };
  const bars: RankedBar[] = [];
  for (const row of display.rows) {
    const value = cellNumber(row[column]);
    if (value === null) continue;
    bars.push({ label: rowLabel(row, display.columns, column), value, column });
  }
  bars.sort((left, right) => right.value - left.value || left.label.localeCompare(right.label));
  if (bars.length <= limit) return { bars, hidden: 0, column };
  return { bars: bars.slice(0, limit), hidden: bars.length - limit, column };
}

export function barWidths(bars: readonly RankedBar[], width: number): number[] {
  const maxAbs = bars.reduce((max, bar) => Math.max(max, Math.abs(bar.value)), 0);
  return bars.map((bar) => barLength(bar.value, maxAbs, width));
}

export function cellNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "boolean" || value === null || value === undefined) return null;
  if (typeof value === "string") {
    const text = value.trim();
    if (!text || !/^[-+]?\d+(\.\d+)?$/.test(text)) return null;
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }
  if (typeof value === "object" && "kind" in value && "value" in value) {
    const cell = value as { kind?: unknown; value?: unknown; datatype?: unknown };
    if (cell.kind !== "literal" || typeof cell.value !== "string") return null;
    const datatype = typeof cell.datatype === "string" ? cell.datatype : "";
    const numericType = /integer|int|double|float|decimal|long|short|byte/i.test(datatype);
    if (!numericType && !/^[-+]?\d+(\.\d+)?$/.test(cell.value)) return null;
    const parsed = Number(cell.value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function numericColumn(display: Extract<DisplayPayload, { kind: "chart" }>): string | null {
  for (const column of display.numericColumns) {
    if (display.columns.includes(column)) return column;
  }
  for (const column of display.columns) {
    const values = display.rows.map((row) => row[column]).filter((value) => value !== null && value !== undefined);
    if (values.length > 0 && values.every((value) => cellNumber(value) !== null)) return column;
  }
  return null;
}

function rowLabel(row: Record<string, unknown>, columns: readonly string[], valueColumn: string): string {
  for (const column of columns) {
    if (column === valueColumn) continue;
    const value = row[column];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (value && typeof value === "object" && "value" in value) {
      const cell = value as { value?: unknown };
      if (typeof cell.value === "string" && cell.value.trim()) return cell.value;
    }
  }
  return valueColumn;
}
