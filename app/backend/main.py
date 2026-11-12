"""Local FastAPI application. It binds to the loopback interface only."""

from __future__ import annotations

import hmac
import json
import math
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.backend.agent.orchestrator import append_log, orchestrate, sse
from app.backend.agent.query_guard import check
from app.backend.agent.result_store import ResultStore
from app.backend.agent.schema_card import build_schema_card
from app.backend.agent.tools import ToolContext
from app.backend.release_db import ReleaseDB
from app.backend.settings import Settings, get_settings
from app.backend.store import SparqlStore
from utilitydata.core.config import DISPLAY_SIMPLIFY_DEGREES

_HOST = "127.0.0.1"
_PORT = 8000


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = get_settings()
    release = ReleaseDB(settings)
    store = SparqlStore(settings.sparql_query_url, settings.query_timeout_s)
    app.state.settings = settings
    app.state.release = release
    app.state.store = store
    try:
        app.state.card = build_schema_card(settings)
        yield
    finally:
        store.close()
        release.close()


def create_app() -> FastAPI:
    """Create the API. Serving it is bound to 127.0.0.1 in run()."""
    app = FastAPI(title="Utility data", lifespan=_lifespan)
    app.middleware("http")(_proxy_identity)
    app.get("/api/stats")(_stats)
    app.get("/api/search")(_search)
    app.get("/api/entity")(_entity)
    app.get("/api/graph/expand")(_expand)
    app.get("/api/geo/service-areas")(_service_areas)
    app.get("/api/geo/who-serves")(_who_serves)
    app.get("/api/coverage/scorecard")(_scorecard)
    app.post("/api/sparql/query")(_sparql)
    app.post("/api/ask")(_ask)
    return app


class SparqlRequest(BaseModel):
    query: str = Field(min_length=1, max_length=24_000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)


async def _proxy_identity(request: Request, call_next):
    """When auth is required, reject a request that lacks the proxy identity and secret."""
    settings = get_settings()
    if settings.require_auth:
        secret = (settings.proxy_shared_secret or "").encode()
        presented = (request.headers.get("x-proxy-secret") or "").encode()
        identity = (request.headers.get("x-forwarded-user") or "").strip()
        if not secret or not identity or not hmac.compare_digest(presented, secret):
            return JSONResponse(status_code=401, content={"detail": "proxy identity required"})
    return await call_next(request)


def run() -> None:
    """Serve the API on the loopback interface."""
    uvicorn.run(app, host=_HOST, port=_PORT)


def _stats(request: Request) -> dict:
    card = request.app.state.card
    settings: Settings = request.app.state.settings
    return {
        "release": settings.utilitydata_release,
        "base_iri": settings.graph_base_iri,
        "llm_configured": settings.llm_configured,
        "classes": [{"name": item.name, "label": item.label, "count": item.count} for item in card.classes],
        "links": [{"name": item.name, "label": item.label, "count": item.count} for item in card.links],
    }


def _search(
    request: Request,
    q: str,
    kind: str | None = None,
    state: str | None = None,
    limit: int = 25,
) -> dict:
    rows = request.app.state.release.search_entities(q, kind=kind, state=state, limit=limit)
    return {"rows": rows, "row_count": len(rows)}


def _entity(request: Request, iri: str) -> dict:
    settings: Settings = request.app.state.settings
    try:
        _query, rows = request.app.state.store.describe(
            iri,
            base_iri=settings.graph_base_iri,
            row_limit=settings.row_limit,
        )
    except ValueError as exc:
        raise _sparql_error(exc, settings) from exc
    return {"iri": iri, "rows": rows, "row_count": len(rows)}


def _expand(request: Request, iri: str, limit: int = 50) -> dict:
    settings: Settings = request.app.state.settings
    capped = max(1, min(limit, 200))
    try:
        _query, rows = request.app.state.store.neighbors(
            iri,
            base_iri=settings.graph_base_iri,
            row_limit=capped,
        )
    except ValueError as exc:
        raise _sparql_error(exc, settings) from exc
    return {"iri": iri, "rows": rows, "row_count": len(rows)}


def _service_areas(
    request: Request,
    service_area_id: Annotated[list[str] | None, Query()] = None,
    bbox: str | None = None,
    sector: str | None = None,
    simplify_degrees: float = 0.01,
    limit: int = 300,
) -> dict:
    settings: Settings = request.app.state.settings
    if not any(math.isclose(simplify_degrees, float(item), rel_tol=0.0, abs_tol=1e-9) for item in DISPLAY_SIMPLIFY_DEGREES):
        raise HTTPException(status_code=400, detail="simplify_degrees is not a display tolerance")
    box = _bbox(bbox) if bbox else None
    try:
        rows, truncated = request.app.state.release.service_areas(
            ids=service_area_id or None,
            bbox=box,
            sector=sector,
            simplify_degrees=simplify_degrees,
            limit=min(limit, 300),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public(exc, settings)) from exc
    features = []
    for row in rows:
        geojson = row.get("geojson")
        if not isinstance(geojson, str):
            continue
        properties = {key: value for key, value in row.items() if key != "geojson"}
        features.append({"type": "Feature", "geometry": json.loads(geojson), "properties": properties})
    return {"type": "FeatureCollection", "features": features, "truncated": truncated}


def _who_serves(request: Request, lat: float, lon: float, sector: str) -> dict:
    settings: Settings = request.app.state.settings
    try:
        rows = request.app.state.release.who_serves(lat, lon, sector)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public(exc, settings)) from exc
    return {"count": len(rows), "systems": rows}


def _scorecard(request: Request, state: str | None = None, sector: str | None = None) -> dict:
    rows = request.app.state.release.scorecard(state=state, sector=sector)
    return {"rows": rows, "row_count": len(rows)}


def _sparql(body: SparqlRequest, request: Request) -> dict:
    settings: Settings = request.app.state.settings
    decision = check(body.query, row_limit=settings.row_limit, base_iri=settings.graph_base_iri)
    if decision.error or not decision.query:
        raise HTTPException(status_code=400, detail=decision.error or "SPARQL query was rejected.")
    store: SparqlStore = request.app.state.store
    try:
        if decision.kind == "ask":
            return {"kind": "ask", "boolean": store.ask(decision.query)}
        rows = store.select(decision.query)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=_public(exc, settings)) from exc
    return {"kind": "select", "row_count": len(rows), "rows": rows}


def _ask(body: AskRequest, request: Request) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    missing = settings.missing_llm()
    question = body.question

    def events():
        results = ResultStore()
        try:
            if missing:
                message = "Ask is not configured. Missing " + ", ".join(missing) + "."
                yield sse("error", {"message": message, "missing": missing})
                append_log(
                    {
                        "question": question,
                        "tool_calls": [],
                        "queries": [],
                        "row_counts": [],
                        "timings": [],
                        "answer": "",
                        "error": message,
                        "missing": missing,
                    },
                    settings,
                )
                return
            context = ToolContext(
                release=request.app.state.release,
                store=request.app.state.store,
                results=results,
                settings=settings,
                card=request.app.state.card,
            )
            yield from orchestrate(question, context)
        finally:
            del results

    return StreamingResponse(events(), media_type="text/event-stream")


def _bbox(value: str) -> tuple[float, float, float, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be minLon,minLat,maxLon,maxLat")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bbox must be four numbers") from exc
    if not -180.0 <= min_lon <= max_lon <= 180.0 or not -90.0 <= min_lat <= max_lat <= 90.0:
        raise HTTPException(status_code=400, detail="bbox is out of range")
    return min_lon, min_lat, max_lon, max_lat


def _sparql_error(exc: ValueError, settings: Settings) -> HTTPException:
    text = str(exc).lower()
    status = 400 if "outside the graph" in text or "rejected" in text or "not allowed" in text else 503
    return HTTPException(status_code=status, detail=_public(exc, settings))


def _public(exc: Exception, settings: Settings) -> str:
    text = " ".join(str(exc).split()) or "Request failed."
    text = text.replace(str(settings.data_home), "data")
    secret = (settings.azure_openai_api_key or "").strip()
    if len(secret) >= 8:
        text = text.replace(secret, "[redacted]")
    return text[:500]


app = create_app()


if __name__ == "__main__":
    run()
