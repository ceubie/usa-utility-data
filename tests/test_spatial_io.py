"""Esri geometry reading: no CRS is guessed, and nested rings become holes after make_valid."""

import re
from pathlib import Path

import pytest
import shapely

from utilitydata.core.spatial_io import get_esri_crs, parse_esri_geometry

SOURCE = Path(__file__).resolve().parents[1] / "src" / "utilitydata"


def test_a_spatial_layer_without_a_spatial_reference_is_refused():
    with pytest.raises(ValueError, match="no resolvable spatial reference"):
        get_esri_crs({"name": "zones", "geometryType": "esriGeometryPolygon"})
    assert get_esri_crs({"type": "Table"}) is None
    assert get_esri_crs({"extent": {"spatialReference": {"wkid": 102100}}}).to_epsg() == 3857
    assert get_esri_crs({"spatialReference": {"latestWkid": 2277}, "geometryType": "esriGeometryPolygon"}).to_epsg() == 2277


def test_a_ring_inside_a_shell_becomes_a_hole():
    shell = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
    hole = [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]
    parsed = parse_esri_geometry({"rings": [shell, hole]}, "esriGeometryPolygon")
    assert shapely.make_valid(parsed).area == pytest.approx(64.0)
    assert parse_esri_geometry({"rings": [[[0, 0], [1, 1]]]}, "esriGeometryPolygon") is None
    assert parse_esri_geometry({"x": float("nan"), "y": 1.0}, "esriGeometryPoint") is None


def test_the_package_does_not_import_the_legacy_pipeline():
    legacy = re.compile(r"^\s*(from|import)\s+pipeline\b", re.MULTILINE)
    offenders = [path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*.py") if legacy.search(path.read_text(encoding="utf-8"))]
    assert offenders == []
