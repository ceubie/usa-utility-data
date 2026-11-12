import gzip
import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import get_args

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
import yaml
from pydantic import ValidationError
from shapely.geometry import Polygon

from utilitydata.registry import (
    AUTHORITIES,
    ZONE_ROLES,
    Authority,
    Sector,
    Source,
    load_registry,
    relaxed_restrictions,
)


def _write_arcgis_snapshot(layer: Path, count: int) -> None:
    page = layer / "page_000000.json.gz"
    digest = hashlib.sha256(page.read_bytes()).hexdigest()
    payload = {"source_layer": "https://example.test/layer", "expected_count_at_start": count, "id_count": count, "downloaded_count": count, "pages": [{"file": page.name, "features": count, "sha256": digest}]}
    (layer / "snapshot.json").write_text(json.dumps(payload), encoding="utf-8")


def test_reviewed_layer_requires_fields_and_rejects_guessing():
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area"}]}
    with pytest.raises(ValidationError, match="role and authority"):
        Source.model_validate(source)
    source["reviewed"] = "false"
    with pytest.raises(ValidationError):
        Source.model_validate(source)


def test_declared_vocabularies_match_registry_validation():
    vocab = Path(__file__).resolve().parents[1] / "registry" / "vocab"
    assert set(yaml.safe_load((vocab / "sector.yaml").read_text(encoding="utf-8"))) == set(get_args(Sector))
    assert set(yaml.safe_load((vocab / "authority.yaml").read_text(encoding="utf-8"))) == set(get_args(Authority)) == AUTHORITIES
    assert set(yaml.safe_load((vocab / "zone_role.yaml").read_text(encoding="utf-8"))) == ZONE_ROLES
    licence_literal = next(value for value in get_args(Source.model_fields["licence"].annotation) if get_args(value))
    assert set(yaml.safe_load((vocab / "licence.yaml").read_text(encoding="utf-8"))) == set(get_args(licence_literal))


def test_registry_checks_exact_metadata_fields_and_review_state(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": "exact_name"}]}), encoding="utf-8")
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer", "expected_count_at_start": 1, "id_count": 1, "downloaded_count": 1, "pages": [{"file": "page_000000.json.gz", "features": 1}]}), encoding="utf-8")
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "not_present", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    file = directory / "publisher.yaml"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing mapped fields"):
        load_registry(directory, raw_root=raw)
    source["layers"][0]["name_field"] = "exact_name"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing snapshot page"):
        load_registry(directory, raw_root=raw)
    with gzip.open(layer / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"exact_name": "water"}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
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
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer", "expected_count_at_start": 1, "id_count": 1, "downloaded_count": 1, "pages": [{"file": "page_000000.json.gz", "features": 1}]}), encoding="utf-8")
    with gzip.open(layer / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "water"}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
    directory = tmp_path / "sources"
    directory.mkdir()
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role_field": {"field": "role", "values": {"serves": "active_retail_service"}, "on_null": "reject"}, "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing attribute"):
        load_registry(directory, raw_root=raw)


def test_role_matrix_requires_exact_observed_combinations(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": "name"}, {"name": "kind"}, {"name": "flag"}]}), encoding="utf-8")
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer", "expected_count_at_start": 1, "id_count": 1, "downloaded_count": 1, "pages": [{"file": "page_000000.json.gz", "features": 1}]}), encoding="utf-8")
    page = layer / "page_000000.json.gz"
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "water", "kind": "school", "flag": "N"}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role_matrix": {"fields": ["kind", "flag"], "cases": [{"values": ["school", "N"], "role": "onsite_noncommunity"}, {"values": ["school", None], "role": "review_required"}]}, "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "metadata_path": "gis/water/layer_metadata.json"}]}
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    assert len(load_registry(directory, raw_root=raw)) == 1
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "water", "kind": "school", "flag": "n"}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
    with pytest.raises(ValueError, match="Value case mismatch"):
        load_registry(directory, raw_root=raw)
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "water", "kind": "school", "flag": "Y"}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
    with pytest.raises(ValueError, match="Unmapped role combination"):
        load_registry(directory, raw_root=raw)


def test_metadata_field_missing_from_features_fails_without_category_mapping(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": "ObjectId"}, {"name": "name"}]}), encoding="utf-8")
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer", "expected_count_at_start": 1, "id_count": 1, "downloaded_count": 1, "pages": [{"file": "page_000000.json.gz", "features": 1}]}), encoding="utf-8")
    with gzip.open(layer / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"ObjectID": 1, "name": "water"}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "id_fields": {"feature_id": "ObjectId"}, "metadata_path": "gis/water/layer_metadata.json"}]}
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"Attribute case mismatch.*ObjectId != ObjectID"):
        load_registry(directory, raw_root=raw)


def test_texas_twdb_objectid_case_and_saved_values_fail_closed(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "texas"
    layer.mkdir(parents=True)
    metadata_fields = ["ObjectId", "PWSName", "Active", "Source"]
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": name} for name in metadata_fields]}), encoding="utf-8")
    features = [
        {"ObjectID": 1, "PWSName": "LAJITAS ON THE RIO GRANDE", "Active": 1, "Source": "System"},
        {"ObjectID": 2, "PWSName": "OTHER", "Active": 0, "Source": "System"},
    ]
    (layer / "snapshot.json").write_text(json.dumps({"source_layer": "https://example.test/layer", "expected_count_at_start": 2, "id_count": 2, "downloaded_count": 2, "pages": [{"file": "page_000000.json.gz", "features": 2}]}), encoding="utf-8")
    page = layer / "page_000000.json.gz"
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": feature} for feature in features]}, stream)
    _write_arcgis_snapshot(layer, 2)
    declaration = {"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "PWSName", "on_missing_name": "preserve_and_review", "metadata_path": "gis/texas/layer_metadata.json", "id_fields": {"feature_id": "ObjectId"}, "state_fixed": "TX"}
    source = {"source_id": "texas_water", "publisher": "Texas Water Development Board", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/texas"], "layers": [declaration]}
    directory = tmp_path / "sources"
    directory.mkdir()
    file = directory / "publisher.yaml"

    def save():
        file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")

    save()
    with pytest.raises(ValueError, match=r"Attribute case mismatch.*ObjectId != ObjectID"):
        load_registry(directory, raw_root=raw)
    declaration["id_fields"] = {"feature_id": "ObjectID"}
    save()
    with pytest.raises(ValueError, match=r"Attribute case mismatch.*ObjectID != ObjectId"):
        load_registry(directory, raw_root=raw)
    declaration.pop("id_fields")
    declaration["status_field"] = {"field": "Active", "values": {"1": "active"}, "on_null": "unknown"}
    save()
    with pytest.raises(ValueError, match=r"Unmapped value 0"):
        load_registry(directory, raw_root=raw)
    declaration["status_field"]["values"] = {"0": "inactive", "1": "active"}
    declaration.pop("role")
    declaration["role_field"] = {"field": "Source", "values": {"system": "active_retail_service"}, "on_null": "reject"}
    save()
    with pytest.raises(ValueError, match=r"Value case mismatch.*'System' != 'system'"):
        load_registry(directory, raw_root=raw)
    features[1]["Source"] = "Other"
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": feature} for feature in features]}, stream)
    _write_arcgis_snapshot(layer, 2)
    declaration["role_field"]["values"] = {"System": "active_retail_service"}
    save()
    with pytest.raises(ValueError, match=r"Unmapped value 'Other'"):
        load_registry(directory, raw_root=raw)
    features[1]["Source"] = "System"
    with gzip.open(page, "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": feature} for feature in features]}, stream)
    _write_arcgis_snapshot(layer, 2)
    declaration.pop("role_field")
    declaration["role"] = "active_retail_service"
    save()
    assert len(load_registry(directory, raw_root=raw)) == 1
    page.unlink()
    with pytest.raises(ValueError, match="Missing snapshot page"):
        load_registry(directory, raw_root=raw)


def test_arcgis_inventory_rejects_nested_and_case_variant_pages(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "water"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(json.dumps({"id": 0, "fields": [{"name": "name"}, {"name": "Active"}]}), encoding="utf-8")
    with gzip.open(layer / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "water", "Active": 1}}]}, stream)
    _write_arcgis_snapshot(layer, 1)
    source = {"source_id": "water", "publisher": "Publisher", "driver": "arcgis", "url": "https://example.test/layer", "cadence": "irregular", "licence": "unknown", "reviewed": True, "paths": ["gis/water"], "layers": [{"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "name", "on_missing_name": "preserve_and_review", "status_field": {"field": "Active", "values": {"1": "active"}, "on_null": "unknown"}, "metadata_path": "gis/water/layer_metadata.json"}]}
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    assert len(load_registry(directory, raw_root=raw)) == 1
    nested = layer / "nested"
    nested.mkdir()
    with gzip.open(nested / "page_000001.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "hidden", "Active": "NOPE"}}]}, stream)
    with pytest.raises(ValueError, match="ArcGIS page inventory mismatch"):
        load_registry(directory, raw_root=raw)
    (nested / "page_000001.json.gz").unlink()
    nested.rmdir()
    with gzip.open(layer / "Page_000001.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "hidden", "Active": "NOPE"}}]}, stream)
    with pytest.raises(ValueError, match="ArcGIS page inventory mismatch"):
        load_registry(directory, raw_root=raw)
    (layer / "Page_000001.json.gz").unlink()
    with gzip.open(layer / "page_000001.JSON.GZ", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": {"name": "hidden", "Active": "NOPE"}}]}, stream)
    with pytest.raises(ValueError, match="ArcGIS page inventory mismatch"):
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
    source["layers"][0]["id_fields"]["pwsid"] = "pwsid"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"Attribute case mismatch.*pwsid != PWSID"):
        load_registry(directory, raw_root=raw)
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
    source["layers"][0]["name_field"] = "Name"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"Attribute case mismatch.*Name != name"):
        load_registry(directory, raw_root=raw)
    source["layers"][0]["name_field"] = "name"
    source["layers"][0]["authority"]["values"] = {"Submitted": "federal_submitted"}
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"Value case mismatch.*'submitted' != 'Submitted'"):
        load_registry(directory, raw_root=raw)
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


def test_single_space_is_a_distinct_coded_value(tmp_path):
    raw = tmp_path / "raw"
    layer = raw / "gis" / "texas"
    layer.mkdir(parents=True)
    (layer / "layer_metadata.json").write_text(
        json.dumps({"id": 0, "fields": [{"name": "Source"}, {"name": "PWSName"}]}),
        encoding="utf-8",
    )
    features = [{"Source": "System", "PWSName": "Kept"}, {"Source": " ", "PWSName": "Space"}]
    with gzip.open(layer / "page_000000.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"features": [{"attributes": feature} for feature in features]}, stream)
    _write_arcgis_snapshot(layer, 2)
    declaration = {
        "layer": "0",
        "sector": "water",
        "grain": "service_area",
        "role": "active_retail_service",
        "authority": "state_regulator",
        "name_field": "PWSName",
        "on_missing_name": "preserve_and_review",
        "metadata_path": "gis/texas/layer_metadata.json",
        "boundary_representation": {"field": "Source", "values": {"System": "unmodeled"}, "on_null": "unknown"},
        "state_fixed": "TX",
    }
    source = {
        "source_id": "texas_water",
        "publisher": "Texas Water Development Board",
        "driver": "arcgis",
        "url": "https://example.test/layer",
        "cadence": "irregular",
        "licence": "unknown",
        "reviewed": True,
        "paths": ["gis/texas"],
        "layers": [declaration],
    }
    directory = tmp_path / "sources"
    directory.mkdir()
    file = directory / "publisher.yaml"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"Unmapped value ' '"):
        load_registry(directory, raw_root=raw)
    declaration["boundary_representation"]["values"][" "] = "unknown"
    file.write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    loaded = load_registry(directory, raw_root=raw)
    assert loaded[0].layers[0].boundary_representation.values[" "] == "unknown"


def test_refused_promotions_stay_draft_and_twdb_maps_the_space():
    registry = Path(__file__).resolve().parents[1] / "registry" / "sources"
    sources = {source.source_id: source for source in load_registry(registry, require_reviewed=False)}
    twdb = sources["texas_water_service_areas_twdb"]
    assert twdb.reviewed is False
    assert twdb.layers[0].boundary_representation.values[" "] == "unknown"
    refused = {
        "kentucky_electric_service_areas_dgi",
        "arkansas_electric_territories_gis",
        "nevada_electric_service_areas_ndom",
        "maine_electric_service_areas_puc_2020",
        "new_jersey_electric_territories_dep",
    }
    assert {source_id for source_id in refused if sources[source_id].reviewed} == set()


def test_a_recorded_restriction_is_never_relaxed():
    def source(source_id: str, licence: str) -> Source:
        return Source.model_validate({"source_id": source_id, "licence": licence})

    previous = [
        source("kept", "internal_or_no_redistribution"),
        source("to_unknown", "internal_or_no_redistribution"),
        source("no_sale_to_unknown", "attribution_no_commercial_sale"),
        source("tightened", "attribution_no_commercial_sale"),
        source("was_unknown", "unknown"),
    ]
    current = [
        source("kept", "internal_or_no_redistribution"),
        source("to_unknown", "unknown"),
        source("no_sale_to_unknown", "unknown"),
        source("tightened", "internal_or_no_redistribution"),
        source("was_unknown", "cc-by-4.0"),
    ]
    assert relaxed_restrictions(previous, current) == ["no_sale_to_unknown", "to_unknown"]


def test_no_restriction_is_relaxed_since_the_frozen_snapshot():
    home = os.environ.get("UTILITYDATA_HOME")
    frozen = Path(home) / "snapshots" / "2026-Q4" / "registry" / "sources" if home else None
    if frozen is None or not frozen.is_dir():
        pytest.skip("The frozen snapshot registry is not available")
    root = Path(__file__).resolve().parents[1]
    previous = load_registry(frozen, require_reviewed=False)
    current = load_registry(root / "registry" / "sources", require_reviewed=False)
    assert relaxed_restrictions(previous, current) == []


def test_draft_partition_lists_every_collection_draft_once():
    root = Path(__file__).resolve().parents[1]
    sources = load_registry(root / "registry" / "sources", require_reviewed=False)
    drafts = {source.source_id for source in sources if not source.reviewed and source.storage == "collection"}
    buckets: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in (root / "docs" / "review-gates.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            name, _space, count = line[3:].rpartition(" ")
            current = buckets.setdefault(name, []) if count.isdigit() and name.replace("_", "").isalpha() else None
            if current is not None:
                current.append(count)
        elif current is not None and line.strip():
            current.append(line.strip())
    listed = [source_id for ids in buckets.values() for source_id in ids[1:]]
    assert {name: int(ids[0]) for name, ids in buckets.items()} == {name: len(ids) - 1 for name, ids in buckets.items()}
    assert len(listed) == len(set(listed))
    assert set(listed) == drafts


def test_wholesaler_mapping_fails_closed_and_keeps_null_unknown(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    archive = raw / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("systems.csv", "id,wholesaler\n1,Y\n2,\n")
    source = {"source_id": "water", "publisher": "Publisher", "driver": "http", "url": "https://example.test/archive", "cadence": "quarterly", "licence": "unknown", "reviewed": True, "paths": ["source.zip"], "layers": [{"layer": "systems.csv", "sector": "water", "grain": "registry_table", "id_fields": {"source_id": "id"}, "wholesaler_field": {"field": "wholesaler", "values": {"Y": "yes", "N": "no"}, "on_null": "unknown"}}]}
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "publisher.yaml").write_text(yaml.safe_dump({"sources": [source]}), encoding="utf-8")
    loaded = load_registry(directory, raw_root=raw)
    assert loaded[0].layers[0].wholesaler_field.on_null == "unknown"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("systems.csv", "id,wholesaler\n1,Z\n")
    with pytest.raises(ValueError, match="Unmapped value"):
        load_registry(directory, raw_root=raw)
