"""Markers for tests that read a built release or a running SPARQL store.

A clean checkout has neither, so those tests skip with the reason instead of failing.
"""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app.backend.settings import Settings

_RELEASE_MARKER = "requires_release"
_SPARQL_MARKER = "requires_sparql"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", f"{_RELEASE_MARKER}: needs the built release graph tables")
    config.addinivalue_line("markers", f"{_SPARQL_MARKER}: needs the SPARQL store loaded with the release")


def _release_missing(settings: Settings) -> str | None:
    nodes = settings.release_dir / "graph" / "nodes"
    if not nodes.is_dir():
        return f"release graph tables are not built: {nodes}"
    return None


def _sparql_missing(settings: Settings) -> str | None:
    url = f"{settings.sparql_query_url}?{urllib.parse.urlencode({'query': 'ASK { ?s ?p ?o }'})}"
    request = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or not bool(payload.get("boolean")):
            return f"SPARQL store at {settings.sparql_query_url} is empty"
        return None
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, json.JSONDecodeError, ValueError) as exc:
        return f"SPARQL store is not reachable at {settings.sparql_query_url}: {exc}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    release_items = [item for item in items if item.get_closest_marker(_RELEASE_MARKER)]
    sparql_items = [item for item in items if item.get_closest_marker(_SPARQL_MARKER)]
    if not release_items and not sparql_items:
        return
    settings = Settings()
    release_reason = _release_missing(settings)
    sparql_reason = (release_reason or _sparql_missing(settings)) if sparql_items else None
    for item in release_items:
        if release_reason:
            item.add_marker(pytest.mark.skip(reason=release_reason))
    for item in sparql_items:
        if sparql_reason:
            item.add_marker(pytest.mark.skip(reason=sparql_reason))
