"""Simplified service-area geometry for the application map."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.errors import GEOSException

from utilitydata.core.config import DISPLAY_SIMPLIFY_DEGREES
from utilitydata.core.text import require_columns
from utilitydata.gold.schema import DISPLAY_COLUMNS


def write_display(territories: Path, destination: Path) -> dict[str, int]:
    """Write each best serving area at every configured degree tolerance."""
    frame = gpd.read_parquet(territories)
    display, retained = _build_display_frame(frame)
    destination.parent.mkdir(parents=True, exist_ok=True)
    display.to_parquet(destination, index=False)
    return {"rows": len(display), "retained_original": retained}


def rebuild_display(territories: list[Path], destination: Path) -> dict[str, int]:
    """Replace the display file from the current territory tables.

    A second call with the same tables writes the same rows. Sectors that are
    not in the territory list are not kept from an older display file.
    """
    frames = [gpd.read_parquet(path) for path in territories if path.is_file()]
    if not frames:
        raise ValueError("Display rebuild found no territory files")
    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    display, retained = _build_display_frame(combined)
    destination.parent.mkdir(parents=True, exist_ok=True)
    display.to_parquet(destination, index=False)
    return {"rows": len(display), "retained_original": retained, "territory_files": len(frames)}


def append_sector_display(sector_areas: gpd.GeoDataFrame, destination: Path) -> dict[str, int]:
    """Simplify sector best serving areas and merge them into service_area_display.parquet."""
    new_display, retained = _build_display_frame(sector_areas)
    sectors = set(new_display["sector"].dropna().astype(str))
    if destination.is_file():
        existing = gpd.read_parquet(destination)
        kept = existing.loc[~existing["sector"].astype(str).isin(sectors)].copy()
        combined = pd.concat([kept, new_display], ignore_index=True)
        display = gpd.GeoDataFrame(combined.loc[:, list(DISPLAY_COLUMNS)], geometry="geometry", crs="EPSG:4326")
    else:
        display = new_display
    if bool(display.duplicated(["service_area_id", "simplify_degrees"]).any()):
        raise ValueError("Display geometry tolerances are not unique")
    destination.parent.mkdir(parents=True, exist_ok=True)
    display.to_parquet(destination, index=False)
    return {"rows": len(display), "sector_rows": len(new_display), "retained_original": retained}


def _build_display_frame(frame: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, int]:
    require_columns(frame, ("service_area_id", "system_id", "sector", "zone_role", "authority", "licence", "geometry"), "territories")
    parts: list[gpd.GeoDataFrame] = []
    retained = 0
    for tolerance in DISPLAY_SIMPLIFY_DEGREES:
        geometries, flags = _simplify_all(frame.geometry, float(tolerance))
        retained += sum(flags)
        part = frame.loc[:, ["service_area_id", "system_id", "sector", "zone_role", "authority", "licence"]].copy()
        part["simplify_degrees"] = float(tolerance)
        part["simplify_retained_original"] = flags
        part["geometry"] = geometries
        parts.append(gpd.GeoDataFrame(part, geometry="geometry", crs="EPSG:4326"))
    display = pd.concat(parts, ignore_index=True)
    display = gpd.GeoDataFrame(display.loc[:, list(DISPLAY_COLUMNS)], geometry="geometry", crs="EPSG:4326")
    if bool(display.duplicated(["service_area_id", "simplify_degrees"]).any()):
        raise ValueError("Display geometry tolerances are not unique")
    return display, retained


def _simplify_all(geometries: gpd.GeoSeries, tolerance: float) -> tuple[list[shapely.Geometry], list[bool]]:
    simplified: list[shapely.Geometry] = []
    retained: list[bool] = []
    for geometry in geometries:
        output, kept = _simplify_one(geometry, tolerance)
        simplified.append(output)
        retained.append(kept)
    return simplified, retained


def _simplify_one(geometry: shapely.Geometry, tolerance: float) -> tuple[shapely.Geometry, bool]:
    try:
        output = geometry.simplify(tolerance, preserve_topology=True)
    except (GEOSException, ValueError):
        return geometry, True
    if output is None or output.is_empty:
        return geometry, True
    return output, False
