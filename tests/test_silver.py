import json
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyogrio
import pytest
import shapely
from pyproj import CRS

from utilitydata.registry import FieldMap, Layer, Source
from utilitydata.sectors.promote import PROMOTION_BACKUPS, promote_reviewed_collection
from utilitydata.silver.boundaries import (
    _extracted_member,
    _read_unarchived_job,
    _read_vector_job,
    _reconcile,
    _write_boundaries,
    build_layer_rows,
    geoparquet_metadata_present,
    parse_vintage,
    select_water_jobs,
)
from utilitydata.silver.geometry import hilbert_distances, prepare_geometries
from utilitydata.silver.ids import normalize_pwsid
from utilitydata.silver.tables import load_sdwa_tables

ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "snapshots" / "2026-Q4" / "files" / "water" / "epa_pws_boundaries_latest.zip"
STATES = {"KS", "MA", "MO", "OK"}


def test_vintage_accepts_epoch_milliseconds_and_year_first_dates():
    assert parse_vintage(1793782800000) == date(2026, 11, 4)
    assert parse_vintage("2007/12/04") == date(2007, 12, 4)
    assert parse_vintage(2000) == date(2000, 1, 1)
    assert parse_vintage("02/10/1983") == date(1983, 2, 10)
    assert parse_vintage(None) is None


def test_standard_and_tribal_identifiers_stay_unchanged():
    counts = {"090600058": 1, "WA53AA101": 1}
    standard = normalize_pwsid("090600058", state_prefix_7=True, state="MA", sdwis_counts=counts)
    trimmed = normalize_pwsid("ND2801430\r\n", state_prefix_7=False, state="ND", sdwis_counts={})
    assert standard.federal_id == "090600058"
    assert standard.exception is False
    assert standard.raw == "090600058"
    assert trimmed.federal_id == "ND2801430"
    assert trimmed.raw == "ND2801430"
    interior = normalize_pwsid("ND28 01430", state_prefix_7=True, state="ND", sdwis_counts={})
    assert interior.federal_id is None
    assert interior.raw == "ND28 01430"


def test_state_prefix_is_added_only_when_requested():
    prefixed = normalize_pwsid("1225038", state_prefix_7=True, state="MA", sdwis_counts={})
    plain = normalize_pwsid("1225038", state_prefix_7=False, state="MA", sdwis_counts={})
    nine = normalize_pwsid("090600058", state_prefix_7=True, state="MA", sdwis_counts={})
    short = normalize_pwsid("123456", state_prefix_7=True, state="MA", sdwis_counts={})
    assert prefixed.federal_id == "MA1225038"
    assert prefixed.raw == "1225038"
    assert plain.federal_id is None
    assert plain.reason == "unmatched_pwsid"
    assert nine.federal_id == "090600058"
    assert short.federal_id is None


def test_unique_sdwis_exception_and_unmatched_values():
    counts = {"WA53AA101": 1, "WA53HD840": 1, "UTAH18166": 1, "WA53AA101-DUP": 2}
    for value in ("WA53AA101", "WA53HD840", "UTAH18166"):
        result = normalize_pwsid(f"  {value}  ", state_prefix_7=True, state="MA", sdwis_counts=counts)
        assert result.federal_id == value
        assert result.exception is True
    duplicate = normalize_pwsid("WA53AA101", state_prefix_7=False, state=None, sdwis_counts={"WA53AA101": 2})
    missing = normalize_pwsid("OKMCD0003", state_prefix_7=False, state="OK", sdwis_counts=counts)
    many = normalize_pwsid("ND5101125; ND5101065; ND3101807 \r\n", state_prefix_7=False, state=None, sdwis_counts=counts)
    assert duplicate.federal_id is None
    assert duplicate.reason == "nonunique_sdwis_match"
    assert missing.federal_id is None
    assert missing.raw == "OKMCD0003"
    assert many.federal_id is None
    assert many.reason == "multiple_identifiers"
    assert many.candidates == ("ND5101125", "ND5101065", "ND3101807")


def test_geometry_preparation_drops_empties_and_reprojects():
    polygon = shapely.box(0, 0, 1, 1)
    prepared, hashes, areas, keep = prepare_geometries(np.array([polygon, None], dtype=object), CRS.from_epsg(4326))
    assert keep.tolist() == [True, False]
    assert prepared[1] is None
    assert hashes[0] == prepare_geometries(np.array([polygon], dtype=object), CRS.from_epsg(4326))[1][0]
    assert areas[0] > 0
    projected = shapely.box(-1_000, -1_000, 1_000, 1_000)
    moved, _hashes, _areas, moved_keep = prepare_geometries(np.array([projected], dtype=object), CRS.from_epsg(3857))
    assert moved_keep.tolist() == [True]
    minimum_x, minimum_y, maximum_x, maximum_y = shapely.bounds(moved[0])
    assert max(abs(minimum_x), abs(minimum_y), abs(maximum_x), abs(maximum_y)) < 1
    assert int(hilbert_distances(np.array([-180.0]), np.array([-90.0]))[0]) == 0


def test_reject_counts_reconcile_on_a_fixture():
    layer = Layer(
        layer="0",
        sector="water",
        grain="service_area",
        role="active_retail_service",
        authority=FieldMap(field="AUTH", values={"S": "state_regulator"}, on_null="reject"),
        name_field="NAME",
        on_missing_name="preserve_and_review",
        id_fields={"feature_id": "ID"},
        state_fixed="KS",
    )
    polygon = shapely.box(-100, 38, -99, 39)
    rows = build_layer_rows(
        source_id="fixture",
        licence="unknown",
        layer=layer,
        attributes=[
            {"ID": 1, "NAME": "Kept", "AUTH": "S"},
            {"ID": 2, "NAME": "No authority", "AUTH": None},
            {"ID": 3, "NAME": "Empty", "AUTH": "S"},
        ],
        geometries=np.array([polygon, polygon, None], dtype=object),
        source_crs=CRS.from_epsg(4326),
        sdwis_counts={},
        known_states=STATES,
        spatial=True,
    )
    assert len(rows.assertions) + len(rows.rejects) == 3
    assert len(rows.assertions) == 1
    assert {row["reason"] for row in rows.rejects} == {"null_authority", "empty_geometry"}
    assert rows.assertions[0]["zone_role"] == "active_retail_service"
    assert rows.assertions[0]["licence"] == "unknown"


def test_registry_pwsid_rule_controls_the_prefix_and_preserves_review_rows():
    polygon = shapely.box(-72, 42, -71, 43)
    shared = {"layer": "0", "sector": "water", "grain": "service_area", "role": "active_retail_service", "authority": "state_regulator", "name_field": "NAME", "on_missing_name": "preserve_and_review", "id_fields": {"feature_id": "ID", "pwsid": "PWS_ID"}, "on_invalid_pwsid": "preserve_raw_without_federal_id", "state_fixed": "MA"}
    prefixed = build_layer_rows(source_id="mass", licence="unknown", layer=Layer(**shared, pwsid_rule="state_prefix_7"), attributes=[{"ID": 1, "NAME": "Park", "PWS_ID": 1225038}], geometries=np.array([polygon], dtype=object), source_crs=CRS.from_epsg(4326), sdwis_counts={}, known_states=STATES, spatial=True)
    unchanged = build_layer_rows(source_id="mass", licence="unknown", layer=Layer(**shared, pwsid_rule="state_prefix_7"), attributes=[{"ID": 2, "NAME": "Tribal", "PWS_ID": "090600058"}], geometries=np.array([polygon], dtype=object), source_crs=CRS.from_epsg(4326), sdwis_counts={"090600058": 1}, known_states=STATES, spatial=True)
    unprefixed = build_layer_rows(source_id="mass", licence="unknown", layer=Layer(**shared), attributes=[{"ID": 3, "NAME": "Park", "PWS_ID": "1225038"}], geometries=np.array([polygon], dtype=object), source_crs=CRS.from_epsg(4326), sdwis_counts={}, known_states=STATES, spatial=True)
    florida = dict(shared)
    florida["state_fixed"] = "FL"
    unnamed = build_layer_rows(source_id="florida", licence="unknown", layer=Layer(**florida), attributes=[{"ID": 4, "NAME": None, "PWS_ID": "FL4565183"}], geometries=np.array([polygon], dtype=object), source_crs=CRS.from_epsg(4326), sdwis_counts={}, known_states=STATES | {"FL"}, spatial=True)
    assert prefixed.assertions[0]["pwsid"] == "MA1225038"
    assert prefixed.assertions[0]["pwsid_raw"] == "1225038"
    assert unchanged.assertions[0]["pwsid"] == "090600058"
    assert unprefixed.assertions[0]["pwsid"] is None
    assert unprefixed.assertions[0]["needs_review"] is True
    assert unnamed.assertions[0]["pwsid"] == "FL4565183"
    assert unnamed.assertions[0]["raw_name"] is None
    assert "missing_name" in unnamed.assertions[0]["review_reason"]


def test_multiple_identifiers_stay_one_assertion_without_a_federal_id():
    layer = Layer(
        layer="CWS",
        sector="water",
        grain="service_area",
        role_field=FieldMap(field="TYPE", values={"Municipality": "active_retail_service"}, on_null="review_required"),
        authority="federal_submitted",
        name_field="NAME",
        on_missing_name="preserve_and_review",
        id_fields={"feature_id": "ID", "pwsid": "PWSID"},
        on_invalid_pwsid="preserve_raw_without_federal_id",
        state_fixed="ND",
    )
    rows = build_layer_rows(
        source_id="epa",
        licence="unknown",
        layer=layer,
        attributes=[{"ID": 9, "NAME": "  ", "PWSID": "ND5101125; ND5101065", "TYPE": "Municipality"}],
        geometries=np.array([shapely.box(-101, 46, -100, 47)], dtype=object),
        source_crs=CRS.from_epsg(4326),
        sdwis_counts={"ND5101125": 1, "ND5101065": 1},
        known_states=STATES | {"ND"},
        spatial=True,
    )
    assert len(rows.assertions) == 1
    assert rows.assertions[0]["pwsid"] is None
    assert rows.assertions[0]["zone_role"] == "active_retail_service"
    assert [row["candidate"] for row in rows.candidates] == ["ND5101125", "ND5101065"]
    assert all(row["federal_id"] is None for row in rows.candidates)


def test_trailing_space_is_a_distinct_coded_value_and_networks_are_not_retail():
    coded = Layer(
        layer="0",
        sector="water",
        grain="service_area",
        role_field=FieldMap(field="CODE", values={"A ": "active_retail_service", "A": "review_required"}, on_null="review_required"),
        authority="state_regulator",
        name_field="NAME",
        on_missing_name="preserve_and_review",
        id_fields={"feature_id": "ID"},
        state_fixed="KS",
        status_field=FieldMap(field="ACTIVITY_STATUS_CD", values={"A ": "active"}, on_null="unknown"),
    )
    rows = build_layer_rows(
        source_id="coded",
        licence="unknown",
        layer=coded,
        attributes=[{"ID": 1, "NAME": "Exact", "CODE": "A ", "ACTIVITY_STATUS_CD": "A "}, {"ID": 2, "NAME": "Other", "CODE": "A", "ACTIVITY_STATUS_CD": None}],
        geometries=np.array([shapely.box(-100, 38, -99, 39), shapely.box(-100, 38, -99, 39)], dtype=object),
        source_crs=CRS.from_epsg(4326),
        sdwis_counts={},
        known_states=STATES,
        spatial=True,
    )
    assert [row["zone_role"] for row in rows.assertions] == ["active_retail_service", "review_required"]
    assert rows.assertions[0]["activity_status"] == "active"
    assert "unknown_status" in rows.assertions[1]["review_reason"]
    network = Layer(layer="4", sector="water", grain="network", name_field="OWNER", id_fields={"feature_id": "ID"}, state_fixed="DC")
    pipes = build_layer_rows(
        source_id="pipes",
        licence="unknown",
        layer=network,
        attributes=[{"ID": 7, "OWNER": "DC Water"}],
        geometries=np.array([shapely.linestrings([[-77.0, 38.9], [-77.1, 38.9]])], dtype=object),
        source_crs=CRS.from_epsg(4326),
        sdwis_counts={},
        known_states=STATES | {"DC"},
        spatial=True,
    )
    assert pipes.assertions[0]["zone_role"] is None
    assert pipes.assertions[0]["area_km2"] == 0


def test_state_mismatch_is_flagged_from_the_representative_point():
    layer = Layer(
        layer="0",
        sector="water",
        grain="service_area",
        role="active_retail_service",
        authority="state_regulator",
        name_field="NAME",
        on_missing_name="preserve_and_review",
        id_fields={"feature_id": "ID"},
        state_fixed="KS",
    )
    rows = build_layer_rows(
        source_id="kansas",
        licence="unknown",
        layer=layer,
        attributes=[{"ID": 1, "NAME": "Inside"}, {"ID": 2, "NAME": "Outside"}],
        geometries=np.array([shapely.box(-100, 38, -99, 39), shapely.box(-94, 38, -93, 39)], dtype=object),
        source_crs=CRS.from_epsg(4326),
        sdwis_counts={},
        known_states=STATES,
        state_geometries=np.array([shapely.box(-102, 37, -95, 40)], dtype=object),
        state_codes=np.array(["KS"], dtype=object),
        spatial=True,
    )
    assert rows.assertions[0]["geom_state"] == "KS"
    assert rows.assertions[0]["state_mismatch"] is False
    assert rows.assertions[1]["geom_state"] is None
    assert "geom_state_unresolved" in rows.assertions[1]["review_reason"]


def test_draft_water_sources_are_not_selected():
    reviewed = Source(
        source_id="reviewed_water",
        publisher="Publisher",
        driver="arcgis",
        url="https://example.test/layer",
        cadence="irregular",
        licence="unknown",
        reviewed=True,
        paths=["gis/reviewed_water"],
        layers=[Layer(layer="0", sector="water", grain="service_area", role="active_retail_service", authority="state_regulator", name_field="NAME", on_missing_name="preserve_and_review")],
    )
    draft = Source(source_id="draft_water", reviewed=False, layers=[Layer(layer="0", sector="water")])
    layers = pd.DataFrame([
        {"source_id": "reviewed_water", "layer": "0", "feature_count": 1, "status": "collected"},
        {"source_id": "draft_water", "layer": "0", "feature_count": 5, "status": "draft"},
    ])
    jobs, drafts = select_water_jobs([reviewed, draft], layers)
    assert [job.source.source_id for job in jobs] == ["reviewed_water"]
    assert drafts == ["draft_water"]


def test_open_ended_date_token_is_preserved_without_dropping_the_row(tmp_path):
    archive = tmp_path / "sdwa.zip"
    text = "PWSID,NON_COMPL_PER_END_DATE\nPA3540384,--->\nPA3540384,12/22/1983\n"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("SDWA_VIOLATIONS_ENFORCEMENT.csv", text)
    counts, _identifiers = load_sdwa_tables(archive, {"SDWA_VIOLATIONS_ENFORCEMENT.csv": {"PWSID"}}, tmp_path, pwsid_column="PWSID")
    frame = pq.read_table(tmp_path / "sdwa_violation.parquet").to_pandas()
    assert counts["sdwa_violation"] == 2
    assert pd.isna(frame.loc[0, "NON_COMPL_PER_END_DATE"])
    assert frame.loc[0, "NON_COMPL_PER_END_DATE_unparsed"] == "--->"
    assert pd.isna(frame.loc[1, "NON_COMPL_PER_END_DATE_unparsed"])


def test_sdwa_table_keeps_inactive_rows_and_rejects_a_short_row(tmp_path):
    archive = tmp_path / "sdwa.zip"
    header = "PWSID,PWS_NAME,PWS_ACTIVITY_CODE,POPULATION_SERVED_COUNT,FIRST_REPORTED_DATE,IS_WHOLESALER_IND\n"
    body = "090600058,Example,I,0,02/10/1983,Y\nWA53AA101,Other,A,,09/28/2026,\n"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("SDWA_PUB_WATER_SYSTEMS.csv", header + body)
    counts, identifiers = load_sdwa_tables(archive, {"SDWA_PUB_WATER_SYSTEMS.csv": {"PWSID", "PWS_ACTIVITY_CODE"}}, tmp_path, pwsid_column="PWSID")
    frame = pq.read_table(tmp_path / "sdwa_public_water_system.parquet").to_pandas()
    assert counts["sdwa_public_water_system"] == 2
    assert set(frame["PWS_ACTIVITY_CODE"]) == {"I", "A"}
    assert identifiers["090600058"] == 1
    assert int(frame.loc[frame["PWSID"].eq("090600058"), "POPULATION_SERVED_COUNT"].iloc[0]) == 0
    assert pd.isna(frame.loc[frame["PWSID"].eq("WA53AA101"), "POPULATION_SERVED_COUNT"].iloc[0])
    assert pd.isna(frame.loc[frame["PWSID"].eq("090600058"), "FIRST_REPORTED_DATE_unparsed"].iloc[0])
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("SDWA_PUB_WATER_SYSTEMS.csv", "PWSID,PWS_NAME\n090600058,Example\n")
    with pytest.raises(ValueError, match="Missing columns"):
        load_sdwa_tables(archive, {"SDWA_PUB_WATER_SYSTEMS.csv": {"PWSID", "PWS_ACTIVITY_CODE"}}, tmp_path, pwsid_column="PWSID")
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("SDWA_PUB_WATER_SYSTEMS.csv", header + "090600058,Example,I\n")
    with pytest.raises(ValueError, match="Malformed CSV row"):
        load_sdwa_tables(archive, {"SDWA_PUB_WATER_SYSTEMS.csv": {"PWSID"}}, tmp_path, pwsid_column="PWSID")


def test_boundary_output_has_geoparquet_metadata(tmp_path):
    layer = Layer(
        layer="0",
        sector="water",
        grain="service_area",
        role="active_retail_service",
        authority="state_regulator",
        name_field="NAME",
        on_missing_name="preserve_and_review",
        id_fields={"feature_id": "ID"},
        state_fixed="KS",
    )
    rows = build_layer_rows(
        source_id="fixture",
        licence="unknown",
        layer=layer,
        attributes=[{"ID": 1, "NAME": "Kept"}],
        geometries=np.array([shapely.box(-100, 38, -99, 39)], dtype=object),
        source_crs=CRS.from_epsg(4326),
        sdwis_counts={},
        known_states=STATES,
        spatial=True,
    )
    path = tmp_path / "boundary_assertion.parquet"
    _write_boundaries(pd.DataFrame(rows.assertions), np.array(rows.geometries, dtype=object), path)
    assert geoparquet_metadata_present(path)
    metadata = json.loads(pq.read_schema(path).metadata[b"geo"])
    assert metadata["columns"]["geometry"]["covering"]["bbox"]["xmin"][0] == "bbox"
    opened = gpd.read_parquet(path)
    assert len(opened) == 1
    assert opened.crs is not None
    assert opened.geometry.iloc[0] is not None


def test_reviewed_draft_snapshot_promotes_zipped_shapefile_and_geopackage(tmp_path):
    home = tmp_path / "home"
    quarter = "2026-Q4"
    files = home / "snapshots" / quarter / "files"
    _write_vector_fixtures(files)
    sources = [_water_source("fixture_zip_water", "zipped/water.zip", archive_member="areas.shp"), _water_source("fixture_gpkg_water", "standalone/areas.gpkg", archive_member=None)]
    _write_draft_tables(home, quarter, sources)
    snapshot = home / "snapshots" / quarter
    before = {name: (snapshot / name).read_bytes() for name in ("layers.parquet", "manifest.parquet")}
    promoted = promote_reviewed_collection(home, quarter, sources, {source.source_id for source in sources})
    assert promoted == ["fixture_gpkg_water", "fixture_zip_water"]
    backups = list((snapshot / PROMOTION_BACKUPS).iterdir())
    assert len(backups) == 1
    assert {name: (backups[0] / name).read_bytes() for name in before} == before
    assert json.loads((backups[0] / "promoted.json").read_text()) == promoted
    assert promote_reviewed_collection(home, quarter, sources, {source.source_id for source in sources}) == []
    assert len(list((snapshot / PROMOTION_BACKUPS).iterdir())) == 1
    layers = pd.read_parquet(home / "snapshots" / quarter / "layers.parquet")
    assert set(layers["status"]) <= {"collected", "partial_geometry"}
    assert layers["feature_count"].astype(int).tolist() == [2, 2]
    jobs, drafts = select_water_jobs(sources, layers)
    assert drafts == []
    written: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    for job in jobs:
        if job.layer.archive_member:
            with _extracted_member(files / job.relative_path, job.layer.archive_member) as extracted:
                attributes, geometries, crs = _read_vector_job(extracted, job)
        else:
            attributes, geometries, crs = _read_unarchived_job(home, quarter, job)
        rows = build_layer_rows(
            source_id=job.source.source_id,
            licence=job.source.licence,
            layer=job.layer,
            attributes=attributes,
            geometries=geometries,
            source_crs=crs,
            sdwis_counts={},
            known_states=STATES,
            spatial=True,
        )
        assert len(rows.assertions) + len(rows.attributes) + len(rows.rejects) == len(attributes) == 2
        assert len(rows.assertions) == 2
        written[job.source.source_id] += len(rows.assertions) + len(rows.attributes)
        rejected[job.source.source_id] += len(rows.rejects)
    _reconcile(jobs, written, rejected)
    assert written["fixture_zip_water"] == 2
    assert written["fixture_gpkg_water"] == 2


def _water_source(source_id: str, relative: str, archive_member: str | None) -> Source:
    return Source(
        source_id=source_id,
        publisher="Publisher",
        driver="http",
        url="https://example.test/water",
        cadence="irregular",
        licence="unknown",
        reviewed=True,
        paths=[relative],
        layers=[
            Layer(
                layer="areas",
                archive_member=archive_member,
                sector="water",
                grain="service_area",
                role="active_retail_service",
                authority="state_regulator",
                name_field="NAME",
                on_missing_name="preserve_and_review",
                id_fields={"feature_id": "ID"},
                state_fixed="KS",
            )
        ],
    )


def _write_vector_fixtures(files: Path) -> None:
    frame = gpd.GeoDataFrame(
        {"ID": ["1", "2"], "NAME": ["Kept", "Also"]},
        geometry=[shapely.box(-100, 38, -99, 39), shapely.box(-99, 38, -98, 39)],
        crs="EPSG:4326",
    )
    shapefile_dir = files / "shapefile"
    shapefile_dir.mkdir(parents=True)
    frame.to_file(shapefile_dir / "areas.shp")
    archive = files / "zipped"
    archive.mkdir()
    with zipfile.ZipFile(archive / "water.zip", "w") as bundle:
        for path in shapefile_dir.glob("areas.*"):
            bundle.write(path, path.name)
    standalone = files / "standalone"
    standalone.mkdir()
    frame.to_file(standalone / "areas.gpkg", layer="areas", driver="GPKG")


def _write_draft_tables(home: Path, quarter: str, sources: list[Source]) -> None:
    snapshot = home / "snapshots" / quarter
    layer_schema = pa.schema([
        ("source_id", pa.string()),
        ("relative_path", pa.string()),
        ("archive_member", pa.string()),
        ("layer", pa.string()),
        ("feature_count", pa.int64()),
        ("geometry_count", pa.int64()),
        ("status", pa.string()),
    ])
    manifest_schema = pa.schema([
        ("source_id", pa.string()),
        ("relative_path", pa.string()),
        ("sha256", pa.string()),
        ("bytes", pa.int64()),
        ("retrieved_utc", pa.string()),
        ("feature_count", pa.int64()),
        ("has_geometry", pa.bool_()),
        ("status", pa.string()),
    ])
    layer_rows = []
    manifest_rows = []
    for source in sources:
        for layer in source.layers:
            layer_rows.append({
                "source_id": source.source_id,
                "relative_path": source.paths[0],
                "archive_member": layer.archive_member,
                "layer": layer.layer,
                "feature_count": None,
                "geometry_count": None,
                "status": "draft",
            })
        manifest_rows.append({
            "source_id": source.source_id,
            "relative_path": source.paths[0],
            "sha256": "0" * 64,
            "bytes": 1,
            "retrieved_utc": None,
            "feature_count": None,
            "has_geometry": None,
            "status": "draft",
        })
    pq.write_table(pa.Table.from_pylist(layer_rows, schema=layer_schema), snapshot / "layers.parquet")
    pq.write_table(pa.Table.from_pylist(manifest_rows, schema=manifest_schema), snapshot / "manifest.parquet")


@pytest.mark.skipif(not ARCHIVE.exists(), reason="frozen 2026-Q4 snapshot is not in the workspace")
def test_frozen_community_layer_authority_counts():
    path = f"/vsizip/{ARCHIVE.resolve().as_posix()}/3_0/Service_Areas_V_3_0.gpkg"
    frame = pyogrio.read_dataframe(path, layer="CWS", columns=["Symbology_Field"], read_geometry=False)
    counts = frame["Symbology_Field"].value_counts()
    assert int(counts["System Sourced"]) == 25_409
    assert int(counts["Modeled"]) == 19_247
    assert int(counts.sum()) == 44_656
