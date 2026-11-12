import type { SparqlRow } from "../types/api";
import { type NodeKind, isNodeKind } from "../types/graph";
import { localName } from "../viz/graphData";

export interface Provenance {
  source: string | null;
  date: string | null;
  authority: string | null;
  matchMethod: string | null;
  confidence: string | null;
}

export interface Selection {
  iri: string | null;
  label: string;
  kind: NodeKind | null;
  attributes: { name: string; value: string }[];
  provenance: Provenance;
}

export interface PlacedFacility {
  iri: string;
  label: string;
  latitude: number;
  longitude: number;
}

export interface EntityReading {
  selection: Selection;
  facility: PlacedFacility | null;
  representation: { id: string; value: string } | null;
}

const RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type";

export function emptyProvenance(): Provenance {
  return { source: null, date: null, authority: null, matchMethod: null, confidence: null };
}

export function provenanceText(value: string | null): string {
  return value && value.trim() ? value : "not in the data";
}

export function selectionFromSearch(input: {
  iri: string | null;
  label: string | null;
  kind: NodeKind | null;
  match: string | null;
  state: string | null;
  sector: string | null;
  status: string | null;
}): Selection {
  const attributes = [
    input.state ? { name: "state", value: input.state } : null,
    input.sector ? { name: "sector", value: input.sector } : null,
    input.status ? { name: "status", value: input.status } : null,
  ].filter((item): item is { name: string; value: string } => item !== null);
  return {
    iri: input.iri,
    label: input.label || input.iri || "Untitled",
    kind: input.kind,
    attributes,
    provenance: { ...emptyProvenance(), matchMethod: input.match },
  };
}

export function selectionFromEntity(iri: string, rows: readonly SparqlRow[], prior: Provenance | null): EntityReading {
  const values = new Map<string, string[]>();
  const kinds: NodeKind[] = [];
  for (const row of rows) {
    const predicate = row.predicate?.value;
    const cell = row.value;
    if (!predicate || !cell?.value) continue;
    if (predicate === RDF_TYPE && cell.kind === "iri") {
      const local = localName(cell.value);
      if (isNodeKind(local)) kinds.push(local);
      continue;
    }
    const name = localName(predicate);
    const text = cell.kind === "iri" ? localName(cell.value) : cell.value;
    const list = values.get(name) ?? [];
    if (!list.includes(text)) list.push(text);
    values.set(name, list);
  }
  const attributes = [...values.entries()].map(([name, list]) => ({ name, value: list.join("; ") }));
  const kind = specificKind(kinds);
  const label = first(values, "name") ?? first(values, "namelsad") ?? localName(iri);
  const evidence = first(values, "evidence");
  const provenance: Provenance = {
    source: first(values, "source_id") ?? first(values, "assertedBy") ?? prior?.source ?? null,
    date: first(values, "source_vintage_date") ?? first(values, "as_of") ?? prior?.date ?? null,
    authority: first(values, "authority") ?? prior?.authority ?? null,
    matchMethod: joinMatch(prior?.matchMethod ?? null, evidence),
    confidence: first(values, "confidence") ?? prior?.confidence ?? null,
  };
  const latitude = asCoord(first(values, "latitude"));
  const longitude = asCoord(first(values, "longitude"));
  const facility = kind === "Facility" && latitude !== null && longitude !== null
    ? { iri, label, latitude, longitude }
    : null;
  const areaId = first(values, "service_area_id");
  const representation = first(values, "boundary_representation");
  return {
    selection: { iri, label, kind, attributes, provenance },
    facility,
    representation: areaId && representation ? { id: areaId, value: representation } : null,
  };
}

export function selectionFromProperties(
  iri: string | null,
  label: string,
  kind: NodeKind | null,
  properties: Record<string, unknown>,
  matchMethod: string | null,
): Selection {
  const attributes = Object.entries(properties)
    .filter((entry): entry is [string, string | number | boolean] => {
      const value = entry[1];
      return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
    })
    .map(([name, value]) => ({ name, value: String(value) }));
  const authority = typeof properties.authority === "string" ? properties.authority : null;
  const date = typeof properties.source_vintage_date === "string" ? properties.source_vintage_date : null;
  const source = typeof properties.source_id === "string" ? properties.source_id : null;
  return {
    iri,
    label,
    kind,
    attributes,
    provenance: { source, date, authority, matchMethod, confidence: null },
  };
}

function specificKind(kinds: readonly NodeKind[]): NodeKind | null {
  return kinds.find((kind) => kind !== "UtilitySystem") ?? kinds[0] ?? null;
}

function first(values: ReadonlyMap<string, string[]>, name: string): string | null {
  return values.get(name)?.[0] ?? null;
}

function joinMatch(match: string | null, evidence: string | null): string | null {
  if (match && evidence && match !== evidence) return `${match}; evidence ${evidence}`;
  return evidence ?? match;
}

function asCoord(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
