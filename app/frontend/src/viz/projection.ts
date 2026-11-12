import * as d3 from "d3";
import type { Feature } from "geojson";

/** geoAlbersUsa draws the states, Alaska, Hawaii, and Puerto Rico. Other island areas return null. */
export function nationalProjection(width: number, height: number): d3.GeoProjection {
  const scale = Math.min(width / 960, height / 600) * 1070;
  return d3.geoAlbersUsa().translate([width / 2, height / 2]).scale(scale);
}

export function stateProjection(item: Feature, width: number, height: number): d3.GeoProjection {
  return d3.geoAlbers().fitExtent(
    [[24, 24], [Math.max(width - 24, 48), Math.max(height - 24, 48)]],
    item,
  );
}

export function projectsInNationalView(item: Feature, projection: d3.GeoProjection): boolean {
  const outline = d3.geoPath(projection)(item);
  return typeof outline === "string" && outline.length > 0;
}
