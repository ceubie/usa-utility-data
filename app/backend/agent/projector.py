"""Turn stored rows into a graph or a map reference."""

from __future__ import annotations

from app.backend.agent.prefixes import prefix_block
from app.backend.store import SparqlStore, format_iri, valid_graph_iri

_NODE_CAP = 150
_LABEL_LIMIT = 5000


def project_result(rows: list[dict], *, store: SparqlStore, base_iri: str) -> dict[str, object]:
    """Collect IRIs from the earliest rows and describe them in two queries."""
    kept, dropped, kept_rows = _cap_rows(rows, base_iri)
    nodes = _labels(store, kept, base_iri) if kept else []
    links = _links(store, kept, base_iri) if len(kept) > 1 else []
    areas, counties = _map_ids(store, kept, kept_rows, base_iri)
    return {
        "nodes": nodes,
        "links": links,
        "dropped": dropped,
        "service_area_ids": areas,
        "county_geoids": counties,
    }


def _cap_rows(rows: list[dict], base_iri: str) -> tuple[list[str], int, list[dict]]:
    seen: list[str] = []
    seen_set: set[str] = set()
    dropped: set[str] = set()
    kept_rows: list[dict] = []
    capped = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        fresh = [iri for iri in _iris(row, base_iri) if iri not in seen_set and iri not in dropped]
        if capped:
            dropped.update(fresh)
            continue
        room = _NODE_CAP - len(seen)
        if len(fresh) > room:
            seen.extend(fresh[:room])
            seen_set.update(fresh[:room])
            dropped.update(fresh[room:])
            capped = True
            if fresh[:room]:
                kept_rows.append(row)
            continue
        seen.extend(fresh)
        seen_set.update(fresh)
        kept_rows.append(row)
        if len(seen) >= _NODE_CAP:
            capped = True
    return seen, len(dropped), kept_rows


def _iris(row: dict, base_iri: str) -> list[str]:
    found: list[str] = []
    for value in row.values():
        _collect(value, base_iri, found)
    unique: list[str] = []
    seen: set[str] = set()
    for iri in found:
        if iri not in seen:
            seen.add(iri)
            unique.append(iri)
    return unique


def _collect(value: object, base_iri: str, found: list[str]) -> None:
    if isinstance(value, str) and valid_graph_iri(value, base_iri):
        found.append(value)
        return
    if isinstance(value, dict):
        if value.get("kind") == "iri" and isinstance(value.get("value"), str) and valid_graph_iri(value["value"], base_iri):
            found.append(value["value"])
            return
        for item in value.values():
            _collect(item, base_iri, found)
        return
    if isinstance(value, list):
        for item in value:
            _collect(item, base_iri, found)


def _labels(store: SparqlStore, iris: list[str], base_iri: str) -> list[dict[str, str]]:
    values = " ".join(format_iri(iri, base_iri) for iri in iris)
    query = f"""{prefix_block(base_iri)}
SELECT ?iri ?label ?type ?primaryState ?usps ?stateCode WHERE {{
  VALUES ?iri {{ {values} }}
  OPTIONAL {{ ?iri ud:name ?label }}
  OPTIONAL {{ ?iri a ?type }}
  OPTIONAL {{ ?iri ud:primary_state ?primaryState }}
  OPTIONAL {{ ?iri ud:usps ?usps }}
  OPTIONAL {{ ?iri ud:state ?stateCode }}
}}
LIMIT {_LABEL_LIMIT}
"""
    grouped = {
        iri: {"label": "", "types": [], "primary": "", "usps": "", "fips": ""}
        for iri in iris
    }
    for row in store.select(query):
        iri = _value(row.get("iri"))
        if iri not in grouped:
            continue
        item = grouped[iri]
        label = _value(row.get("label"))
        if label and not item["label"]:
            item["label"] = label
        type_iri = _value(row.get("type"))
        if type_iri and "/ontology/" in type_iri:
            local = type_iri.split("/ontology/", 1)[1]
            if local not in item["types"]:
                item["types"].append(local)
        if not item["primary"]:
            item["primary"] = _value(row.get("primaryState")) or ""
        if not item["usps"]:
            item["usps"] = _value(row.get("usps")) or ""
        if not item["fips"]:
            item["fips"] = _value(row.get("stateCode")) or ""
    nodes = []
    for iri in iris:
        item = grouped[iri]
        specific = sorted(name for name in item["types"] if name != "UtilitySystem")
        kind = specific[0] if specific else (item["types"][0] if item["types"] else "")
        state = item["primary"] or item["usps"] or item["fips"]
        nodes.append({
            "iri": iri,
            "label": item["label"] or iri.removeprefix(base_iri).rstrip("/").rsplit("/", 1)[-1],
            "kind": kind,
            "state": state,
        })
    return nodes


def _links(store: SparqlStore, iris: list[str], base_iri: str) -> list[dict[str, str]]:
    values = " ".join(format_iri(iri, base_iri) for iri in iris)
    query = f"""{prefix_block(base_iri)}
SELECT ?subject ?predicate ?object WHERE {{
  VALUES ?subject {{ {values} }}
  VALUES ?object {{ {values} }}
  ?subject ?predicate ?object .
}}
LIMIT {_LABEL_LIMIT}
"""
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in store.select(query):
        subject = _value(row.get("subject"))
        predicate = _value(row.get("predicate"))
        target = _value(row.get("object"))
        if not subject or not predicate or not target or predicate.endswith("#type"):
            continue
        local = predicate.split("/ontology/", 1)[1] if "/ontology/" in predicate else predicate.rsplit("/", 1)[-1]
        key = (subject, local, target)
        if key in seen:
            continue
        seen.add(key)
        links.append({"source": subject, "predicate": local, "target": target})
    return links


def _map_ids(store: SparqlStore, iris: list[str], rows: list[dict], base_iri: str) -> tuple[list[str], list[str]]:
    areas: list[str] = []
    counties: list[str] = []
    area_prefix = base_iri + "area/"
    county_prefix = base_iri + "county/"
    coverage_prefix = base_iri + "coverage/"
    system_prefix = base_iri + "system/"
    system_iris: list[str] = []
    for iri in iris:
        if iri.startswith(area_prefix):
            areas.append(iri[len(area_prefix) :])
        elif iri.startswith(county_prefix):
            counties.append(iri[len(county_prefix) :])
        elif iri.startswith(coverage_prefix):
            parts = iri[len(coverage_prefix) :].split("/")
            if len(parts) == 2 and parts[1]:
                counties.append(parts[1])
        elif iri.startswith(system_prefix):
            system_iris.append(iri)
    for row in rows:
        for key, value in row.items():
            text = _plain_literal(value)
            if not text:
                continue
            if key in {"service_area_id", "area_id"}:
                areas.append(text)
            elif key == "county_geoid":
                counties.append(text)
    if system_iris and not areas:
        values = " ".join(format_iri(iri, base_iri) for iri in system_iris[:300])
        query = f"""{prefix_block(base_iri)}
SELECT ?areaId WHERE {{
  VALUES ?sys {{ {values} }}
  ?sys ud:hasServiceArea ?area .
  ?area ud:is_best true ;
        ud:service_area_id ?areaId .
}}
LIMIT 300
"""
        try:
            for item in store.select(query):
                aid = _value(item.get("areaId"))
                if aid:
                    areas.append(aid)
        except ValueError:
            pass
    return _unique(areas), _unique(counties)


def _value(cell: object) -> str:
    if isinstance(cell, dict) and isinstance(cell.get("value"), str):
        return cell["value"]
    return ""


def _plain_literal(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("kind") == "literal" and isinstance(value.get("value"), str):
        return value["value"]
    return ""


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
