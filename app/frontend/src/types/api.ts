import type { Feature, FeatureCollection, GeoJsonProperties, Geometry } from "geojson";

export interface SparqlCell {
  kind: "iri" | "literal" | "bnode";
  value: string;
  datatype?: string;
  language?: string;
}

export type SparqlRow = Record<string, SparqlCell>;

export interface StatsResponse {
  release: string;
  base_iri: string;
  llm_configured?: boolean;
  classes: { name: string; label: string; count: number }[];
  links: { name: string; label: string; count: number }[];
}

export interface SearchRow {
  iri: string | null;
  id: string | null;
  kind: string | null;
  label: string | null;
  state: string | null;
  sector: string | null;
  status: string | null;
  match: string | null;
}

export interface SearchResponse {
  rows: SearchRow[];
  row_count: number;
}

export interface EntityResponse {
  iri: string;
  rows: SparqlRow[];
  row_count: number;
}

export interface ServiceAreaCollection extends FeatureCollection<Geometry, GeoJsonProperties> {
  truncated: boolean;
}

export type MapFeature = Feature<Geometry, GeoJsonProperties>;

export interface WhoServesSystem {
  iri: string | null;
  service_area_iri: string | null;
  service_area_id: string | null;
  system_id: string | null;
  name: string | null;
  sector: string | null;
  status: string | null;
  primary_state: string | null;
  authority: string | null;
  source_vintage_date: string | null;
  boundary_representation: string | null;
  zone_role: string | null;
  licence: string | null;
  grain: string | null;
}

export interface WhoServesResponse {
  count: number;
  systems: WhoServesSystem[];
}

export interface ScorecardRow {
  state: string | null;
  sector: string;
  population: number | null;
  population_in_nonmodeled_boundary: number | null;
  share_population_nonmodeled: number | null;
  median_boundary_age_days: number | null;
  boundaries_with_vintage: number | null;
  boundaries_missing_vintage: number | null;
  active_systems: number | null;
  systems_with_no_boundary: number | null;
  as_of_date: string | null;
}

export interface ScorecardResponse {
  rows: ScorecardRow[];
  row_count: number;
}

export type SparqlResponse =
  | { kind: "ask"; boolean: boolean }
  | { kind: "select"; row_count: number; rows: SparqlRow[] };

export interface ProjectedNode {
  iri: string;
  label: string;
  kind: string;
  state: string;
}

export interface ProjectedLink {
  source: string;
  predicate: string;
  target: string;
}

export type DisplayPayload =
  | { kind: "graph"; nodes: ProjectedNode[]; links: ProjectedLink[]; dropped: number }
  | { kind: "map"; serviceAreaIds: string[]; countyGeoids: string[]; dropped: number }
  | {
      kind: "chart";
      columns: string[];
      rows: Record<string, unknown>[];
      rowCount: number;
      numericColumns: string[];
    };

export type AskEvent =
  | { event: "status"; message: string }
  | { event: "answer_delta"; text: string }
  | { event: "tool_call"; callId: string; name: string; arguments: unknown }
  | { event: "tool_result"; callId: string; name: string; result: unknown }
  | { event: "display"; display: DisplayPayload }
  | { event: "done"; answer: string }
  | { event: "error"; message: string; missing?: string[] };
