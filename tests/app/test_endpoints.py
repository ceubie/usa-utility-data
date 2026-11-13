"""Endpoints that do not call a model."""

import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from app.backend.agent.projector import project_result
from app.backend.main import create_app
from app.backend.release_db import ReleaseDB
from app.backend.settings import get_settings
from app.backend.store import SparqlStore

pytestmark = [pytest.mark.requires_release, pytest.mark.requires_sparql]


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _expected_release_metrics(release_dir: Path) -> tuple[dict[str, int], int, int]:
    manifest = json.loads((release_dir / "graph" / "manifest.json").read_text(encoding="utf-8"))
    connection = duckdb.connect()
    try:
        water_row = connection.execute(
            "SELECT count(*)::BIGINT FROM read_parquet(?) WHERE sector = 'water'",
            [str(release_dir / "graph" / "nodes" / "utility_system.parquet")],
        ).fetchone()
        travis_row = connection.execute(
            "SELECT count(DISTINCT system_id)::BIGINT FROM read_parquet(?) WHERE county_geoid = '48453' AND sector = 'water'",
            [str(release_dir / "graph" / "edges" / "serves_county.parquet")],
        ).fetchone()
    finally:
        connection.close()
    assert water_row is not None and travis_row is not None
    return manifest["node_rows"], int(water_row[0]), int(travis_row[0])


def test_stats_search_scorecard_sparql_and_place(client: TestClient):
    settings = get_settings()
    node_rows, expected_water_systems, expected_travis_water = _expected_release_metrics(settings.release_dir)

    stats = client.get("/api/stats")
    assert stats.status_code == 200
    payload = stats.json()
    assert payload["release"] == settings.utilitydata_release
    classes = {item["name"]: item["count"] for item in payload["classes"]}
    assert classes["Organization"] == node_rows["organization"] > 0
    assert classes["WaterSystem"] == expected_water_systems > 0

    search = client.get("/api/search", params={"q": "KELLY LANE WCID 1", "state": "TX", "limit": 10})
    assert search.status_code == 200
    assert any("KELLY LANE" in str(row.get("label") or "").upper() for row in search.json()["rows"])

    scorecard = client.get("/api/coverage/scorecard", params={"state": "TX", "sector": "water"})
    assert scorecard.status_code == 200
    assert scorecard.json()["row_count"] >= 1

    query = """
    PREFIX ud: <http://utilities.local/ontology/>
    SELECT (COUNT(DISTINCT ?system) AS ?systems) WHERE {
      ?system a ud:WaterSystem ;
              ud:servesCounty <http://utilities.local/county/48453> .
    }
    """
    sparql = client.post("/api/sparql/query", json={"query": query})
    assert sparql.status_code == 200
    body = sparql.json()
    assert body["row_count"] == 1
    assert 0 < expected_travis_water < 120
    assert int(body["rows"][0]["systems"]["value"]) == expected_travis_water

    release = ReleaseDB(get_settings())
    try:
        places = release.locate_place("Austin", state="TX")
    finally:
        release.close()
    assert any(row["id"] == "4805000" for row in places)


def test_who_serves_uses_the_exact_polygon(client: TestClient):
    settings = get_settings()
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        point = connection.execute(
            """
            SELECT system_id,
                   ST_X(ST_PointOnSurface(geometry)) AS lon,
                   ST_Y(ST_PointOnSurface(geometry)) AS lat
            FROM read_parquet(?, union_by_name = true)
            WHERE is_best AND sector = 'water' AND geometry IS NOT NULL
            LIMIT 1
            """,
            [[
                str(settings.release_dir / "internal" / "territories_water.parquet"),
                str(settings.release_dir / "shareable" / "territories_water.parquet"),
            ]],
        ).fetchone()
    finally:
        connection.close()
    assert point is not None
    system_id, lon, lat = point
    response = client.get("/api/geo/who-serves", params={"lat": lat, "lon": lon, "sector": "water"})
    assert response.status_code == 200
    ids = {row["system_id"] for row in response.json()["systems"]}
    assert system_id in ids
    area_id = next(row["service_area_id"] for row in response.json()["systems"] if row["system_id"] == system_id)
    areas = client.get("/api/geo/service-areas", params={"service_area_id": area_id})
    assert areas.status_code == 200
    collection = areas.json()
    assert collection["type"] == "FeatureCollection"
    assert 1 <= len(collection["features"]) <= 300
    assert collection["features"][0]["geometry"]["type"]


def test_entity_expand_and_map_projection(client: TestClient):
    county = "http://utilities.local/county/48453"
    entity = client.get("/api/entity", params={"iri": county})
    assert entity.status_code == 200
    assert entity.json()["row_count"] >= 1

    expanded = client.get("/api/graph/expand", params={"iri": county, "limit": 40})
    assert expanded.status_code == 200
    rows = expanded.json()["rows"]
    assert any(row["predicate"]["value"].endswith("servesCounty") for row in rows)
    assert any(row["direction"]["value"] == "out" for row in rows)

    settings = get_settings()
    store = SparqlStore(settings.sparql_query_url, settings.query_timeout_s)
    try:
        projected = project_result(
            [{"county": {"kind": "iri", "value": county}}],
            store=store,
            base_iri=settings.graph_base_iri,
        )
    finally:
        store.close()
    assert projected["county_geoids"] == ["48453"]
    assert projected["dropped"] == 0
    assert projected["nodes"][0]["label"] == "Travis"


def test_guard_rejects_an_update_on_the_sparql_endpoint(client: TestClient):
    response = client.post("/api/sparql/query", json={"query": "INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }"})
    assert response.status_code == 400
    assert "INSERT" in response.json()["detail"]
