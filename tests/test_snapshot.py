import gzip
import hashlib
import json

import pyarrow.parquet as pq
import pytest
import yaml

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
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": url, "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "name", "on_missing_name": "reject", "metadata_path": "gis/water/layer_metadata.json"}]}
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
