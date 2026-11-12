"""QLever stays off the default path until an index and a pinned image exist."""

from pathlib import Path

from utilitydata.graph.qlever import load_and_serve, qlever_query_url
from utilitydata.graph.store import query_url


def test_fuseki_remains_the_default_query_url():
    assert query_url().startswith("http://127.0.0.1:3030/utility/query")
    assert query_url(engine="qlever") == "http://127.0.0.1:7019"
    assert qlever_query_url() == query_url(engine="qlever")


def test_missing_index_does_not_start_a_server(tmp_path: Path):
    graph = tmp_path / "releases" / "2026Q4.2" / "graph"
    graph.mkdir(parents=True)
    nt_path = graph / "graph.nt"
    nt_path.write_text("", encoding="utf-8")
    status = load_and_serve(tmp_path, "2026Q4.2", nt_path)
    assert status.started is False
    assert status.loaded is False
    assert status.query_url.startswith("http://127.0.0.1:")
