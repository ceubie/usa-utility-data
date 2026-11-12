"""Normalize source geometries once, for every Silver input.

The same sequence is applied to every layer: reproject to EPSG:4326, make
geometries valid, drop empties, snap coordinates to 0.000001 degrees, hash the
WKB, and measure polygonal area with a WGS84 geodesic.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS, Geod

from utilitydata.core.spatial_io import (
    get_esri_crs,
    parse_esri_geometry,
    read_ogr_table,
    reproject_geoms,
)

DESTINATION = CRS.from_epsg(4326)
PRECISION = 1e-6
_GEOD = Geod(ellps="WGS84")
_EMPTY = shapely.from_wkt("GEOMETRYCOLLECTION EMPTY")
_POLYGON_TYPES = frozenset({"Polygon", "MultiPolygon"})


def prepare_geometries(geometries: np.ndarray, source_crs: CRS) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return aligned geometries, WKB hashes, square-kilometre areas, and a keep mask.

    Null and empty inputs are marked dropped. Kept geometries are valid,
    two-dimensional, and on the 0.000001-degree grid. The hash is the SHA-256 of
    the WKB that is returned.
    """
    incoming = np.asarray(geometries, dtype=object)
    filled = np.empty(len(incoming), dtype=object)
    for index, geometry in enumerate(incoming):
        filled[index] = _EMPTY if geometry is None else geometry
    reprojected = reproject_geoms(filled, source_crs, DESTINATION)
    valid = shapely.make_valid(reprojected)
    snapped = shapely.set_precision(valid, grid_size=PRECISION)
    invalid = ~shapely.is_valid(snapped)
    if bool(np.any(invalid)):
        snapped = np.array(snapped, dtype=object, copy=True)
        snapped[invalid] = shapely.make_valid(snapped[invalid])
    keep = np.asarray(~shapely.is_empty(snapped), dtype=bool)
    output = np.array(snapped, dtype=object, copy=True)
    hashes = np.empty(len(output), dtype=object)
    areas = np.empty(len(output), dtype=object)
    for index, geometry in enumerate(output):
        if not keep[index]:
            output[index] = None
            hashes[index] = None
            areas[index] = None
            continue
        hashes[index] = hashlib.sha256(shapely.to_wkb(geometry)).hexdigest()
        areas[index] = _area_km2(geometry)
    return output, hashes, areas, keep


def containing_state_codes(geometries: np.ndarray, state_geometries: np.ndarray, state_codes: np.ndarray) -> np.ndarray:
    """Return the code of the single state whose polygon covers each representative point.

    A point covered by no state, or by more than one, is unresolved and comes
    back as None. The function does not choose a nearest state.
    """
    points = shapely.point_on_surface(np.asarray(geometries, dtype=object))
    result = np.empty(len(points), dtype=object)
    if len(points) == 0:
        return result
    tree = shapely.STRtree(np.asarray(state_geometries, dtype=object))
    hits = tree.query(points, predicate="covered_by")
    grouped: dict[int, list[str]] = {}
    if len(hits):
        for point_index, state_index in zip(hits[0], hits[1], strict=True):
            grouped.setdefault(int(point_index), []).append(str(state_codes[int(state_index)]))
    for index in range(len(points)):
        codes = grouped.get(index, [])
        result[index] = codes[0] if len(codes) == 1 else None
    return result


def hilbert_distances(longitude: np.ndarray, latitude: np.ndarray, *, bits: int = 16) -> np.ndarray:
    """Map longitude and latitude onto one Hilbert index at the requested bit depth."""
    if bits < 1 or bits > 16:
        raise ValueError("Hilbert bit depth must be from 1 through 16")
    maximum = (1 << bits) - 1
    x_values = np.rint((np.asarray(longitude, dtype=float) + 180.0) / 360.0 * maximum)
    y_values = np.rint((np.asarray(latitude, dtype=float) + 90.0) / 180.0 * maximum)
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        raise ValueError("Hilbert sort received a coordinate that is not finite")
    x_values = np.clip(x_values, 0, maximum).astype(np.int64)
    y_values = np.clip(y_values, 0, maximum).astype(np.int64)
    return np.fromiter((_hilbert(int(x_value), int(y_value), bits) for x_value, y_value in zip(x_values, y_values, strict=True)), dtype=np.int64, count=len(x_values))


def representative_longitude_latitude(geometries: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the longitude and latitude of each geometry's representative point."""
    points = shapely.point_on_surface(np.asarray(geometries, dtype=object))
    return shapely.get_x(points), shapely.get_y(points)


def read_arcgis_features(directory: Path) -> tuple[list[dict], np.ndarray, CRS | None]:
    """Read saved ArcGIS pages with the shared Esri geometry parser."""
    metadata_path = directory / "layer_metadata.json"
    snapshot_path = directory / "snapshot.json"
    if not metadata_path.is_file() or not snapshot_path.is_file():
        raise ValueError(f"ArcGIS snapshot is incomplete: {directory.name}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    pages = snapshot.get("pages")
    if not isinstance(pages, list):
        raise TypeError(f"ArcGIS pages are missing: {directory.name}")
    geometry_type = metadata.get("geometryType")
    attributes: list[dict] = []
    geometries: list[object] = []
    for page in pages:
        name = page.get("file") if isinstance(page, dict) else None
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f"Invalid ArcGIS page name in {directory.name}")
        with gzip.open(directory / name, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise TypeError(f"ArcGIS page has no feature list: {name}")
        for feature in features:
            if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
                raise TypeError(f"ArcGIS feature is missing attributes: {name}")
            attributes.append(feature["attributes"])
            geometries.append(parse_esri_geometry(feature.get("geometry"), geometry_type))
    return attributes, np.array(geometries, dtype=object), get_esri_crs(metadata)


def read_vector_features(path: str, layer_name: str | None, *, feature_id_field: str | None) -> tuple[pd.DataFrame, np.ndarray, CRS]:
    """Read one OGR layer, including the driver FID when the registry names it."""
    info = pyogrio.read_info(path, layer=layer_name)
    fields = {str(name) for name in info["fields"]}
    fid_column = info.get("fid_column")
    need_fids = feature_id_field is not None and feature_id_field == fid_column and feature_id_field not in fields
    meta, frame, geometries = read_ogr_table(path, layer_name, return_fids=need_fids)
    if not meta.get("crs"):
        raise ValueError(f"Vector layer has no CRS: {layer_name or path}")
    return frame, geometries, CRS.from_user_input(meta["crs"])


def _area_km2(geometry: shapely.Geometry) -> float:
    if geometry.geom_type in _POLYGON_TYPES:
        area, _perimeter = _GEOD.geometry_area_perimeter(geometry)
        return abs(float(area)) / 1_000_000.0
    if geometry.geom_type == "GeometryCollection":
        return float(sum(_area_km2(part) for part in geometry.geoms))
    return 0.0


def _hilbert(x_value: int, y_value: int, bits: int) -> int:
    distance = 0
    span = 1 << (bits - 1)
    while span:
        region_x = 1 if x_value & span else 0
        region_y = 1 if y_value & span else 0
        distance += span * span * ((3 * region_x) ^ region_y)
        if region_y == 0:
            if region_x == 1:
                mask = (1 << bits) - 1
                x_value, y_value = mask - x_value, mask - y_value
            x_value, y_value = y_value, x_value
        span >>= 1
    return distance
