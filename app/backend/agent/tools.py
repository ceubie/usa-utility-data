"""One function and one JSON schema for each Ask tool."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from app.backend.agent.projector import project_result
from app.backend.agent.query_guard import check
from app.backend.agent.result_store import ResultStore
from app.backend.agent.schema_card import SchemaCard
from app.backend.release_db import ReleaseDB
from app.backend.settings import Settings
from app.backend.store import SparqlStore, format_iri

_LOG = logging.getLogger(__name__)

_PREVIEW_ROWS = 25
_SEARCH_COLUMNS = ["iri", "id", "kind", "label", "state", "sector", "status", "match"]
_PLACE_COLUMNS = ["kind", "id", "iri", "name", "namelsad", "state_fips", "state_usps"]
_SERVE_COLUMNS = [
    "iri",
    "service_area_iri",
    "service_area_id",
    "system_id",
    "name",
    "sector",
    "status",
    "primary_state",
    "authority",
    "source_vintage_date",
    "boundary_representation",
    "zone_role",
    "licence",
    "grain",
]
_NUMERIC_DATATYPES = {"integer", "int", "long", "short", "byte", "double", "float", "decimal"}


@dataclass
class ToolContext:
    """Services available to tools for one request."""

    release: ReleaseDB
    store: SparqlStore
    results: ResultStore
    settings: Settings
    card: SchemaCard


@dataclass
class ToolOutcome:
    """A tool result for the model and, for display tools, a payload for the client."""

    result: dict
    display: dict | None = None
    query: str | None = None
    row_count: int | None = None
    elapsed_s: float | None = None


def tool_schemas() -> list[dict]:
    """Return the JSON schema of every tool."""
    return [
        _function(
            "search_entities",
            "Resolve a utility, organization, facility, place, county, or state by name or identifier. "
            "Call this before writing a SPARQL query that needs an IRI.",
            {
                "query": {"type": "string", "description": "Name, alternate name, or identifier."},
                "kind": {
                    "type": "string",
                    "enum": ["system", "organization", "facility", "county", "place", "state"],
                    "description": "Optional entity kind.",
                },
                "state": {"type": "string", "description": "Optional USPS code, FIPS code, or state name."},
                "limit": {"type": "integer", "description": "Maximum rows, at most 100."},
            },
            ["query"],
        ),
        _function(
            "locate_place",
            "Resolve a census place, county, or state name to its GEOID and IRI.",
            {
                "name": {"type": "string", "description": "Place, county, or state name."},
                "state": {"type": "string", "description": "Optional USPS code, FIPS code, or state name."},
                "limit": {"type": "integer", "description": "Maximum rows, at most 100."},
            },
            ["name"],
        ),
        _function(
            "who_serves_point",
            "Exact point-in-polygon test on best service areas. Returns authority, vintage, and boundary representation.",
            {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "sector": {"type": "string", "description": "Sector such as water, electric, wastewater, or natural_gas."},
            },
            ["lat", "lon", "sector"],
        ),
        _function(
            "describe_entity",
            "Fetch the predicates of one IRI returned by a previous tool.",
            {"iri": {"type": "string", "description": "An IRI returned by a previous tool."}},
            ["iri"],
        ),
        _function(
            "run_sparql",
            "Run one guarded SELECT or ASK query. Use row_count and values inside the rows. "
            "A row preview can be shorter than row_count. When row_count equals the limit, the result may be truncated.",
            {"query": {"type": "string", "description": "A SELECT or ASK query. Do not guess IRIs."}},
            ["query"],
        ),
        _display_schema(
            "show_on_graph",
            "Show the entities in a stored result as a graph. Accepts only a result_id.",
        ),
        _display_schema(
            "show_on_map",
            "Show service areas and counties from a stored result on the map. Accepts only a result_id. "
            "The client fetches the shapes.",
        ),
        _display_schema(
            "show_chart",
            "Chart a stored result. Accepts only a result_id.",
        ),
    ]


def run_tool(name: str, arguments: object, ctx: ToolContext) -> ToolOutcome:
    """Run one tool and record how long it took."""
    started = time.perf_counter()
    try:
        implementation = _IMPLEMENTATIONS.get(name)
        if implementation is None:
            outcome = ToolOutcome({"error": "Unknown tool."})
        else:
            parsed = _parse_arguments(arguments)
            outcome = implementation(parsed, ctx)
    except json.JSONDecodeError:
        outcome = ToolOutcome({"error": "Tool arguments are not JSON."})
    except Exception as exc:  # noqa: BLE001 - the model receives the error and may retry with other arguments
        _LOG.exception("Tool %s failed", name)
        outcome = ToolOutcome({"error": _safe_error(exc, ctx.settings)})
    outcome.elapsed_s = round(time.perf_counter() - started, 4)
    return outcome


def search_entities(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolOutcome({"error": "query is required."})
    kind = arguments.get("kind")
    state = arguments.get("state")
    rows = ctx.release.search_entities(
        query,
        kind=kind if isinstance(kind, str) else None,
        state=state if isinstance(state, str) else None,
        limit=_optional_limit(arguments.get("limit"), 25, 100),
    )
    return _stored(ctx, _SEARCH_COLUMNS, rows)


def locate_place(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        return ToolOutcome({"error": "name is required."})
    state = arguments.get("state")
    rows = ctx.release.locate_place(
        name,
        state=state if isinstance(state, str) else None,
        limit=_optional_limit(arguments.get("limit"), 25, 100),
    )
    return _stored(ctx, _PLACE_COLUMNS, rows)


def who_serves_point(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    sector = arguments.get("sector")
    if not isinstance(sector, str) or not sector.strip():
        return ToolOutcome({"error": "sector is required."})
    rows = ctx.release.who_serves(_number(arguments.get("lat"), "lat"), _number(arguments.get("lon"), "lon"), sector)
    return _stored(ctx, _SERVE_COLUMNS, rows)


def describe_entity(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    iri = arguments.get("iri")
    if not isinstance(iri, str) or not iri.strip():
        return ToolOutcome({"error": "iri is required."})
    format_iri(iri, ctx.settings.graph_base_iri)
    query, rows = ctx.store.describe(iri, base_iri=ctx.settings.graph_base_iri, row_limit=ctx.settings.row_limit)
    columns = _columns(rows)
    result_id = ctx.results.put(columns, rows)
    return ToolOutcome(
        {
            "result_id": result_id,
            "iri": iri,
            "row_count": len(rows),
            "columns": columns,
            "rows": rows[:_PREVIEW_ROWS],
        },
        query=query,
        row_count=len(rows),
    )


def run_sparql(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolOutcome({"error": "query is required."})
    decision = check(query, row_limit=ctx.settings.row_limit, base_iri=ctx.settings.graph_base_iri)
    if decision.error or not decision.query:
        return ToolOutcome({"error": decision.error or "SPARQL query was rejected."})
    if decision.kind == "ask":
        value = ctx.store.ask(decision.query)
        result_id = ctx.results.put(["boolean"], [{"boolean": value}])
        return ToolOutcome(
            {"result_id": result_id, "kind": "ask", "boolean": value, "row_count": 1},
            query=decision.query,
            row_count=1,
        )
    rows = ctx.store.select(decision.query)
    columns = _columns(rows)
    result_id = ctx.results.put(columns, rows)
    return ToolOutcome(
        {
            "result_id": result_id,
            "kind": "select",
            "row_count": len(rows),
            "truncated": len(rows) >= ctx.settings.row_limit,
            "columns": columns,
            "rows": rows[:_PREVIEW_ROWS],
        },
        query=decision.query,
        row_count=len(rows),
    )


def show_on_graph(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    stored, error = _stored_result(arguments, ctx)
    if error is not None or stored is None:
        return ToolOutcome({"error": error or "Unknown result_id."})
    projected = project_result(stored.rows, store=ctx.store, base_iri=ctx.settings.graph_base_iri)
    display = {
        "kind": "graph",
        "nodes": projected["nodes"],
        "links": projected["links"],
        "dropped": projected["dropped"],
    }
    return ToolOutcome(
        {
            "result_id": arguments["result_id"],
            "nodes": len(projected["nodes"]),
            "links": len(projected["links"]),
            "dropped": projected["dropped"],
        },
        display=display,
    )


def show_on_map(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    stored, error = _stored_result(arguments, ctx)
    if error is not None or stored is None:
        return ToolOutcome({"error": error or "Unknown result_id."})
    projected = project_result(stored.rows, store=ctx.store, base_iri=ctx.settings.graph_base_iri)
    display = {
        "kind": "map",
        "service_area_ids": projected["service_area_ids"],
        "county_geoids": projected["county_geoids"],
        "dropped": projected["dropped"],
    }
    return ToolOutcome(
        {
            "result_id": arguments["result_id"],
            "service_area_ids": len(projected["service_area_ids"]),
            "county_geoids": len(projected["county_geoids"]),
            "dropped": projected["dropped"],
        },
        display=display,
    )


def show_chart(arguments: dict, ctx: ToolContext) -> ToolOutcome:
    stored, error = _stored_result(arguments, ctx)
    if error is not None or stored is None:
        return ToolOutcome({"error": error or "Unknown result_id."})
    display = {
        "kind": "chart",
        "columns": stored.columns,
        "rows": stored.rows,
        "row_count": len(stored.rows),
        "numeric_columns": _numeric_columns(stored.columns, stored.rows),
    }
    return ToolOutcome(
        {"result_id": arguments["result_id"], "row_count": len(stored.rows), "columns": stored.columns},
        display=display,
    )


_IMPLEMENTATIONS = {
    "search_entities": search_entities,
    "locate_place": locate_place,
    "who_serves_point": who_serves_point,
    "describe_entity": describe_entity,
    "run_sparql": run_sparql,
    "show_on_graph": show_on_graph,
    "show_on_map": show_on_map,
    "show_chart": show_chart,
}


def _stored(ctx: ToolContext, columns: list[str], rows: list[dict]) -> ToolOutcome:
    shaped = [{column: row.get(column) for column in columns} for row in rows]
    result_id = ctx.results.put(columns, shaped)
    return ToolOutcome(
        {
            "result_id": result_id,
            "row_count": len(shaped),
            "columns": columns,
            "rows": shaped[:_PREVIEW_ROWS],
        },
        row_count=len(shaped),
    )


def _stored_result(arguments: dict, ctx: ToolContext):
    result_id, error = _only_result_id(arguments)
    if error or result_id is None:
        return None, error or "result_id is required."
    stored = ctx.results.get(result_id)
    if stored is None:
        return None, "Unknown result_id."
    return stored, None


def _only_result_id(arguments: dict) -> tuple[str | None, str | None]:
    if not isinstance(arguments, dict) or set(arguments) != {"result_id"}:
        return None, "Display tools accept only a result_id."
    result_id = arguments.get("result_id")
    if not isinstance(result_id, str) or not result_id.strip():
        return None, "result_id is required."
    return result_id, None


def _parse_arguments(arguments: object) -> dict:
    if isinstance(arguments, str):
        parsed = json.loads(arguments or "{}")
    else:
        parsed = arguments
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be an object.")
    return parsed


def _optional_limit(value: object, default: int, ceiling: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _columns(rows: list[dict]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _numeric_columns(columns: list[str], rows: list[dict]) -> list[str]:
    numeric: list[str] = []
    for column in columns:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        if values and all(_is_numeric(value) for value in values):
            numeric.append(column)
    return numeric


def _is_numeric(value: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict) and value.get("kind") == "literal":
        datatype = str(value.get("datatype") or "").rsplit("#", 1)[-1]
        if datatype in _NUMERIC_DATATYPES:
            return True
    return False


def _safe_error(exc: Exception, settings: Settings) -> str:
    text = " ".join(str(exc).split()) or "The tool failed."
    text = text.replace(str(settings.data_home), "data")
    secret = (settings.azure_openai_api_key or "").strip()
    if len(secret) >= 8:
        text = text.replace(secret, "[redacted]")
    return text[:500]


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _display_schema(name: str, description: str) -> dict:
    return _function(
        name,
        description,
        {"result_id": {"type": "string", "description": "The result_id returned by a previous tool."}},
        ["result_id"],
    )
