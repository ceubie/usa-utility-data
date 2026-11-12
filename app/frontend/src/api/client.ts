import type { Feature, GeoJsonProperties, Geometry } from "geojson";
import { POLYGON_CAP } from "../limits";
import type {
  EntityResponse,
  ScorecardResponse,
  ScorecardRow,
  SearchResponse,
  SearchRow,
  ServiceAreaCollection,
  SparqlResponse,
  SparqlRow,
  StatsResponse,
  WhoServesResponse,
  WhoServesSystem,
} from "../types/api";
import { capFeatures } from "../viz/mapData";
import { ApiError, asBoolean, asNumber, asRecord, asString, requestJson, type RequestOptions } from "./http";

export interface ServiceAreaQuery {
  ids?: readonly string[];
  bbox?: [number, number, number, number] | null;
  sector?: string | null;
  simplifyDegrees?: 0.001 | 0.01;
  limit?: number;
}

export async function getStats(options?: RequestOptions): Promise<StatsResponse> {
  return requestJson("/api/stats", options, parseStats);
}

export async function searchEntities(
  query: string,
  filters?: { kind?: string | null; state?: string | null; limit?: number },
  options?: RequestOptions,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (filters?.kind) params.set("kind", filters.kind);
  if (filters?.state) params.set("state", filters.state);
  if (filters?.limit) params.set("limit", String(filters.limit));
  return requestJson(`/api/search?${params.toString()}`, options, parseSearch);
}

export async function getEntity(iri: string, options?: RequestOptions): Promise<EntityResponse> {
  const params = new URLSearchParams({ iri });
  return requestJson(`/api/entity?${params.toString()}`, options, (value) => parseRows(value, "entity"));
}

export async function expandGraph(iri: string, limit = 50, options?: RequestOptions): Promise<EntityResponse> {
  const params = new URLSearchParams({ iri, limit: String(limit) });
  return requestJson(`/api/graph/expand?${params.toString()}`, options, (value) => parseRows(value, "expand"));
}

export async function getServiceAreas(query: ServiceAreaQuery, options?: RequestOptions): Promise<ServiceAreaCollection> {
  const ids = (query.ids ?? []).map((id) => id.trim()).filter(Boolean).slice(0, POLYGON_CAP);
  const bbox = query.bbox ?? null;
  if (ids.length === 0 && !bbox) throw new ApiError(0, "Service areas need an id or a bbox.");
  const params = new URLSearchParams();
  for (const id of ids) params.append("service_area_id", id);
  if (bbox) params.set("bbox", bbox.join(","));
  if (query.sector) params.set("sector", query.sector);
  params.set("simplify_degrees", String(query.simplifyDegrees ?? 0.01));
  params.set("limit", String(Math.max(1, Math.min(query.limit ?? POLYGON_CAP, POLYGON_CAP))));
  return requestJson(`/api/geo/service-areas?${params.toString()}`, options, parseServiceAreas);
}

export async function whoServes(
  lat: number,
  lon: number,
  sector: string,
  options?: RequestOptions,
): Promise<WhoServesResponse> {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    sector,
  });
  return requestJson(`/api/geo/who-serves?${params.toString()}`, options, parseWhoServes);
}

export async function getScorecard(
  filters?: { state?: string | null; sector?: string | null },
  options?: RequestOptions,
): Promise<ScorecardResponse> {
  const params = new URLSearchParams();
  if (filters?.state) params.set("state", filters.state);
  if (filters?.sector) params.set("sector", filters.sector);
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return requestJson(`/api/coverage/scorecard${query}`, options, parseScorecard);
}

export async function querySparql(query: string, options?: RequestOptions): Promise<SparqlResponse> {
  return requestJson("/api/sparql/query", options, parseSparql, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
}

function parseStats(value: unknown): StatsResponse {
  const record = asRecord(value);
  return {
    release: asString(record.release) ?? "",
    base_iri: asString(record.base_iri) ?? "",
    classes: arrayOf(record.classes).map((item) => {
      const row = asRecord(item);
      return {
        name: asString(row.name) ?? "",
        label: asString(row.label) ?? "",
        count: asNumber(row.count) ?? 0,
      };
    }),
    links: arrayOf(record.links).map((item) => {
      const row = asRecord(item);
      return {
        name: asString(row.name) ?? "",
        label: asString(row.label) ?? "",
        count: asNumber(row.count) ?? 0,
      };
    }),
  };
}

function parseSearch(value: unknown): SearchResponse {
  const record = asRecord(value);
  const rows = arrayOf(record.rows).map(parseSearchRow);
  return { rows, row_count: asNumber(record.row_count) ?? rows.length };
}

function parseSearchRow(value: unknown): SearchRow {
  const row = asRecord(value);
  return {
    iri: asString(row.iri),
    id: asString(row.id),
    kind: asString(row.kind),
    label: asString(row.label),
    state: asString(row.state),
    sector: asString(row.sector),
    status: asString(row.status),
    match: asString(row.match),
  };
}

function parseRows(value: unknown, label: string): EntityResponse {
  const record = asRecord(value);
  const iri = asString(record.iri);
  if (!iri) throw new ApiError(0, `The ${label} response did not include an IRI.`);
  const rows = arrayOf(record.rows).map(parseSparqlRow);
  return { iri, rows, row_count: asNumber(record.row_count) ?? rows.length };
}

function parseServiceAreas(value: unknown): ServiceAreaCollection {
  const record = asRecord(value);
  if (record.type !== "FeatureCollection" || !Array.isArray(record.features)) {
    throw new ApiError(0, "Service areas were not a FeatureCollection.");
  }
  const features = record.features.filter(isFeature);
  const capped = capFeatures(features);
  return {
    type: "FeatureCollection",
    features: capped.features,
    truncated: record.truncated === true || capped.truncated,
  };
}

function parseWhoServes(value: unknown): WhoServesResponse {
  const record = asRecord(value);
  const systems = arrayOf(record.systems).map(parseWhoServesSystem);
  return { count: asNumber(record.count) ?? systems.length, systems };
}

function parseWhoServesSystem(value: unknown): WhoServesSystem {
  const row = asRecord(value);
  return {
    iri: asString(row.iri),
    service_area_iri: asString(row.service_area_iri),
    service_area_id: asString(row.service_area_id),
    system_id: asString(row.system_id),
    name: asString(row.name),
    sector: asString(row.sector),
    status: asString(row.status),
    primary_state: asString(row.primary_state),
    authority: asString(row.authority),
    source_vintage_date: dateString(row.source_vintage_date),
    boundary_representation: asString(row.boundary_representation),
    zone_role: asString(row.zone_role),
    licence: asString(row.licence),
    grain: asString(row.grain),
  };
}

function parseScorecard(value: unknown): ScorecardResponse {
  const record = asRecord(value);
  const rows = arrayOf(record.rows).map(parseScorecardRow);
  return { rows, row_count: asNumber(record.row_count) ?? rows.length };
}

function parseScorecardRow(value: unknown): ScorecardRow {
  const row = asRecord(value);
  return {
    state: asString(row.state),
    sector: asString(row.sector) ?? "",
    population: asNumber(row.population),
    population_in_nonmodeled_boundary: asNumber(row.population_in_nonmodeled_boundary),
    share_population_nonmodeled: asNumber(row.share_population_nonmodeled),
    median_boundary_age_days: asNumber(row.median_boundary_age_days),
    boundaries_with_vintage: asNumber(row.boundaries_with_vintage),
    boundaries_missing_vintage: asNumber(row.boundaries_missing_vintage),
    active_systems: asNumber(row.active_systems),
    systems_with_no_boundary: asNumber(row.systems_with_no_boundary),
    as_of_date: dateString(row.as_of_date),
  };
}

function parseSparql(value: unknown): SparqlResponse {
  const record = asRecord(value);
  if (record.kind === "ask") {
    const answer = asBoolean(record.boolean);
    if (answer === null) throw new ApiError(0, "SPARQL ASK did not return a boolean.");
    return { kind: "ask", boolean: answer };
  }
  if (record.kind === "select") {
    const rows = arrayOf(record.rows).map(parseSparqlRow);
    return { kind: "select", row_count: asNumber(record.row_count) ?? rows.length, rows };
  }
  throw new ApiError(0, "SPARQL response kind was not select or ask.");
}

function parseSparqlRow(value: unknown): SparqlRow {
  const record = asRecord(value);
  const row: SparqlRow = {};
  for (const [name, cell] of Object.entries(record)) {
    const item = asRecord(cell);
    const kind = item.kind;
    const text = asString(item.value);
    if ((kind !== "iri" && kind !== "literal" && kind !== "bnode") || text === null) continue;
    const parsed: SparqlRow[string] = { kind, value: text };
    const datatype = asString(item.datatype);
    const language = asString(item.language);
    if (datatype) parsed.datatype = datatype;
    if (language) parsed.language = language;
    row[name] = parsed;
  }
  return row;
}

function isFeature(value: unknown): value is Feature<Geometry, GeoJsonProperties> {
  const record = asRecord(value);
  return record.type === "Feature" && typeof record.geometry === "object" && record.geometry !== null;
}

function arrayOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function dateString(value: unknown): string | null {
  if (typeof value === "string") return value;
  return null;
}
