"""Example queries against Fuseki, with a DuckDB fallback when Fuseki is down."""

from __future__ import annotations

import duckdb

from app.backend.agent.prompts import example_files, example_question
from app.backend.agent.query_guard import check
from app.backend.settings import get_settings
from app.backend.store import SparqlStore

_EDGE_FALLBACK = {
    "travis_water_systems.rq": """
        SELECT system_id FROM read_parquet(?)
        WHERE county_geoid = '48453' AND sector = 'water'
        LIMIT 5
    """,
    "travis_water_count.rq": """
        SELECT count(*) AS systems FROM read_parquet(?)
        WHERE county_geoid = '48453' AND sector = 'water'
    """,
    "electric_serves_county.rq": """
        SELECT system_id FROM read_parquet(?)
        WHERE sector = 'electric'
        LIMIT 5
    """,
    "owns_system.rq": "SELECT system_id FROM read_parquet(?) LIMIT 5",
    "has_service_area.rq": "SELECT service_area_id FROM read_parquet(?) LIMIT 5",
}
_EDGE_FILE = {
    "travis_water_systems.rq": "serves_county.parquet",
    "travis_water_count.rq": "serves_county.parquet",
    "electric_serves_county.rq": "serves_county.parquet",
    "owns_system.rq": "owns_system.parquet",
    "has_service_area.rq": "has_service_area.parquet",
}


def test_every_example_has_a_question_and_returns_a_row():
    settings = get_settings()
    files = example_files()
    assert len(files) >= 12
    store = SparqlStore(settings.sparql_query_url, settings.query_timeout_s)
    try:
        fuseki = _fuseki_up(store)
        guard_failures: list[str] = []
        empty: list[str] = []
        not_run: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            assert text.startswith("#")
            assert example_question(text)
            decision = check(text, row_limit=settings.row_limit, base_iri=settings.graph_base_iri)
            if decision.error or not decision.query or decision.kind != "select":
                guard_failures.append(f"{path.name}: {decision.error}")
                continue
            if fuseki:
                try:
                    rows = store.select(decision.query)
                except ValueError as exc:
                    empty.append(f"{path.name}: {exc}")
                    continue
                if not rows:
                    empty.append(path.name)
            else:
                rows = _duckdb_rows(path.name, settings.release_dir)
                if rows is None:
                    not_run.append(path.name)
                elif not rows:
                    empty.append(path.name)
        assert guard_failures == []
        if fuseki:
            assert empty == []
            pattern = "?system a ud:WaterSystem ; ud:servesCounty <http://utilities.local/county/48453>"
            assert store.count(pattern) == 84
        else:
            message = "Fuseki is down. Examples not run against DuckDB: " + ", ".join(not_run)
            print(message)
            assert empty == [], message
    finally:
        store.close()


def _fuseki_up(store: SparqlStore) -> bool:
    try:
        return store.ask("ASK { <http://utilities.local/county/48453> ?p ?o }")
    except ValueError:
        return False


def _duckdb_rows(name: str, release) -> list | None:
    filename = _EDGE_FILE.get(name)
    sql = _EDGE_FALLBACK.get(name)
    if filename is None or sql is None:
        return None
    path = release / "graph" / "edges" / filename
    if not path.is_file():
        return None
    connection = duckdb.connect()
    try:
        return connection.execute(sql, [str(path)]).fetchall()
    finally:
        connection.close()
