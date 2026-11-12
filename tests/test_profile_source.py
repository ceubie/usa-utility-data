import gzip
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
import shapely

from scripts.profile_source import profile_path


def test_profile_keeps_null_empty_and_space_distinct(tmp_path: Path):
    folder = tmp_path / "texas_water"
    folder.mkdir()
    features = [
        {"attributes": {"Source": "System", "Name": "A"}, "geometry": {"rings": [[[0, 0], [1, 0], [0, 0]]]}},
        {"attributes": {"Source": " ", "Name": None}, "geometry": {"rings": []}},
        {"attributes": {"Source": "", "Name": "B"}, "geometry": None},
    ]
    with gzip.open(folder / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": features}, stream)
    report = profile_path(folder)
    layer = report["layers"][0]
    assert layer["rows"] == 3
    assert layer["geometry"] == {"null": 1, "empty": 1, "nonempty": 1, "unrecognized": 0}
    fields = {field["name"]: field for field in layer["fields"]}
    assert fields["Source"]["null"] == 0
    assert fields["Source"]["empty"] == 1
    assert fields["Source"]["whitespace"] == 1
    assert fields["Source"]["distinct"] == 3
    assert {item["repr"]: item["count"] for item in fields["Source"]["top"]} == {"'System'": 1, "' '": 1, "''": 1}
    assert fields["Name"]["null"] == 1
    assert fields["Name"]["distinct"] == 2


def test_profile_reads_csv_geopackage_geojson_and_zipped_shapefile(tmp_path: Path):
    table = tmp_path / "plants.csv"
    table.write_text("ID,NAME\n1,Kept\n2,\n", encoding="utf-8")
    csv_report = profile_path(table)
    csv_fields = {field["name"]: field for field in csv_report["layers"][0]["fields"]}
    assert csv_report["layers"][0]["kind"] == "csv"
    assert csv_report["layers"][0]["geometry"] is None
    assert csv_fields["NAME"]["empty"] == 1
    assert csv_fields["NAME"]["null"] == 0

    frame = gpd.GeoDataFrame(
        {"ID": ["1"], "NAME": ["Kept"]},
        geometry=[shapely.box(-100, 38, -99, 39)],
        crs="EPSG:4326",
    )
    gpkg = tmp_path / "areas.gpkg"
    frame.to_file(gpkg, layer="areas", driver="GPKG")
    geojson = tmp_path / "areas.geojson"
    frame.to_file(geojson, driver="GeoJSON")
    shapefile_dir = tmp_path / "shp"
    shapefile_dir.mkdir()
    frame.to_file(shapefile_dir / "areas.shp")
    archive = tmp_path / "areas.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in shapefile_dir.glob("areas.*"):
            bundle.write(path, path.name)
    for path, kind in ((gpkg, "geopackage"), (geojson, "geojson"), (archive, "shapefile")):
        layer = profile_path(path)["layers"][0]
        assert layer["kind"] == kind
        assert layer["rows"] == 1
        assert layer["geometry"]["nonempty"] == 1

    ragged = tmp_path / "ragged.csv"
    ragged.write_text("ID,NAME\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed CSV row"):
        profile_path(ragged)
