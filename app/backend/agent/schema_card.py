"""Schema card built from the ontology and the release graph tables."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from app.backend.agent.prefixes import prefix_block
from app.backend.settings import Settings, repository_root
from utilitydata.graph.spec import EDGE_FILES

_NODE_FILES = (
    "organization.parquet",
    "utility_system.parquet",
    "service_area.parquet",
    "facility.parquet",
    "county.parquet",
    "state.parquet",
    "place.parquet",
    "source.parquet",
    "county_coverage.parquet",
)
_HOMOGENEOUS = {
    "organization.parquet": "Organization",
    "service_area.parquet": "ServiceArea",
    "facility.parquet": "Facility",
    "county.parquet": "County",
    "state.parquet": "State",
    "place.parquet": "Place",
    "source.parquet": "Source",
    "county_coverage.parquet": "CountyCoverage",
}
_VALUE_LIMIT = 30
_CACHE: dict[tuple[str, int, str], SchemaCard] = {}


@dataclass(frozen=True)
class ClassCard:
    name: str
    iri: str
    label: str
    description: str
    count: int
    subclass_of: str | None


@dataclass(frozen=True)
class LinkCard:
    name: str
    iri: str
    label: str
    description: str
    count: int
    domain: str | None
    range: str | None


@dataclass(frozen=True)
class AttributeCard:
    name: str
    iri: str
    label: str
    description: str
    datatype: str
    values: tuple[str, ...] | None


@dataclass(frozen=True)
class SchemaCard:
    classes: tuple[ClassCard, ...]
    links: tuple[LinkCard, ...]
    attributes: tuple[AttributeCard, ...]
    iri_patterns: tuple[dict[str, str], ...]
    prefixes: str

    def as_prompt(self) -> str:
        """Return the card text included in the system prompt."""
        lines = ["Schema card", "", self.prefixes, "", "Classes"]
        for item in self.classes:
            parent = f" Subclass of {item.subclass_of}." if item.subclass_of else ""
            lines.append(f"- {item.name}: {item.label}. {item.description}{parent} Count: {item.count}.")
        lines.extend(["", "Links"])
        for item in self.links:
            domain = item.domain or "unspecified"
            range_name = item.range or "unspecified"
            lines.append(
                f"- {item.name}: {item.label}. {item.description} "
                f"Domain {domain}, range {range_name}. Count: {item.count}."
            )
        lines.extend(["", "Attributes"])
        for item in self.attributes:
            if item.values is None:
                allowed = "more than 30 distinct values"
            elif item.values:
                allowed = ", ".join(item.values)
            else:
                allowed = "no non-null values"
            lines.append(f"- {item.name} ({item.datatype}): {item.description} Allowed values: {allowed}.")
        lines.extend(["", "IRI patterns"])
        for pattern in self.iri_patterns:
            lines.append(f"- {pattern['entity']}: {pattern['pattern']}")
        return "\n".join(lines)


def build_schema_card(settings: Settings) -> SchemaCard:
    """Build the card once per release and ontology revision."""
    ontology = repository_root() / "graph" / "ontology.ttl"
    key = (str(settings.release_dir), ontology.stat().st_mtime_ns, settings.graph_base_iri)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    card = _build(settings, ontology)
    _CACHE[key] = card
    return card


def _build(settings: Settings, ontology: Path) -> SchemaCard:
    parsed = Graph()
    parsed.parse(ontology, format="turtle")
    class_counts = _class_counts(settings.release_dir)
    link_counts = _link_counts(settings.release_dir)
    classes = tuple(
        sorted(
            (
                ClassCard(
                    name=_local(str(iri)),
                    iri=str(iri),
                    label=_text(parsed.value(iri, RDFS.label)) or _local(str(iri)),
                    description=_text(parsed.value(iri, RDFS.comment)),
                    count=class_counts.get(_local(str(iri)), 0),
                    subclass_of=_local(str(parent)) if (parent := parsed.value(iri, RDFS.subClassOf)) else None,
                )
                for iri in parsed.subjects(RDF.type, RDFS.Class)
            ),
            key=lambda item: item.name,
        )
    )
    links = tuple(
        sorted(
            (
                LinkCard(
                    name=_local(str(iri)),
                    iri=str(iri),
                    label=_text(parsed.value(iri, RDFS.label)) or _local(str(iri)),
                    description=_text(parsed.value(iri, RDFS.comment)),
                    count=link_counts[_local(str(iri))],
                    domain=_local(str(domain)) if (domain := parsed.value(iri, RDFS.domain)) else None,
                    range=_local(str(range_iri)) if (range_iri := parsed.value(iri, RDFS.range)) else None,
                )
                for iri in parsed.subjects(RDF.type, OWL.ObjectProperty)
            ),
            key=lambda item: item.name,
        )
    )
    attributes = _attributes(parsed, settings.release_dir)
    return SchemaCard(
        classes=classes,
        links=links,
        attributes=attributes,
        iri_patterns=_patterns(settings.graph_base_iri),
        prefixes=prefix_block(settings.graph_base_iri),
    )


def _class_counts(release: Path) -> dict[str, int]:
    nodes = release / "graph" / "nodes"
    counts = {
        class_name: pq.ParquetFile(nodes / filename).metadata.num_rows
        for filename, class_name in _HOMOGENEOUS.items()
    }
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            """
            SELECT type_name, count(*)::BIGINT
            FROM (SELECT UNNEST(rdf_types) AS type_name FROM read_parquet(?))
            GROUP BY 1
            """,
            [str(nodes / "utility_system.parquet")],
        ).fetchall()
    finally:
        connection.close()
    for name, count in rows:
        counts[str(name)] = int(count)
    return counts


def _link_counts(release: Path) -> dict[str, int]:
    edges = release / "graph" / "edges"
    counts = {
        name: pq.ParquetFile(edges / f"{stem}.parquet").metadata.num_rows
        for name, stem in EDGE_FILES.items()
    }
    connection = duckdb.connect()
    try:
        row = connection.execute(
            """
            SELECT
                count(*) FILTER (WHERE system_iri IS NOT NULL)::BIGINT,
                count(*) FILTER (WHERE county_iri IS NOT NULL)::BIGINT
            FROM read_parquet(?)
            """,
            [str(release / "graph" / "nodes" / "county_coverage.parquet")],
        ).fetchone()
    finally:
        connection.close()
    counts["system"] = int(row[0]) if row else 0
    counts["county"] = int(row[1]) if row else 0
    return counts


def _attributes(parsed: Graph, release: Path) -> tuple[AttributeCard, ...]:
    properties = []
    for iri in parsed.subjects(RDF.type, OWL.DatatypeProperty):
        properties.append(
            (
                _local(str(iri)),
                str(iri),
                _text(parsed.value(iri, RDFS.label)) or _local(str(iri)),
                _text(parsed.value(iri, RDFS.comment)),
                _datatype(parsed.value(iri, RDFS.range)),
            )
        )
    names = {item[0] for item in properties}
    columns = _attribute_columns(release / "graph" / "nodes", names)
    cards = []
    for name, iri, label, description, datatype in sorted(properties):
        values = columns.get(name)
        cards.append(
            AttributeCard(
                name=name,
                iri=iri,
                label=label,
                description=description,
                datatype=datatype,
                values=None if values is None else tuple(sorted(values, key=str.casefold)),
            )
        )
    return tuple(cards)


def _attribute_columns(nodes: Path, names: set[str]) -> dict[str, set[str] | None]:
    combined: dict[str, set[str] | None] = {name: set() for name in names}
    for filename in _NODE_FILES:
        path = nodes / filename
        present = [name for name in sorted(names) if name in pq.ParquetFile(path).schema_arrow.names]
        if not present:
            continue
        found = _column_values(path, present)
        for name, values in found.items():
            current = combined[name]
            if current is None or values is None:
                combined[name] = None
                continue
            current.update(values)
            if len(current) > _VALUE_LIMIT:
                combined[name] = None
    return combined


def _column_values(path: Path, columns: list[str]) -> dict[str, set[str] | None]:
    parquet = pq.ParquetFile(path)
    sample: dict[str, set[str]] = {column: set() for column in columns}
    seen = 0
    for batch in parquet.iter_batches(columns=columns, batch_size=10_000):
        for column in columns:
            bucket = sample[column]
            if len(bucket) > _VALUE_LIMIT:
                continue
            for value in batch.column(column).to_pylist():
                if value is None:
                    continue
                bucket.add(_value_text(value))
                if len(bucket) > _VALUE_LIMIT:
                    break
        seen += batch.num_rows
        if seen >= 10_000:
            break
    survivors = [column for column, bucket in sample.items() if len(bucket) <= _VALUE_LIMIT]
    totals = {column: set() for column in survivors}
    if survivors:
        for batch in parquet.iter_batches(columns=survivors, batch_size=100_000):
            for column in survivors:
                bucket = totals[column]
                if len(bucket) > _VALUE_LIMIT:
                    continue
                for value in batch.column(column).to_pylist():
                    if value is None:
                        continue
                    bucket.add(_value_text(value))
    result: dict[str, set[str] | None] = {}
    for column in columns:
        if column not in totals or len(totals[column]) > _VALUE_LIMIT:
            result[column] = None
        else:
            result[column] = totals[column]
    return result


def _patterns(base: str) -> tuple[dict[str, str], ...]:
    return (
        {"entity": "UtilitySystem", "pattern": f"{base}system/{{system_id}}"},
        {"entity": "Organization", "pattern": f"{base}org/{{org_id}}"},
        {"entity": "Facility", "pattern": f"{base}facility/{{facility_id}}"},
        {"entity": "ServiceArea", "pattern": f"{base}area/{{service_area_id}}"},
        {"entity": "County", "pattern": f"{base}county/{{county_geoid}}"},
        {"entity": "State", "pattern": f"{base}state/{{usps}}"},
        {"entity": "Place", "pattern": f"{base}place/{{place_geoid}}"},
        {"entity": "Source", "pattern": f"{base}source/{{source_id}}"},
        {"entity": "CountyCoverage", "pattern": f"{base}coverage/{{system_id}}/{{county_geoid}}"},
        {"entity": "Parent statement", "pattern": f"{base}relationship/{{relationship_id}}"},
        {"entity": "Class or link", "pattern": f"{base}ontology/{{local_name}}"},
    )


def _local(uri: str) -> str:
    if "/ontology/" in uri:
        return uri.split("/ontology/", 1)[1]
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _datatype(value: object) -> str:
    if value is None:
        return "xsd:string"
    text = str(value)
    if text.startswith("http://www.w3.org/2001/XMLSchema#"):
        return "xsd:" + text.rsplit("#", 1)[-1]
    return _local(text)


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _value_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.timetuple()[3:6] == (0, 0, 0) else value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)
