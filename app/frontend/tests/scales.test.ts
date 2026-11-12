import { describe, expect, it } from "vitest";
import type { Feature } from "geojson";
import { whoServes } from "../src/api/client";
import { CANVAS_PATH_CAP, POLYGON_CAP } from "../src/limits";
import { EDGE_KINDS, NODE_KINDS } from "../src/types/graph";
import { capFeatures, isModeledBoundary, planAreaRequest, useCanvas } from "../src/viz/mapData";
import { nationalProjection, projectsInNationalView, stateProjection } from "../src/viz/projection";
import {
  MISSING_COLOR,
  ZERO_SHARE_COLOR,
  authorityColor,
  barLength,
  colorForEdge,
  colorForKind,
  coverageColor,
  formatShare,
  providerColor,
  providersFor,
  sectorNonmodeledShare,
} from "../src/viz/scales";
import type { ScorecardRow } from "../src/types/api";

describe("color and scale", () => {
  it("assigns a color to every ontology class and edge", () => {
    const colors = NODE_KINDS.map((kind) => colorForKind(kind));
    expect(new Set(colors).size).toBeGreaterThan(8);
    expect(colors.every((color) => /^#[0-9a-f]{6}$/.test(color))).toBe(true);
    expect(colorForKind("WaterSystem")).not.toBe(colorForKind("ElectricSystem"));
    expect(EDGE_KINDS.map((kind) => colorForEdge(kind)).every((color) => color.startsWith("#"))).toBe(true);
    expect(authorityColor("utility_direct")).not.toBe(authorityColor("admin_proxy"));
  });

  it("keeps a zero non-modeled share at the zero color and a missing share apart from it", () => {
    expect(coverageColor(0)).toBe(ZERO_SHARE_COLOR);
    expect(coverageColor(null)).toBe(MISSING_COLOR);
    expect(formatShare(0)).toBe("0");
    expect(coverageColor(0.25)).not.toBe(ZERO_SHARE_COLOR);
    const rows: ScorecardRow[] = [
      score("TX", 100, 0, 0),
      score("AK", 50, 0, 0),
      score("AB", null, null, null),
    ];
    expect(sectorNonmodeledShare(rows, "water")).toBe(0);
    expect(sectorNonmodeledShare([score("TX", 100, 25, 0.25)], "water")).toBe(0.25);
  });

  it("does not treat a missing provider count as zero when the query was cut off", () => {
    expect(providersFor("11001", [], true)).toBe(0);
    expect(providersFor("11001", [], false)).toBeNull();
    expect(providerColor(0)).not.toBe(providerColor(null));
    expect(barLength(5, 10, 100)).toBe(50);
    expect(barLength(0, 0, 100)).toBe(0);
  });

  it("draws territories in the state projection and omits them from the national projection", () => {
    const national = nationalProjection(960, 600);
    const dc = point(-77.0369, 38.9072);
    const guam = point(144.79, 13.44);
    expect(projectsInNationalView(dc, national)).toBe(true);
    expect(projectsInNationalView(guam, national)).toBe(false);
    const island = polygon(144.79, 13.44);
    const fitted = stateProjection(island, 640, 480);
    const projected = fitted([144.79, 13.44]);
    expect(projected).not.toBeNull();
    if (projected) {
      expect(projected[0]).toBeGreaterThan(20);
      expect(projected[0]).toBeLessThan(620);
      expect(projected[1]).toBeGreaterThan(20);
      expect(projected[1]).toBeLessThan(460);
    }
  });

  it("caps polygons at 300 and uses canvas above 1500 paths", () => {
    const features = Array.from({ length: POLYGON_CAP + 1 }, (_, index) => index);
    const capped = capFeatures(features);
    expect(capped.features).toHaveLength(POLYGON_CAP);
    expect(capped.truncated).toBe(true);
    expect(useCanvas(CANVAS_PATH_CAP, CANVAS_PATH_CAP)).toBe(false);
    expect(useCanvas(CANVAS_PATH_CAP + 1, CANVAS_PATH_CAP)).toBe(true);
    const plan = planAreaRequest({
      explicitIds: features.map(String),
      bbox: [-77.2, 38.8, -76.9, 39.0],
      sector: "water",
    });
    expect(plan.mode).toBe("ids");
    expect(plan.ids).toHaveLength(POLYGON_CAP);
    expect(plan.bbox).toBeNull();
    expect(plan.omitted).toBe(1);
    expect(isModeledBoundary({ boundary_representation: "modeled" })).toBe(true);
    expect(isModeledBoundary({ boundary_representation: "mixed" })).toBe(false);
    expect(isModeledBoundary({ boundary_representation: "unknown" })).toBe(false);
    expect(isModeledBoundary(null)).toBe(false);
  });
});

describe("who-serves client", () => {
  it("calls the same point the map click uses", async () => {
    const seen: string[] = [];
    const systems = [{ system_id: "SYS_PWS_DC0000002", name: "DC Water", sector: "water" }];
    await whoServes(38.9072, -77.0369, "water", {
      baseUrl: "http://127.0.0.1:8000",
      fetchImpl: (input) => {
        seen.push(String(input));
        return Promise.resolve(new Response(JSON.stringify({ count: 1, systems }), { status: 200 }));
      },
    });
    expect(seen).toEqual([
      "http://127.0.0.1:8000/api/geo/who-serves?lat=38.9072&lon=-77.0369&sector=water",
    ]);
  });
});

function point(lon: number, lat: number): Feature {
  return { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon, lat] } };
}

function polygon(lon: number, lat: number): Feature {
  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [[
        [lon - 0.3, lat - 0.2],
        [lon + 0.3, lat - 0.2],
        [lon + 0.3, lat + 0.2],
        [lon - 0.3, lat + 0.2],
        [lon - 0.3, lat - 0.2],
      ]],
    },
  };
}

function score(
  state: string,
  population: number | null,
  inside: number | null,
  share: number | null,
): ScorecardRow {
  return {
    state,
    sector: "water",
    population,
    population_in_nonmodeled_boundary: inside,
    share_population_nonmodeled: share,
    median_boundary_age_days: null,
    boundaries_with_vintage: null,
    boundaries_missing_vintage: null,
    active_systems: null,
    systems_with_no_boundary: null,
    as_of_date: "2026-09-30",
  };
}
