"""Schema card coverage."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from app.backend.agent.schema_card import build_schema_card
from app.backend.main import create_app
from app.backend.settings import Settings, get_settings, repository_root
from utilitydata.graph.spec import EDGE_FIELDS, EDGE_FILES, NODE_FIELDS, SECTOR_CLASSES

_NODE_TO_CLASS = {
    "organization": "Organization",
    "utility_system": "UtilitySystem",
    "service_area": "ServiceArea",
    "facility": "Facility",
    "county": "County",
    "state": "State",
    "place": "Place",
    "source": "Source",
    "county_coverage": "CountyCoverage",
}


def _expected_counts(release_dir: Path) -> tuple[dict[str, int], dict[str, int]]:
    manifest = json.loads((release_dir / "graph" / "manifest.json").read_text(encoding="utf-8"))
    nodes_dir = release_dir / "graph" / "nodes"
    expected_classes = {
        class_name: int(manifest["node_rows"][node_key])
        for node_key, class_name in _NODE_TO_CLASS.items()
    }
    for class_name in SECTOR_CLASSES.values():
        expected_classes[class_name] = 0
    connection = duckdb.connect()
    try:
        sector_rows = connection.execute(
            "SELECT sector, count(*)::BIGINT FROM read_parquet(?) GROUP BY 1",
            [str(nodes_dir / "utility_system.parquet")],
        ).fetchall()
        cov_row = connection.execute(
            """
            SELECT
                count(*) FILTER (WHERE system_iri IS NOT NULL)::BIGINT,
                count(*) FILTER (WHERE county_iri IS NOT NULL)::BIGINT
            FROM read_parquet(?)
            """,
            [str(nodes_dir / "county_coverage.parquet")],
        ).fetchone()
    finally:
        connection.close()
    for sector, count in sector_rows:
        expected_classes[SECTOR_CLASSES[str(sector)]] = int(count)
    assert sum(expected_classes[name] for name in SECTOR_CLASSES.values()) == expected_classes["UtilitySystem"]
    expected_links = {
        link_name: int(manifest["edge_rows"][stem])
        for link_name, stem in EDGE_FILES.items()
    }
    assert cov_row is not None
    expected_links["system"] = int(cov_row[0])
    expected_links["county"] = int(cov_row[1])
    return expected_classes, expected_links


def _assert_card_matches_release(settings: Settings) -> None:
    card = build_schema_card(settings)
    parsed = Graph()
    parsed.parse(repository_root() / "graph" / "ontology.ttl")
    classes = {_local(str(iri)) for iri in parsed.subjects(RDF.type, RDFS.Class)}
    links = {_local(str(iri)) for iri in parsed.subjects(RDF.type, OWL.ObjectProperty)}
    card_classes = {item.name for item in card.classes}
    card_links = {item.name for item in card.links}
    assert classes <= card_classes
    assert links <= card_links
    assert card.prefixes.startswith("PREFIX rdf:")
    assert card.iri_patterns

    expected_classes, expected_links = _expected_counts(settings.release_dir)
    by_class = {item.name: item.count for item in card.classes}
    by_link = {item.name: item.count for item in card.links}
    for name, count in expected_classes.items():
        assert by_class[name] == count
    for name, count in expected_links.items():
        assert by_link[name] == count

    authority = next(item for item in card.attributes if item.name == "authority")
    assert authority.values is not None
    assert {"utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy"} <= set(authority.values)


@pytest.mark.requires_release
def test_every_ontology_class_and_link_is_in_the_schema_card():
    settings = get_settings()
    manifest = json.loads((settings.release_dir / "graph" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["release"] == settings.utilitydata_release
    _assert_card_matches_release(settings)


def test_schema_card_and_stats_follow_the_served_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    release_id = "2026Q4.test"
    release_dir = tmp_path / "releases" / release_id
    graph_dir = release_dir / "graph"
    nodes_dir = graph_dir / "nodes"
    edges_dir = graph_dir / "edges"
    nodes_dir.mkdir(parents=True)
    edges_dir.mkdir(parents=True)

    _write_parquet(
        nodes_dir / "organization.parquet",
        NODE_FIELDS["organization"],
        [_org_row(i) for i in range(3)],
    )
    _write_parquet(
        nodes_dir / "utility_system.parquet",
        NODE_FIELDS["utility_system"],
        [
            _system_row("SYS_W1", "water", "WaterSystem"),
            _system_row("SYS_W2", "water", "WaterSystem"),
            _system_row("SYS_E1", "electric", "ElectricSystem"),
        ],
    )
    authorities = ("utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy")
    _write_parquet(
        nodes_dir / "service_area.parquet",
        NODE_FIELDS["service_area"],
        [_area_row(i, auth) for i, auth in enumerate(authorities)],
    )
    _write_parquet(nodes_dir / "facility.parquet", NODE_FIELDS["facility"], [])
    _write_parquet(nodes_dir / "county.parquet", NODE_FIELDS["county"], [])
    _write_parquet(
        nodes_dir / "state.parquet",
        NODE_FIELDS["state"],
        [{
            "iri": "http://utilities.local/state/TX",
            "rdf_types": ["State"],
            "state": "48",
            "geoid": "48",
            "usps": "TX",
            "name": "Texas",
            "pop20": 29_145_505,
        }],
    )
    _write_parquet(nodes_dir / "place.parquet", NODE_FIELDS["place"], [])
    _write_parquet(nodes_dir / "source.parquet", NODE_FIELDS["source"], [])
    _write_parquet(
        nodes_dir / "county_coverage.parquet",
        NODE_FIELDS["county_coverage"],
        [{
            "iri": "http://utilities.local/coverage/SYS_W1/48453",
            "rdf_types": ["CountyCoverage"],
            "system_iri": "http://utilities.local/system/SYS_W1",
            "county_iri": "http://utilities.local/county/48453",
            "system_id": "SYS_W1",
            "county_geoid": "48453",
            "state": "48",
            "sector": "water",
            "pop_in_area": 100,
            "housing_in_area": 40,
            "pop_share_of_county": 0.1,
            "pop_share_of_system": 1.0,
            "area_share": 0.1,
            "evidence": "polygon",
            "authority": "utility_direct",
            "is_served": True,
            "licence": "public_domain",
            "source_id": "src_w",
            "in_federal_registry": True,
        }],
    )
    for stem, fields in EDGE_FIELDS.items():
        rows = (
            [{
                "subject_iri": "http://utilities.local/system/SYS_W1",
                "object_iri": "http://utilities.local/county/48453",
                "predicate": "servesCounty",
                "system_id": "SYS_W1",
                "county_geoid": "48453",
                "sector": "water",
            }]
            if stem == "serves_county"
            else []
        )
        _write_parquet(edges_dir / f"{stem}.parquet", fields, rows)

    manifest = {
        "release": release_id,
        "node_rows": {name: pq.ParquetFile(nodes_dir / f"{name}.parquet").metadata.num_rows for name in NODE_FIELDS},
        "edge_rows": {stem: pq.ParquetFile(edges_dir / f"{stem}.parquet").metadata.num_rows for stem in EDGE_FIELDS},
    }
    (graph_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setenv("UTILITYDATA_HOME", str(tmp_path))
    monkeypatch.setenv("UTILITYDATA_RELEASE", release_id)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        _assert_card_matches_release(settings)
        with TestClient(create_app()) as client:
            stats = client.get("/api/stats")
        assert stats.status_code == 200
        payload = stats.json()
        assert payload["release"] == release_id
        by_class = {item["name"]: item["count"] for item in payload["classes"]}
        assert by_class["Organization"] == 3
        assert by_class["WaterSystem"] == 2
        assert by_class["ElectricSystem"] == 1
        assert by_class["ServiceArea"] == 5
    finally:
        get_settings.cache_clear()


def _org_row(index: int) -> dict[str, object]:
    return {
        "iri": f"http://utilities.local/org/ORG_{index}",
        "rdf_types": ["Organization"],
        "org_id": f"ORG_{index}",
        "name": f"Org {index}",
        "name_norm": f"org {index}",
        "state": "TX",
        "owner_type": "local",
        "owner_type_code": "L",
        "government_unit_id": None,
        "sector": "water",
        "source_id": "src_w",
    }


def _system_row(system_id: str, sector: str, class_name: str) -> dict[str, object]:
    return {
        "iri": f"http://utilities.local/system/{system_id}",
        "rdf_types": ["UtilitySystem", class_name],
        "system_id": system_id,
        "sector": sector,
        "name": system_id,
        "status": "active",
        "system_type": "CWS",
        "primary_state": "TX",
        "population_served": 100,
        "service_connections": 40,
        "customers": None,
        "sales_mwh": None,
        "owner_org_id": "ORG_0",
        "operator_org_id": None,
        "in_federal_registry": True,
        "first_seen_release": "2026-Q4",
        "last_seen_release": "2026-Q4",
    }


def _area_row(index: int, authority: str) -> dict[str, object]:
    return {
        "iri": f"http://utilities.local/area/AREA_{index}",
        "rdf_types": ["ServiceArea"],
        "service_area_id": f"AREA_{index}",
        "system_id": "SYS_W1",
        "sector": "water",
        "zone_role": "active_retail_service",
        "source_id": "src_w",
        "authority": authority,
        "grain": "service_area",
        "source_vintage_date": dt.date(2025, 1, 1),
        "is_best": index == 0,
        "part_count": 1,
        "area_km2": 1.0,
        "footprint_verified": False,
        "licence": "public_domain",
        "boundary_representation": "polygon",
    }


def _write_parquet(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    types: dict[str, pa.DataType] = {}
    for name in fields:
        if name == "rdf_types":
            types[name] = pa.list_(pa.string())
        elif name in {"experimental", "is_served", "reviewed", "out_of_scope", "in_federal_registry", "is_best", "footprint_verified"}:
            types[name] = pa.bool_()
        elif name in {"confidence", "customers", "sales_mwh", "area_km2", "capacity_mw", "longitude", "latitude", "pop_share_of_county", "pop_share_of_system", "area_share"}:
            types[name] = pa.float64()
        elif name in {"population_served", "service_connections", "part_count", "unit_count", "pop20", "pop_in_area", "housing_in_area"}:
            types[name] = pa.int64()
        elif name in {"source_vintage_date", "as_of"}:
            types[name] = pa.date32()
        else:
            types[name] = pa.string()
    arrays = [pa.array([row.get(name) for row in rows], type=types[name]) for name in fields]
    pq.write_table(pa.Table.from_arrays(arrays, names=list(fields)), path)


def _local(uri: str) -> str:
    if "/ontology/" in uri:
        return uri.split("/ontology/", 1)[1]
    return uri.rstrip("/").rsplit("/", 1)[-1]
