"""Geometry helpers for overlap scores and dissolved service areas."""

import numpy as np
import shapely
from pyproj import Geod, Transformer
from shapely.geometry.base import BaseGeometry

_EQUAL_AREA = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
_GEOD = Geod(ellps="WGS84")
_POLYGON_TYPES = frozenset({"Polygon", "MultiPolygon"})


def _project_coords(coords: np.ndarray) -> np.ndarray:
    easting, northing = _EQUAL_AREA.transform(coords[:, 0], coords[:, 1])
    return np.column_stack((easting, northing))


def equal_area(geometry: BaseGeometry | None) -> BaseGeometry | None:
    """Project a polygonal geometry for an area ratio. Lines and points return None."""
    if geometry is None or geometry.is_empty or geometry.area <= 0:
        return None
    projected = shapely.make_valid(shapely.transform(geometry, _project_coords))
    if projected.is_empty or projected.area <= 0:
        return None
    return projected


def covered_fraction(zone: BaseGeometry | None, territory: BaseGeometry | None) -> float:
    """Return the share of the zone area covered by the territory.

    The ratio uses an equal-area projection. A zone with no area, or a
    territory that misses it, returns 0.
    """
    left = equal_area(zone)
    right = equal_area(territory)
    if left is None or right is None or left.area <= 0 or not left.intersects(right):
        return 0.0
    return float(left.intersection(right).area / left.area)


def area_ratio(left: BaseGeometry | None, right: BaseGeometry | None) -> float:
    """Intersection-over-union using the geometries as given, without projecting them."""
    if left is None or right is None or left.is_empty or right.is_empty or not left.intersects(right):
        return 0.0
    intersection = left.intersection(right).area
    union = left.area + right.area - intersection
    if union <= 0:
        return 0.0
    return float(intersection / union)


def intersection_over_union(left: BaseGeometry | None, right: BaseGeometry | None) -> float:
    """Return the equal-area intersection-over-union, or 0 when either side has no area."""
    return area_ratio(equal_area(left), equal_area(right))


def union_geometries(geometries: list[BaseGeometry]) -> BaseGeometry:
    """Union every part. A single part is returned unchanged."""
    if not geometries:
        raise ValueError("Cannot union an empty geometry list")
    if len(geometries) == 1:
        return geometries[0]
    if len(geometries) <= 4096:
        return shapely.union_all(geometries)
    middle = len(geometries) // 2
    return shapely.union(union_geometries(geometries[:middle]), union_geometries(geometries[middle:]))


def polygonal_area_km2(geometry: BaseGeometry | None) -> float:
    """Geodesic square kilometres for polygonal parts. Lines and points contribute 0."""
    return _area(geometry)


def _area(geometry: BaseGeometry | None) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    if geometry.geom_type in _POLYGON_TYPES:
        area, _perimeter = _GEOD.geometry_area_perimeter(geometry)
        return abs(float(area)) / 1_000_000.0
    if geometry.geom_type == "GeometryCollection":
        return float(sum(_area(part) for part in geometry.geoms))
    return 0.0
