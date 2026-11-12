"""Build the ontology from the table contracts and the hand-written labels."""

from __future__ import annotations

from pathlib import Path

import yaml

from utilitydata.core.config import GRAPH_BASE_IRI, GRAPH_QUERY_TIMEOUT_S
from utilitydata.cross.schema import FACILITY_COLUMNS
from utilitydata.graph.literals import ontology_iri, turtle_string
from utilitydata.graph.spec import (
    CLASS_COMMENTS,
    CLASS_LABELS,
    COVERAGE_OBJECT_PROPERTIES,
    EXCLUDED_EXPORT_COLUMNS,
    LINK_COMMENTS,
    LINK_DOMAIN,
    LINK_LABELS,
    LINK_RANGE,
    LINKS,
    SECTOR_CLASSES,
    SOURCE_FIELDS,
    XSD,
)

_CONTRACTS = (
    ("contracts/core/organization.yaml", "Organization"),
    ("contracts/core/system.yaml", "UtilitySystem"),
    ("contracts/core/service_area.yaml", "ServiceArea"),
    ("contracts/gold/system_county_coverage.yaml", "CountyCoverage"),
)
_MAIN_CLASSES = (
    "Organization",
    "UtilitySystem",
    "ServiceArea",
    "Facility",
    "County",
    "State",
    "Place",
    "Source",
    "CountyCoverage",
)
_FACILITY_TYPES = {
    "facility_id": "string",
    "sector": "string",
    "facility_type": "string",
    "name": "string",
    "name_norm": "string",
    "state": "string",
    "owner_name": "string",
    "status": "string",
    "capacity_mw": "float",
    "unit_count": "integer",
    "source_id": "string",
    "source_layer": "string",
    "source_feature_id": "string",
    "licence": "string",
    "longitude": "float",
    "latitude": "float",
    "geometry_wkb": "string",
}
_GEOGRAPHY = {
    "County": {
        "county_geoid": "string",
        "state": "string",
        "countyfp": "string",
        "name": "string",
        "namelsad": "string",
        "pop20": "integer",
    },
    "State": {
        "state": "string",
        "geoid": "string",
        "usps": "string",
        "name": "string",
        "pop20": "integer",
    },
    "Place": {
        "place_geoid": "string",
        "state": "string",
        "placefp": "string",
        "name": "string",
        "namelsad": "string",
        "pop20": "integer",
    },
}
_SOURCE_TYPES = {
    "source_id": "string",
    "publisher": "string",
    "driver": "string",
    "url": "string",
    "licence": "string",
    "cadence": "string",
    "redistribution": "string",
    "out_of_scope": "boolean",
    "notes": "string",
    "reviewed": "boolean",
}


def write_ontology(repository_root: Path, base: str = GRAPH_BASE_IRI) -> Path:
    """Write graph/ontology.ttl from the contracts and the hand-written labels."""
    destination = repository_root / "graph" / "ontology.ttl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_ontology(repository_root, base), encoding="utf-8")
    return destination


def render_ontology(repository_root: Path, base: str = GRAPH_BASE_IRI) -> str:
    """Return the ontology document."""
    _require_labels()
    sectors = _sectors(repository_root / "registry" / "vocab" / "sector.yaml")
    properties = _properties(repository_root)
    lines = [
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        f"@prefix ud: <{ontology_iri(base)}> .",
        "",
        "# Query language: SPARQL.",
        "# Store: Apache Jena Fuseki. The dataset is loaded from N-Triples and queried read-only.",
        f"# Base IRI: {base}",
        "# Geometry, block coverage, monthly series, and individual violations are not in this ontology.",
        "",
    ]
    for name in _MAIN_CLASSES:
        if name == "UtilitySystem":
            lines.extend(_class(name))
            for sector in sectors:
                lines.extend(_class(SECTOR_CLASSES[sector], subclass_of="UtilitySystem"))
        else:
            lines.extend(_class(name))
    lines.append("")
    for name in LINKS:
        lines.extend(_link(name))
    lines.append("")
    for name, (range_name, comment) in COVERAGE_OBJECT_PROPERTIES.items():
        lines.extend(
            [
                f"ud:{name} a owl:ObjectProperty ;",
                f"    rdfs:label {turtle_string(name)} ;",
                "    rdfs:domain ud:CountyCoverage ;",
                f"    rdfs:range ud:{range_name} ;",
                f"    rdfs:comment {turtle_string(comment)} .",
                "",
            ]
        )
    for name in sorted(properties):
        record = properties[name]
        classes = ", ".join(record["classes"])
        description = " ".join(record["descriptions"]) if record["descriptions"] else f"Column {name}."
        lines.extend(
            [
                f"ud:{name} a owl:DatatypeProperty ;",
                f"    rdfs:label {turtle_string(name)} ;",
                f"    rdfs:range {record['xsd']} ;",
                f"    rdfs:comment {turtle_string(description + ' Used by ' + classes + '.')} .",
                "",
            ]
        )
    return "\n".join(lines)


def render_assembler() -> str:
    """Return the Fuseki assembler. It exposes the query service and a server-side timeout."""
    timeout_ms = GRAPH_QUERY_TIMEOUT_S * 1000
    return "\n".join(
        [
            "@prefix fuseki: <http://jena.apache.org/fuseki#> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix ja: <http://jena.apache.org/ja#> .",
            "@prefix tdb2: <http://jena.apache.org/2016/tdb#> .",
            "",
            "# Query service only. The timeout is server-side.",
            f"# Query timeout: {GRAPH_QUERY_TIMEOUT_S} seconds.",
            "",
            "[] rdf:type fuseki:Server ;",
            f'    ja:context [ ja:cxtName "arq:queryTimeout" ; ja:cxtValue "{timeout_ms}" ] ;',
            "    fuseki:services ( <#utility> ) .",
            "",
            "<#utility> rdf:type fuseki:Service ;",
            '    fuseki:name "utility" ;',
            '    fuseki:serviceQuery "query" ;',
            "    fuseki:dataset <#dataset> .",
            "",
            "<#dataset> rdf:type tdb2:DatasetTDB2 ;",
            '    tdb2:location "/fuseki/databases/utility" ;',
            f'    ja:context [ ja:cxtName "arq:queryTimeout" ; ja:cxtValue "{timeout_ms}" ] .',
            "",
        ]
    )


def write_assembler(repository_root: Path) -> Path:
    """Write the Fuseki assembler next to the image definition."""
    destination = repository_root / "graph" / "fuseki" / "assembler.ttl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_assembler(), encoding="utf-8")
    return destination


def _require_labels() -> None:
    expected = set(_MAIN_CLASSES) | set(SECTOR_CLASSES.values())
    if set(CLASS_LABELS) != expected or set(CLASS_COMMENTS) != expected:
        raise ValueError("Class labels do not match the ontology classes")
    if set(LINK_LABELS) != set(LINKS) or set(LINK_COMMENTS) != set(LINKS):
        raise ValueError("Link labels do not match the ontology links")
    if tuple(LINK_LABELS) != LINKS:
        raise ValueError("Link label order does not match the link list")


def _sectors(path: Path) -> list[str]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or [str(item) for item in loaded] != list(SECTOR_CLASSES):
        raise ValueError("Sector vocabulary does not match the graph sector classes")
    return [str(item) for item in loaded]


def _class(name: str, subclass_of: str | None = None) -> list[str]:
    lines = [
        f"ud:{name} a rdfs:Class ;",
        f"    rdfs:label {turtle_string(CLASS_LABELS[name])} ;",
    ]
    if subclass_of:
        lines.append(f"    rdfs:subClassOf ud:{subclass_of} ;")
    lines.append(f"    rdfs:comment {turtle_string(CLASS_COMMENTS[name])} .")
    lines.append("")
    return lines


def _link(name: str) -> list[str]:
    lines = [
        f"ud:{name} a owl:ObjectProperty ;",
        f"    rdfs:label {turtle_string(LINK_LABELS[name])} ;",
    ]
    if name in LINK_DOMAIN:
        lines.append(f"    rdfs:domain ud:{LINK_DOMAIN[name]} ;")
    lines.append(f"    rdfs:range ud:{LINK_RANGE[name]} ;")
    lines.append(f"    rdfs:comment {turtle_string(LINK_COMMENTS[name])} .")
    lines.append("")
    return lines


def _properties(repository_root: Path) -> dict[str, dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for relative, class_name in _CONTRACTS:
        for column in _contract_columns(repository_root / relative):
            _add_property(grouped, column["name"], column["type"], class_name, column.get("description") or "")
    if set(FACILITY_COLUMNS) != set(_FACILITY_TYPES):
        raise ValueError("Facility columns do not match the graph property list")
    if "geometry_wkb" not in FACILITY_COLUMNS:
        raise ValueError("Facility schema no longer names geometry_wkb")
    for name, type_name in _FACILITY_TYPES.items():
        _add_property(grouped, name, type_name, "Facility", "")
    for class_name, columns in _GEOGRAPHY.items():
        for name, type_name in columns.items():
            _add_property(grouped, name, type_name, class_name, "")
    if tuple(_SOURCE_TYPES) != SOURCE_FIELDS:
        raise ValueError("Source fields do not match the graph property list")
    for name, type_name in _SOURCE_TYPES.items():
        _add_property(grouped, name, type_name, "Source", "")
    return grouped


def _add_property(
    grouped: dict[str, dict[str, object]],
    name: str,
    type_name: str,
    class_name: str,
    description: str,
) -> None:
    if name in EXCLUDED_EXPORT_COLUMNS:
        return
    lowered = name.casefold()
    if "violation" in lowered or lowered.startswith("block") or "geometry" in lowered:
        raise ValueError(f"Refusing to export column {name}")
    if type_name not in XSD:
        raise ValueError(f"{name} has an unknown contract type: {type_name}")
    current = grouped.setdefault(name, {"xsd": XSD[type_name], "classes": [], "descriptions": []})
    if current["xsd"] != XSD[type_name]:
        raise ValueError(f"{name} has more than one contract type")
    classes = current["classes"]
    if not isinstance(classes, list) or not isinstance(current["descriptions"], list):
        raise TypeError(f"{name} property record is invalid")
    if class_name not in classes:
        classes.append(class_name)
    text = " ".join(description.split())
    if text and text not in current["descriptions"]:
        current["descriptions"].append(text)


def _contract_columns(path: Path) -> list[dict[str, str]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    columns = document.get("columns") if isinstance(document, dict) else None
    if not isinstance(columns, list) or not columns:
        raise ValueError(f"{path.name} has no columns")
    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for column in columns:
        if not isinstance(column, dict) or "name" not in column:
            raise ValueError(f"{path.name} has a column without a name")
        name = str(column["name"])
        if name in seen:
            raise ValueError(f"{path.name} repeats column {name}")
        seen.add(name)
        if name in EXCLUDED_EXPORT_COLUMNS:
            parsed.append({"name": name, "type": str(column.get("type") or "string"), "description": ""})
            continue
        if "type" not in column:
            raise ValueError(f"{path.name}.{name} is missing a type")
        parsed.append(
            {
                "name": name,
                "type": str(column["type"]),
                "description": str(column.get("description") or ""),
            }
        )
    if path.name == "service_area.yaml" and "geometry" not in seen:
        raise ValueError("Service area contract no longer names geometry")
    return parsed
