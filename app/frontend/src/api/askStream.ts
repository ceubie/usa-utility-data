import { POLYGON_CAP } from "../limits";
import type { AskEvent, DisplayPayload } from "../types/api";
import { assertNever } from "../types/graph";
import { capGraph, graphFromDisplay, mergeGraph } from "../viz/graphData";
import { emptyGraph, type GraphData } from "../types/graph";
import { readDetail, resolveUrl, type RequestOptions } from "./http";

export interface ToolStep {
  callId: string;
  name: string;
  arguments: unknown;
  summary: string;
}

export interface AskMapFocus {
  serviceAreaIds: string[];
  countyGeoids: string[];
}

export interface AskPresentation {
  markdown: string;
  error: string | null;
  missing: string[];
  steps: ToolStep[];
  queries: string[];
  graph: GraphData | null;
  map: AskMapFocus | null;
  chart: Extract<DisplayPayload, { kind: "chart" }> | null;
  drewEntities: boolean;
}

export interface RawSse {
  event: string;
  data: string;
}

export interface AskHooks {
  onEntities: (presentation: AskPresentation) => void;
}

export function parseSseBuffer(buffer: string): { events: RawSse[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const parts = normalized.split("\n\n");
  const rest = parts.pop() ?? "";
  const events: RawSse[] = [];
  for (const part of parts) {
    const parsed = parseSseBlock(part);
    if (parsed) events.push(parsed);
  }
  return { events, rest };
}

export function askEventFromSse(raw: RawSse): AskEvent {
  let payload: unknown;
  try {
    payload = JSON.parse(raw.data) as unknown;
  } catch {
    return { event: "error", message: "Ask returned an event that was not JSON." };
  }
  const record = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  switch (raw.event) {
    case "status":
      return { event: "status", message: stringField(record, "message") };
    case "answer_delta":
      return { event: "answer_delta", text: stringField(record, "text") };
    case "tool_call":
      return {
        event: "tool_call",
        callId: stringField(record, "call_id"),
        name: stringField(record, "name"),
        arguments: record.arguments ?? null,
      };
    case "tool_result":
      return {
        event: "tool_result",
        callId: stringField(record, "call_id"),
        name: stringField(record, "name"),
        result: record.result ?? null,
      };
    case "display":
      return displayEvent(record);
    case "done":
      return { event: "done", answer: stringField(record, "answer") };
    case "error":
      return {
        event: "error",
        message: stringField(record, "message") || "Ask failed.",
        missing: stringList(record.missing),
      };
    default:
      return { event: "error", message: `Unknown ask event: ${raw.event}` };
  }
}

export async function* readAskEvents(stream: ReadableStream<Uint8Array>): AsyncGenerator<AskEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseBuffer(buffer);
      buffer = parsed.rest;
      for (const raw of parsed.events) yield askEventFromSse(raw);
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      const parsed = parseSseBuffer(`${buffer}\n\n`);
      for (const raw of parsed.events) yield askEventFromSse(raw);
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* askQuestion(question: string, options?: RequestOptions): AsyncGenerator<AskEvent> {
  const fetchImpl = options?.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(resolveUrl("/api/ask", options?.baseUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question }),
      signal: options?.signal,
    });
  } catch (error) {
    if (options?.signal?.aborted) return;
    const message = error instanceof Error ? error.message : "Ask failed.";
    yield { event: "error", message };
    return;
  }
  if (!response.ok) {
    yield { event: "error", message: await readDetail(response) };
    return;
  }
  if (!response.body) {
    yield { event: "error", message: "Ask returned an empty response." };
    return;
  }
  yield* readAskEvents(response.body);
}

export function previewAsk(events: readonly AskEvent[]): AskPresentation {
  const presentation = consumeAskEvents(events);
  return { ...presentation, graph: null, map: null, chart: null, drewEntities: false };
}

export function consumeAskEvents(events: readonly AskEvent[]): AskPresentation {
  let markdown = "";
  let error: string | null = null;
  let missing: string[] = [];
  const steps: ToolStep[] = [];
  const queries: string[] = [];
  let graph: GraphData | null = null;
  let map: AskMapFocus | null = null;
  let chart: AskPresentation["chart"] = null;

  for (const item of events) {
    switch (item.event) {
      case "status":
        break;
      case "answer_delta":
        markdown += item.text;
        break;
      case "done":
        if (item.answer) markdown = item.answer;
        break;
      case "error":
        error = item.message;
        missing = item.missing ?? [];
        graph = null;
        map = null;
        chart = null;
        break;
      case "tool_call":
        steps.push({
          callId: item.callId,
          name: item.name,
          arguments: item.arguments,
          summary: "running",
        });
        queries.push(...queriesFromCall(item.name, item.arguments));
        break;
      case "tool_result": {
        const summary = summarizeToolResult(item.result);
        const step = steps.find((candidate) => candidate.callId === item.callId);
        if (step) step.summary = summary;
        else steps.push({ callId: item.callId, name: item.name, arguments: null, summary });
        break;
      }
      case "display":
        if (error) break;
        switch (item.display.kind) {
          case "graph":
            graph = capGraph(mergeGraph(graph ?? emptyGraph(), graphFromDisplay(item.display)));
            break;
          case "map":
            map = {
              serviceAreaIds: unique(item.display.serviceAreaIds).slice(0, POLYGON_CAP),
              countyGeoids: unique(item.display.countyGeoids),
            };
            break;
          case "chart":
            chart = item.display;
            break;
          default:
            assertNever(item.display);
        }
        break;
      default:
        assertNever(item);
    }
  }

  if (error) {
    graph = null;
    map = null;
    chart = null;
  }
  const drewEntities = !error && hasEntities(graph, map, chart);
  return {
    markdown,
    error,
    missing,
    steps,
    queries,
    graph: drewEntities ? graph : null,
    map: drewEntities ? map : null,
    chart: drewEntities ? chart : null,
    drewEntities,
  };
}

function hasEntities(
  graph: GraphData | null,
  map: AskMapFocus | null,
  chart: AskPresentation["chart"],
): boolean {
  if (graph && graph.nodes.length > 0) return true;
  if (map && (map.serviceAreaIds.length > 0 || map.countyGeoids.length > 0)) return true;
  return chart !== null;
}

function parseSseBlock(block: string): RawSse | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const index = line.indexOf(":");
    const field = index === -1 ? line : line.slice(0, index);
    const raw = index === -1 ? "" : line.slice(index + 1).replace(/^ /, "");
    if (field === "event") event = raw;
    if (field === "data") data.push(raw);
  }
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

function displayEvent(record: Record<string, unknown>): AskEvent {
  const kind = record.kind;
  if (kind !== "graph" && kind !== "map" && kind !== "chart") {
    return { event: "error", message: "The display event did not name a graph, map, or chart." };
  }
  switch (kind) {
    case "graph": {
      const display = graphDisplay(record);
      return display
        ? { event: "display", display }
        : { event: "error", message: "The graph display was incomplete." };
    }
    case "map": {
      const display = mapDisplay(record);
      return display
        ? { event: "display", display }
        : { event: "error", message: "The map display was incomplete." };
    }
    case "chart": {
      const display = chartDisplay(record);
      return display
        ? { event: "display", display }
        : { event: "error", message: "The chart display was incomplete." };
    }
    default:
      return assertNever(kind);
  }
}

function graphDisplay(record: Record<string, unknown>): Extract<DisplayPayload, { kind: "graph" }> | null {
  if (!Array.isArray(record.nodes) || !Array.isArray(record.links)) return null;
  const nodes = [];
  for (const node of record.nodes) {
    if (!node || typeof node !== "object") return null;
    const item = node as Record<string, unknown>;
    if (typeof item.iri !== "string") return null;
    nodes.push({
      iri: item.iri,
      label: typeof item.label === "string" ? item.label : item.iri,
      kind: typeof item.kind === "string" ? item.kind : "",
      state: typeof item.state === "string" ? item.state : "",
    });
  }
  const links = [];
  for (const link of record.links) {
    if (!link || typeof link !== "object") return null;
    const item = link as Record<string, unknown>;
    if (typeof item.source !== "string" || typeof item.target !== "string") return null;
    links.push({
      source: item.source,
      predicate: typeof item.predicate === "string" ? item.predicate : "",
      target: item.target,
    });
  }
  return {
    kind: "graph",
    nodes,
    links,
    dropped: typeof record.dropped === "number" ? record.dropped : 0,
  };
}

function mapDisplay(record: Record<string, unknown>): Extract<DisplayPayload, { kind: "map" }> | null {
  const areas = record.service_area_ids ?? record.serviceAreaIds;
  const counties = record.county_geoids ?? record.countyGeoids;
  if (!Array.isArray(areas) || !Array.isArray(counties)) return null;
  return {
    kind: "map",
    serviceAreaIds: areas.filter((item): item is string => typeof item === "string"),
    countyGeoids: counties.filter((item): item is string => typeof item === "string"),
    dropped: typeof record.dropped === "number" ? record.dropped : 0,
  };
}

function chartDisplay(record: Record<string, unknown>): Extract<DisplayPayload, { kind: "chart" }> | null {
  if (!Array.isArray(record.columns) || !Array.isArray(record.rows)) return null;
  const numeric = record.numeric_columns ?? record.numericColumns;
  return {
    kind: "chart",
    columns: record.columns.filter((item): item is string => typeof item === "string"),
    rows: record.rows.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object"),
    rowCount: typeof record.row_count === "number" ? record.row_count : record.rows.length,
    numericColumns: Array.isArray(numeric) ? numeric.filter((item): item is string => typeof item === "string") : [],
  };
}

function queriesFromCall(name: string, args: unknown): string[] {
  if (name !== "run_sparql") return [];
  const record = argumentRecord(args);
  const query = record && typeof record.query === "string" ? record.query.trim() : "";
  return query ? [query] : [];
}

function argumentRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value);
      return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }
  if (value && typeof value === "object") return value as Record<string, unknown>;
  return null;
}

function summarizeToolResult(result: unknown): string {
  if (!result || typeof result !== "object") return "done";
  const record = result as Record<string, unknown>;
  if (typeof record.error === "string") return record.error;
  if (typeof record.row_count === "number") return `${record.row_count} rows`;
  if (typeof record.boolean === "boolean") return record.boolean ? "yes" : "no";
  if (typeof record.nodes === "number") return `${record.nodes} nodes`;
  return "done";
}

function stringField(record: Record<string, unknown>, name: string): string {
  const value = record[name];
  return typeof value === "string" ? value : "";
}

function stringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value.filter((item): item is string => typeof item === "string");
  return items.length > 0 ? items : undefined;
}

function unique(values: readonly string[]): string[] {
  const output: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (!value || seen.has(value)) continue;
    seen.add(value);
    output.push(value);
  }
  return output;
}
