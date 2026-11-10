import gzip
import hashlib
import json
import zipfile

import geopandas as gpd
import pyarrow.parquet as pq
import pytest
import yaml
from shapely.geometry import Polygon

from utilitydata.bronze import snapshot
from utilitydata.bronze.snapshot import freeze, inventory
from utilitydata.registry import Source


def _collection(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    url = "https://example.test/FeatureServer/0"
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "type": "Feature Layer", "geometryType": "esriGeometryPolygon", "fields": [{"name": "name"}]}), encoding="utf-8")
    page = layer / "page_000000.json.gz"
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "Provider"}, "geometry": None}]}, stream)
    sha = hashlib.sha256(page.read_bytes()).hexdigest()
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": url, "retrieved_utc": "2026-11-10T00:00:00Z", "expected_count_at_start": 1, "id_count": 1, "downloaded_count": 1, "pages": [{"file": page.name, "features": 1, "sha256": sha}]}), encoding="utf-8")
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": url, "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    return raw, layer, source, registry


def test_snapshot_copies_hashes_and_marks_missing_geometry(tmp_path):
    raw, _layer, _source, registry = _collection(tmp_path)
    (raw / "extra.txt").write_text("context", encoding="utf-8")
    unused = tmp_path / "unused.yaml"
    unused.write_text("unused:\n  - {path: extra.txt, reason: Context only}\n", encoding="utf-8")
    home = tmp_path / "home"
    result = freeze("2026-Q4", home=home, raw_root=raw, registry_dir=registry, unused_path=unused)
    rows = pq.read_table(result / "manifest.parquet").to_pylist()
    assert len(rows) == 4
    page = next(row for row in rows if row["relative_path"].endswith(".gz"))
    assert page["status"] == "no_geometry" and page["has_geometry"] is False
    assert page["feature_count"] == 1
    layer_rows = pq.read_table(result / "layers.parquet").to_pylist()
    assert layer_rows[0]["feature_count"] == 1 and layer_rows[0]["status"] == "no_geometry"
    assert next(row for row in rows if row["relative_path"] == "extra.txt")["status"] == "unused"
    (raw / "extra.txt").write_text("changed", encoding="utf-8")
    assert (result / "files" / "extra.txt").read_text(encoding="utf-8") == "context"
    with pytest.raises(FileExistsError):
        freeze("2026-Q4", home=home, raw_root=raw, registry_dir=registry, unused_path=unused)


def test_snapshot_refuses_unassigned_files_and_tampered_pages(tmp_path):
    raw, layer, source, registry = _collection(tmp_path)
    extra = raw / "extra.txt"
    extra.write_text("unassigned", encoding="utf-8")
    owners, unused, missing = inventory(raw, [Source.model_validate(source)], tmp_path / "unused.yaml")
    assert missing == ["extra.txt"] and len(owners) == 3 and not unused
    with pytest.raises(ValueError, match="lack a registry disposition"):
        freeze("2026-Q4", home=tmp_path / "home", raw_root=raw, registry_dir=registry, unused_path=tmp_path / "unused.yaml")
    extra.unlink()
    (layer / "page_000000.json.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        freeze("2026-Q4", home=tmp_path / "home", raw_root=raw, registry_dir=registry, unused_path=tmp_path / "unused.yaml")


def test_nonspatial_tables_are_not_missing_geometry(tmp_path):
    raw, layer, source, registry = _collection(tmp_path)
    metadata = {"id": 0, "type": "Table", "fields": [{"name": "name"}]}
    (layer / "layer_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    source["layers"][0] = {"layer": "0", "sector": "water", "grain": "registry_table", "metadata_path": "gis/water/layer_metadata.json"}
    (registry / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    result = freeze("2026-Q4", home=tmp_path / "home", raw_root=raw, registry_dir=registry, unused_path=tmp_path / "unused.yaml")
    rows = pq.read_table(result / "manifest.parquet").to_pylist()
    assert all(row["status"] == "nonspatial" for row in rows)


def test_snapshot_records_archive_layer_counts_and_partial_geometry(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    gpkg = tmp_path / "source.gpkg"
    frame = gpd.GeoDataFrame({"name": ["one", "two"]}, geometry=[Polygon([(0, 0), (1, 0), (0, 1)]), None], crs="EPSG:4326")
    frame.to_file(gpkg, layer="areas", driver="GPKG")
    with zipfile.ZipFile(raw / "source.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(gpkg, "data/source.gpkg")
        bundle.writestr("systems.csv", "id,name\n1,one\n2,two\n3,three\n")
    source = {"source_id": "water", "publisher": "Publisher", "driver": "http", "url": "https://example.test/archive", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["source.zip"], "layers": [{"layer": "areas", "archive_member": "data/source.gpkg", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review"}, {"layer": "systems.csv", "sector": "water", "grain": "registry_table", "id_fields": {"source_id": "id"}}]}
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    result = freeze("2026-Q4", home=tmp_path / "home", raw_root=raw, registry_dir=registry, unused_path=tmp_path / "unused.yaml")
    rows = {row["layer"]: row for row in pq.read_table(result / "layers.parquet").to_pylist()}
    assert rows["areas"]["feature_count"] == 2
    assert rows["areas"]["geometry_count"] == 1 and rows["areas"]["status"] == "partial_geometry"
    assert rows["systems.csv"]["feature_count"] == 3 and rows["systems.csv"]["status"] == "nonspatial"


def test_snapshot_revalidates_copied_bytes_after_live_source_changes(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    archive = raw / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("systems.csv", "id,status\n1,A\n")
    source = {"source_id": "water", "publisher": "Publisher", "driver": "http", "url": "https://example.test/archive", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["source.zip"], "layers": [{"layer": "systems.csv", "sector": "water", "grain": "registry_table", "id_fields": {"source_id": "id"}, "status_field": {"field": "status", "values": {"A": "active"}, "on_null": "unknown"}}]}
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    original = snapshot.load_registry
    calls = 0

    def change_after_validation(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("systems.csv", "id,status\n1,B\n")
        return result

    monkeypatch.setattr(snapshot, "load_registry", change_after_validation)
    with pytest.raises(ValueError, match="Unmapped value"):
        freeze("2026-Q4", home=tmp_path / "home", raw_root=raw, registry_dir=registry, unused_path=tmp_path / "unused.yaml")
    assert not (tmp_path / "home" / "snapshots" / "2026-Q4").exists()
