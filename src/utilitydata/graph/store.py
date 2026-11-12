"""The only module that queries Fuseki. It posts SELECT and ASK to the query service."""

from __future__ import annotations

from typing import Any

import requests

from utilitydata.core.config import (
    GRAPH_BASE_IRI,
    GRAPH_QLEVER_PORT,
    GRAPH_QUERY_HOST,
    GRAPH_QUERY_PORT,
    GRAPH_QUERY_TIMEOUT_S,
)
from utilitydata.gold.schema import TRAVIS_COUNTY_GEOID
from utilitydata.graph.literals import ontology_iri, require_base
from utilitydata.graph.qlever import qlever_query_url

QUERY_DATASET = "utility"
QUERY_ENDPOINT = "query"


def query_url(
    host: str = GRAPH_QUERY_HOST,
    port: int = GRAPH_QUERY_PORT,
    *,
    engine: str = "fuseki",
) -> str:
    """Return the local query URL for the selected engine. Fuseki is the default."""
    if engine == "qlever":
        return qlever_query_url(host, GRAPH_QLEVER_PORT if port == GRAPH_QUERY_PORT else port)
    if engine != "fuseki":
        raise ValueError(f"Unknown graph engine: {engine}")
    if host != "127.0.0.1":
        raise ValueError("SPARQL query host must be the loopback interface")
    if port < 1 or port > 65535:
        raise ValueError("SPARQL query port is invalid")
    return f"http://{host}:{port}/{QUERY_DATASET}/{QUERY_ENDPOINT}"


class SparqlStore:
    """Read-only SPARQL client for the local Fuseki query service."""

    def __init__(self, url: str | None = None, *, timeout_s: int = GRAPH_QUERY_TIMEOUT_S) -> None:
        self.url = url if url is not None else query_url()
        if not self.url.startswith("http://127.0.0.1:") and not self.url.startswith("http://localhost:"):
            raise ValueError("SPARQL query URL must use the local query service")
        if timeout_s < 1:
            raise ValueError("SPARQL timeout must be at least one second")
        self.timeout_s = timeout_s

    def select(self, query: str) -> list[dict[str, dict[str, str]]]:
        """Run a SELECT query and return rows that mark each value as an IRI or a literal."""
        payload = self._post(query, "application/sparql-results+json")
        bindings = payload.get("results", {}).get("bindings", [])
        if not isinstance(bindings, list):
            raise TypeError("SPARQL response did not contain rows")
        return [_binding(row) for row in bindings]

    def ask(self, query: str) -> bool:
        """Run an ASK query."""
        payload = self._post(query, "application/sparql-results+json")
        if not isinstance(payload.get("boolean"), bool):
            raise TypeError("SPARQL ASK response did not contain a boolean")
        return bool(payload["boolean"])

    def _post(self, query: str, accept: str) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("SPARQL query is empty")
        try:
            response = requests.post(
                self.url,
                data=query.encode("utf-8"),
                headers={"Content-Type": "application/sparql-query", "Accept": accept},
                timeout=self.timeout_s + 5,
            )
        except requests.RequestException as exc:
            raise ValueError(f"SPARQL query service did not answer: {exc}") from exc
        if response.status_code != 200:
            detail = " ".join(response.text.split())[:400]
            raise ValueError(f"SPARQL query failed with status {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("SPARQL response was not JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("SPARQL response was not an object")
        return payload


def travis_water_query(base: str = GRAPH_BASE_IRI) -> str:
    """SPARQL for water systems that serve Travis County."""
    checked = require_base(base)
    prefix = ontology_iri(checked)
    county = f"{checked}county/{TRAVIS_COUNTY_GEOID}"
    return (
        f"PREFIX ud: <{prefix}>\n"
        "SELECT ?system WHERE {\n"
        "  ?system a ud:WaterSystem .\n"
        f"  ?system ud:servesCounty <{county}> .\n"
        "}\n"
    )


def system_ids_from_bindings(rows: list[dict[str, dict[str, str]]], base: str = GRAPH_BASE_IRI) -> set[str]:
    """Return system ids from SELECT bindings."""
    prefix = f"{require_base(base)}system/"
    found: set[str] = set()
    for row in rows:
        binding = row.get("system")
        if binding is None or binding.get("type") != "uri":
            raise ValueError("SPARQL row did not return a system IRI")
        value = binding.get("value", "")
        if not value.startswith(prefix):
            raise ValueError("SPARQL system IRI is outside the graph base")
        found.add(value[len(prefix):])
    return found


def _binding(row: object) -> dict[str, dict[str, str]]:
    if not isinstance(row, dict):
        raise TypeError("SPARQL row was not an object")
    parsed: dict[str, dict[str, str]] = {}
    for name, value in row.items():
        if not isinstance(value, dict) or "type" not in value or "value" not in value:
            raise ValueError(f"SPARQL binding {name} is incomplete")
        kind = str(value["type"])
        if kind not in {"uri", "literal", "bnode"}:
            raise ValueError(f"SPARQL binding {name} has an unknown type")
        parsed[str(name)] = {"type": kind, "value": str(value["value"])}
    return parsed
