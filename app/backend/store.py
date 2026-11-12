"""The only module that talks to Fuseki."""

from __future__ import annotations

from typing import Any

import httpx

from app.backend.agent.query_guard import check

_CELL_TYPES = {"uri": "iri", "literal": "literal", "bnode": "bnode"}


class SparqlStore:
    """Read-only client for the local SPARQL query endpoint."""

    def __init__(self, url: str, timeout_s: float) -> None:
        if timeout_s < 1:
            raise ValueError("SPARQL timeout must be at least one second")
        self.url = url
        self.timeout_s = timeout_s
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)))

    def close(self) -> None:
        self._client.close()

    def select(self, query: str) -> list[dict[str, dict[str, str]]]:
        """Run a SELECT query and return rows that mark each value as an IRI or a literal."""
        payload = self._post(query)
        bindings = payload.get("results", {}).get("bindings", [])
        if not isinstance(bindings, list):
            raise ValueError("SPARQL response did not contain rows")
        return [_row(binding) for binding in bindings]

    def ask(self, query: str) -> bool:
        """Run an ASK query."""
        payload = self._post(query)
        if not isinstance(payload.get("boolean"), bool):
            raise ValueError("SPARQL ASK response did not contain a boolean")
        return bool(payload["boolean"])

    def count(self, pattern: str) -> int:
        """Count solutions of one graph pattern."""
        if not pattern or not pattern.strip():
            raise ValueError("SPARQL pattern is empty")
        decision = check(f"SELECT (COUNT(*) AS ?count) WHERE {{ {pattern} }}")
        if decision.error or not decision.query:
            raise ValueError(decision.error or "SPARQL pattern was rejected")
        rows = self.select(decision.query)
        if len(rows) != 1 or "count" not in rows[0]:
            raise ValueError("SPARQL count did not return one row")
        cell = rows[0]["count"]
        if cell.get("kind") != "literal":
            raise ValueError("SPARQL count was not a literal")
        return int(cell["value"])

    def guarded_select(self, query: str, *, base_iri: str, row_limit: int) -> tuple[str, list[dict[str, dict[str, str]]]]:
        """Guard a SELECT query and return the query that ran plus its rows."""
        decision = check(query, row_limit=row_limit, base_iri=base_iri)
        if decision.error or not decision.query:
            raise ValueError(decision.error or "SPARQL query was rejected")
        if decision.kind != "select":
            raise ValueError("Expected a SELECT query")
        return decision.query, self.select(decision.query)

    def describe(self, iri: str, *, base_iri: str, row_limit: int) -> tuple[str, list[dict[str, dict[str, str]]]]:
        """Return the predicates of one graph IRI."""
        query = "SELECT ?predicate ?value WHERE {\n  " + format_iri(iri, base_iri) + " ?predicate ?value .\n}\n"
        return self.guarded_select(query, base_iri=base_iri, row_limit=row_limit)

    def neighbors(self, iri: str, *, base_iri: str, row_limit: int) -> tuple[str, list[dict[str, dict[str, str]]]]:
        """Return IRIs one hop from an entity, from both directions."""
        bracket = format_iri(iri, base_iri)
        per_direction = max(1, int(row_limit) // 2)
        query = (
            "SELECT ?direction ?predicate ?other WHERE {\n"
            "  {\n"
            f'    SELECT ("out" AS ?direction) ?predicate ?other WHERE {{\n'
            f"      {bracket} ?predicate ?other .\n"
            "      FILTER(isIRI(?other))\n"
            f"    }} LIMIT {per_direction}\n"
            "  } UNION {\n"
            f'    SELECT ("in" AS ?direction) ?predicate ?other WHERE {{\n'
            f"      ?other ?predicate {bracket} .\n"
            "      FILTER(isIRI(?other))\n"
            f"    }} LIMIT {per_direction}\n"
            "  }\n"
            "}\n"
        )
        return self.guarded_select(query, base_iri=base_iri, row_limit=row_limit)

    def _post(self, query: str) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("SPARQL query is empty")
        try:
            response = self._client.post(
                self.url,
                content=query.encode("utf-8"),
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": "application/sparql-results+json",
                },
            )
        except httpx.HTTPError as exc:
            raise ValueError("SPARQL query service did not answer") from exc
        if response.status_code != 200:
            detail = " ".join(response.text.split())[:400]
            raise ValueError(f"SPARQL query failed with status {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("SPARQL response was not JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("SPARQL response was not an object")
        return payload


def format_iri(value: str, base_iri: str) -> str:
    """Return a bracketed IRI after rejecting anything that is not in this graph."""
    if not isinstance(value, str) or not valid_graph_iri(value, base_iri):
        raise ValueError("IRI is outside the graph")
    return f"<{value}>"


def valid_graph_iri(value: str, base_iri: str) -> bool:
    """Return whether an IRI is a safe entity or term under the graph base."""
    if not value.startswith(base_iri):
        return False
    rest = value[len(base_iri) :]
    if not rest or ".." in rest.split("/"):
        return False
    return all(char.isalnum() or char in "_./-" for char in rest)


def _row(binding: object) -> dict[str, dict[str, str]]:
    if not isinstance(binding, dict):
        raise ValueError("SPARQL row was not an object")
    parsed: dict[str, dict[str, str]] = {}
    for name, value in binding.items():
        parsed[str(name)] = _cell(name, value)
    return parsed


def _cell(name: object, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or "type" not in value or "value" not in value:
        raise ValueError(f"SPARQL binding {name} is incomplete")
    raw_type = str(value["type"])
    if raw_type not in _CELL_TYPES:
        raise ValueError(f"SPARQL binding {name} has an unknown type")
    cell = {"kind": _CELL_TYPES[raw_type], "value": str(value["value"])}
    datatype = value.get("datatype")
    if isinstance(datatype, str) and datatype:
        cell["datatype"] = datatype
    language = value.get("xml:lang")
    if isinstance(language, str) and language:
        cell["language"] = language
    return cell
