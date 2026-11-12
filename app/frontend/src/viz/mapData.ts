import * as d3 from "d3";
import type { Feature, GeoJsonProperties, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import { feature } from "topojson-client";
import { POLYGON_CAP } from "../limits";
import type { MapFeature, WhoServesSystem } from "../types/api";
import { assertNever } from "../types/graph";

export interface AreaPlan {
  mode: "ids" | "bbox" | "none";
  ids: string[];
  bbox: [number, number, number, number] | null;
  sector: string | null;
  omitted: number;
}

export function capFeatures<T>(features: readonly T[], cap = POLYGON_CAP): { features: T[]; truncated: boolean } {
  if (features.length <= cap) return { features: [...features], truncated: false };
  return { features: features.slice(0, cap), truncated: true };
}

export function pathCount(features: readonly MapFeature[]): number {
  let count = 0;
  for (const item of features) count += geometryPaths(item.geometry);
  return count;
}

export function geometryPaths(geometry: Geometry | null): number {
  if (!geometry) return 0;
  switch (geometry.type) {
    case "Polygon":
    case "Point":
    case "MultiPoint":
    case "LineString":
    case "MultiLineString":
      return 1;
    case "MultiPolygon":
      return geometry.coordinates.length;
    case "GeometryCollection":
      return geometry.geometries.reduce((sum, item) => sum + geometryPaths(item), 0);
    default:
      return assertNever(geometry);
  }
}

export function useCanvas(paths: number, limit: number): boolean {
  return paths > limit;
}

export function isModeledBoundary(properties: GeoJsonProperties | null | undefined): boolean {
  return properties?.boundary_representation === "modeled";
}

export function planAreaRequest(input: {
  explicitIds: readonly string[];
  bbox: [number, number, number, number] | null;
  sector: string | null;
}): AreaPlan {
  const explicit: string[] = [];
  const seen = new Set<string>();
  for (const id of input.explicitIds) {
    const text = id.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    explicit.push(text);
  }
  if (explicit.length > 0) {
    return {
      mode: "ids",
      ids: explicit.slice(0, POLYGON_CAP),
      bbox: null,
      sector: input.sector,
      omitted: Math.max(0, explicit.length - POLYGON_CAP),
    };
  }
  if (input.bbox) {
    return { mode: "bbox", ids: [], bbox: input.bbox, sector: input.sector, omitted: 0 };
  }
  return { mode: "none", ids: [], bbox: null, sector: input.sector, omitted: 0 };
}

export function featureBBox(item: Feature): [number, number, number, number] | null {
  const bounds = d3.geoBounds(item);
  const minLon = bounds[0][0];
  const minLat = bounds[0][1];
  const maxLon = bounds[1][0];
  const maxLat = bounds[1][1];
  if (![minLon, minLat, maxLon, maxLat].every((value) => Number.isFinite(value))) return null;
  if (minLon > maxLon || minLat > maxLat) return null;
  if (minLon < -180 || maxLon > 180 || minLat < -90 || maxLat > 90) return null;
  return [minLon, minLat, maxLon, maxLat];
}

export function withBoundaryRepresentation(
  features: readonly MapFeature[],
  systems: readonly WhoServesSystem[],
  representations: Readonly<Record<string, string>>,
): MapFeature[] {
  const fromSystems = new Map<string, string>();
  for (const system of systems) {
    if (system.service_area_id && system.boundary_representation) {
      fromSystems.set(system.service_area_id, system.boundary_representation);
    }
  }
  return features.map((item) => {
    const id = propertyString(item, "service_area_id");
    if (!id) return item;
    const representation = fromSystems.get(id) ?? representations[id];
    if (!representation) return item;
    return {
      ...item,
      properties: { ...(item.properties ?? {}), boundary_representation: representation },
    };
  });
}

export function propertyString(item: Feature, name: string): string | null {
  const value = item.properties?.[name];
  return typeof value === "string" && value ? value : null;
}

export function featuresFromTopology(value: unknown): MapFeature[] {
  if (!value || typeof value !== "object") return [];
  const topology = value as Topology;
  const objects = topology.objects;
  if (!objects) return [];
  const key = Object.keys(objects)[0];
  if (!key) return [];
  const object = objects[key];
  if (!object || object.type !== "GeometryCollection") return [];
  const collection = feature(topology, object as GeometryCollection);
  return collection.features;
}
