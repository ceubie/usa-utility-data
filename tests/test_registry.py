import gzip
import json
import zipfile

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
import yaml
from pydantic import ValidationError
from shapely.geometry import Polygon

from utilitydata.registry import Source, load_registry


def test_reviewed_layer_requires_fields_and_rejects_guessing():
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area"}]}
    with pytest.raises(ValidationError, match="role and authority"):
        Source.model_validate(source)
    source["reviewed"] = "false"
    with pytest.raises(ValidationError):
        Source.model_validate(source)


def test_registry_checks_exact_metadata_fields_and_review_state(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": "exact_name"}]}), encoding="utf-8")
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer"}), encoding="utf-8")
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "not_present", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    file = directory / "publisher.yaml"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing mapped fields"):
        load_registry(directory, raw_root=raw)
    source["layers"][0]["name_field"] = "exact_name"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    assert len(load_registry(directory, raw_root=raw)) == 1
    source["reviewed"] = False
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="require review"):
        load_registry(directory, raw_root=raw)
    assert len(load_registry(directory, raw_root=raw, require_reviewed=False)) == 1


def test_rejects_invalid_vocabulary_licence_and_state():
    base = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "name_field": "name", "on_missing_name": "preserve_and_review", "role": "active_retail_service", "authority": "state_regulator"}]}
    for key, value in [("role", "made_up"), ("state_fixed", "ZZ"), ("authority", {"field": "kind", "values": {"A": "invented"}})]:
        changed = {**base, "layers": [{**base["layers"][0], key: value}]}
        with pytest.raises(ValidationError):
            Source.model_validate(changed)
    with pytest.raises(ValidationError, match="Unknown or restricted licence"):
        Source.model_validate({**base, "redistribution": "shareable"})


def test_layer_id_and_metadata_source_must_match(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 1, "fields": [{"name": "name"}]}), encoding="utf-8")
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Layer ID"):
        load_registry(directory, raw_root=raw)


def test_mapped_attribute_missing_from_feature_is_not_a_null(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": "name"}, {"name": "role"}]}), encoding="utf-8")
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer"}), encoding="utf-8")
    with gzip.open(layer / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "water"}}]}, stream)
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role_field": {"field": "role", "values": {"serves": "active_retail_service"}, "on_null": "reject"}, "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing attribute"):
        load_registry(directory, raw_root=raw)


def test_reviewed_csv_archive_validates_member_columns_and_values(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    archive = raw / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("systems.csv", "PWSID,status\nWA53AA101,A\n")
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "http", "url": "https://example.test/archive", "cadence": "quarterly", "licence": "unknown", "reviewed": True, "paths": ["source.zip"], "layers": [{"layer": "systems.csv", "sector": "water", "grain": "registry_table", "id_fields": {"pwsid": "PWSID"}, "on_invalid_pwsid": "preserve_raw_without_federal_id", "status_field": {"field": "status", "values": {"A": "active"}, "on_null": "unknown"}}]}
    file = directory / "publisher.yaml"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    assert len(load_registry(directory, raw_root=raw)) == 1
    source["layers"][0]["id_fields"]["pwsid"] = "missing"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing mapped fields"):
        load_registry(directory, raw_root=raw)
    source["layers"][0]["id_fields"]["pwsid"] = "PWSID"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("systems.csv", "PWSID,PWSID,status\nONE,TWO,A\n")
    with pytest.raises(ValueError, match="duplicate CSV header"):
        load_registry(directory, raw_root=raw)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("systems.csv", "PWSID,status\nONE\n")
    with pytest.raises(ValueError, match="Malformed CSV row"):
        load_registry(directory, raw_root=raw)
    source["layers"][0].pop("status_field")
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed CSV row"):
        load_registry(directory, raw_root=raw)


def test_geopackage_archive_validates_layer_and_mappings(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    gpkg = tmp_path / "source.gpkg"
    frame = gpd.GeoDataFrame({"name": ["Provider"], "kind": ["submitted"]}, geometry=[Polygon([(0, 0), (1, 0), (0, 1)])], crs="EPSG:4326")
    frame.to_file(gpkg, layer="areas", driver="GPKG")
    with zipfile.ZipFile(raw / "source.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(gpkg, "data/source.gpkg")
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "http", "url": "https://example.test/archive", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["source.zip"], "layers": [{"layer": "areas", "archive_member": "data/source.gpkg", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": {"field": "kind", "values": {"submitted": "federal_submitted"}, "on_null": "reject"}, "name_field": "name", "on_missing_name": "preserve_and_review"}]}
    file = directory / "publisher.yaml"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    assert len(load_registry(directory, raw_root=raw)) == 1
    source["layers"][0]["authority"]["values"] = {"different": "federal_submitted"}
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unmapped value"):
        load_registry(directory, raw_root=raw)
    source["layers"][0]["authority"]["values"] = {"submitted": "federal_submitted"}
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    nonspatial = tmp_path / "nonspatial.gpkg"
    pyogrio.write_dataframe(pd.DataFrame({"name": ["Provider"], "kind": ["submitted"]}), nonspatial, layer="areas", driver="GPKG")
    with zipfile.ZipFile(raw / "source.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(nonspatial, "data/source.gpkg")
    with pytest.raises(ValueError, match="Spatial layer has no geometry"):
        load_registry(directory, raw_root=raw)
