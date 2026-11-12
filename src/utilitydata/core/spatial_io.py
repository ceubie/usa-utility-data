"""Read Esri JSON and OGR geometries and reproject them.

Esri polygon rings are returned as one part per ring. Shells and holes are not
told apart here; every caller runs make_valid, whose even-odd rule turns a ring
nested in a shell back into a hole.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

_WEB_MERCATOR_WKIDS = frozenset({102100, 102113, 3857})


def get_esri_crs(meta: dict) -> CRS | None:
    """Resolve the CRS in ArcGIS layer metadata. A table has none; a spatial layer without one raises."""
    sr = (meta.get("extent") or {}).get("spatialReference") or meta.get("spatialReference") or {}
    wkid = sr.get("latestWkid") or sr.get("wkid")
    if wkid:
        if wkid in _WEB_MERCATOR_WKIDS:
            return CRS.from_epsg(3857)
        try:
            return CRS.from_epsg(int(wkid))
        except CRSError:
            try:
                return CRS.from_user_input(f"ESRI:{int(wkid)}")
            except CRSError:
                pass
    wkt = sr.get("wkt")
    if wkt:
        try:
            return CRS.from_wkt(wkt)
        except CRSError:
            pass
    if not meta.get("geometryType"):
        return None
    raise ValueError(f"ArcGIS layer {meta.get('name') or ''} has geometry but no resolvable spatial reference")


def parse_esri_geometry(g: dict | None, gtype: str | None) -> shapely.Geometry | None:
    """Convert an Esri JSON geometry object into a 2D Shapely geometry. Unreadable input returns None."""
    if not g:
        return None
    try:
        if gtype == "esriGeometryPolygon" or "rings" in g:
            rings = g.get("rings")
            if not rings:
                return None
            valid_rings = [np.asarray(r, dtype=np.float64)[:, :2] for r in rings if len(r) >= 3]
            if not valid_rings:
                return None
            if len(valid_rings) == 1:
                return shapely.polygons(valid_rings[0])
            return shapely.multipolygons([shapely.polygons(r) for r in valid_rings])
        if gtype == "esriGeometryPolyline" or "paths" in g:
            paths = g.get("paths")
            if not paths:
                return None
            valid_paths = [np.asarray(p, dtype=np.float64)[:, :2] for p in paths if len(p) >= 2]
            if not valid_paths:
                return None
            if len(valid_paths) == 1:
                return shapely.linestrings(valid_paths[0])
            return shapely.multilinestrings([shapely.linestrings(p) for p in valid_paths])
        if gtype == "esriGeometryPoint" or ("x" in g and "y" in g):
            x, y = g.get("x"), g.get("y")
            if x is None or y is None or not np.isfinite(x) or not np.isfinite(y):
                return None
            return shapely.points(float(x), float(y))
        if gtype == "esriGeometryMultipoint" or "points" in g:
            pts = g.get("points")
            if not pts:
                return None
            return shapely.multipoints(np.asarray(pts, dtype=np.float64)[:, :2])
    except (TypeError, ValueError, IndexError, shapely.errors.GEOSException):
        return None
    return None


def reproject_geoms(geoms: np.ndarray, src_crs: CRS, dst_crs: CRS) -> np.ndarray:
    """Transform an array of Shapely geometries between coordinate systems."""
    if src_crs.equals(dst_crs):
        return geoms
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)

    def _tx(coords: np.ndarray) -> np.ndarray:
        if len(coords) == 0:
            return coords
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack((x, y))

    return shapely.transform(geoms, _tx)


def read_ogr_table(vsi_path: str, layer: str | None = None, *, return_fids: bool = False) -> tuple[dict, pd.DataFrame, np.ndarray]:
    """Read an OGR vector source through pyogrio's Arrow reader."""
    meta, table = pyogrio.raw.read_arrow(vsi_path, layer=layer, return_fids=return_fids)
    geom_col = meta.get("geometry_name") or "wkb_geometry"
    geoms = shapely.from_wkb(table[geom_col].to_pylist())
    return meta, table.drop([geom_col]).to_pandas(), geoms
