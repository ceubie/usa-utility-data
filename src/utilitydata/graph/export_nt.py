"""Stream node and edge tables to N-Triples without building an in-memory graph."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from utilitydata.core.config import GRAPH_BASE_IRI
from utilitydata.graph.literals import (
    RDF_OBJECT,
    RDF_PREDICATE,
    RDF_STATEMENT,
    RDF_SUBJECT,
    RDF_TYPE,
    iri_ref,
    literal_token,
    term_iri,
    triple,
)
from utilitydata.graph.spec import (
    EDGE_FIELDS,
    EDGE_FILES,
    NODE_FIELDS,
    NODE_OBJECT_COLUMNS,
    PARENT_STATEMENT_FIELDS,
)

_PREDICATE_BY_FILE = {file_name: link for link, file_name in EDGE_FILES.items()}
_BATCH_ROWS = 8000


def write_ntriples(graph_dir: Path, destination: Path | None = None, *, base: str = GRAPH_BASE_IRI) -> dict[str, object]:
    """Write N-Triples from the exported tables. Rows are streamed in batches."""
    meta_path = graph_dir / "export_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("query_language") != "SPARQL":
        raise ValueError("Graph export is not a SPARQL export")
    if meta.get("base_iri") != base:
        raise ValueError("Graph export base IRI does not match the configured base IRI")
    output = destination if destination is not None else graph_dir / "graph.nt"
    counts: dict[str, int] = {}
    triples = 0
    with output.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as handle:
        nodes = graph_dir / "nodes"
        edges = graph_dir / "edges"
        for name in NODE_FIELDS:
            path = nodes / f"{name}.parquet"
            if not path.is_file():
                raise ValueError(f"Node table is missing: {name}")
            triples += _write_nodes(path, name, handle, counts, base)
        for name in EDGE_FIELDS:
            path = edges / f"{name}.parquet"
            if not path.is_file():
                raise ValueError(f"Edge table is missing: {name}")
            triples += _write_edges(path, name, handle, base)
    return {"triples": triples, "type_counts": counts, "path": output.name}


def _write_nodes(path: Path, name: str, handle, counts: dict[str, int], base: str) -> int:
    parquet = pq.ParquetFile(path)
    _require_columns(path, NODE_FIELDS[name], name)
    written = 0
    objects = NODE_OBJECT_COLUMNS.get(name, {})
    for batch in parquet.iter_batches(batch_size=_BATCH_ROWS):
        columns = {field.name: batch.column(index).to_pylist() for index, field in enumerate(batch.schema)}
        types = {field.name: field.type for field in batch.schema}
        lines: list[str] = []
        for row in range(batch.num_rows):
            subject = columns["iri"][row]
            if not isinstance(subject, str) or not subject:
                raise ValueError(f"{name} row is missing an IRI")
            type_names = columns["rdf_types"][row]
            if not type_names:
                raise ValueError(f"{name} row is missing a class")
            for type_name in type_names:
                if not isinstance(type_name, str):
                    raise TypeError(f"{name} class is not text")
                lines.append(triple(subject, RDF_TYPE, iri_ref(term_iri(type_name, base))))
                counts[type_name] = counts.get(type_name, 0) + 1
            for column, values in columns.items():
                if column in {"iri", "rdf_types"}:
                    continue
                value = values[row]
                if column in objects:
                    if not isinstance(value, str) or not value:
                        raise ValueError(f"{name}.{column} is missing an IRI")
                    lines.append(triple(subject, term_iri(objects[column], base), iri_ref(value)))
                    continue
                if value is None:
                    continue
                lines.append(triple(subject, term_iri(column, base), literal_token(value, types[column])))
        handle.writelines(lines)
        written += len(lines)
    return written


def _write_edges(path: Path, name: str, handle, base: str) -> int:
    parquet = pq.ParquetFile(path)
    _require_columns(path, EDGE_FIELDS[name], name)
    predicate_name = _PREDICATE_BY_FILE[name]
    predicate = term_iri(predicate_name, base)
    written = 0
    for batch in parquet.iter_batches(batch_size=_BATCH_ROWS):
        columns = {field.name: batch.column(index).to_pylist() for index, field in enumerate(batch.schema)}
        types = {field.name: field.type for field in batch.schema}
        lines: list[str] = []
        for row in range(batch.num_rows):
            if columns["predicate"][row] != predicate_name:
                raise ValueError(f"{name} predicate does not match its link")
            subject = columns["subject_iri"][row]
            object_iri = columns["object_iri"][row]
            if not isinstance(subject, str) or not isinstance(object_iri, str):
                raise TypeError(f"{name} edge is missing an IRI")
            lines.append(triple(subject, predicate, iri_ref(object_iri)))
            if name == "parent_of":
                lines.extend(_parent_statement(columns, types, row, predicate, base))
        handle.writelines(lines)
        written += len(lines)
    return written


def _parent_statement(
    columns: dict[str, list[object]],
    types: dict[str, pa.DataType],
    row: int,
    predicate: str,
    base: str,
) -> list[str]:
    statement = columns["relationship_iri"][row]
    subject = columns["subject_iri"][row]
    object_iri = columns["object_iri"][row]
    if not isinstance(statement, str) or not isinstance(subject, str) or not isinstance(object_iri, str):
        raise TypeError("Parent statement is missing an IRI")
    lines = [
        triple(statement, RDF_TYPE, iri_ref(RDF_STATEMENT)),
        triple(statement, RDF_SUBJECT, iri_ref(subject)),
        triple(statement, RDF_PREDICATE, iri_ref(predicate)),
        triple(statement, RDF_OBJECT, iri_ref(object_iri)),
    ]
    for column in PARENT_STATEMENT_FIELDS:
        value = columns[column][row]
        if value is None:
            if column in {"experimental", "coverage_note"}:
                raise ValueError("Parent statement is missing its experimental label")
            continue
        lines.append(triple(statement, term_iri(column, base), literal_token(value, types[column])))
    note = columns["coverage_note"][row]
    experimental = columns["experimental"][row]
    if not isinstance(experimental, bool):
        raise TypeError("Parent experimental flag is not boolean")
    if experimental and (not isinstance(note, str) or "experimental" not in note or "incomplete" not in note):
        raise ValueError("Experimental parent rows must stay labeled experimental and incomplete")
    return lines


def _require_columns(path: Path, expected: tuple[str, ...], label: str) -> None:
    found = tuple(pq.ParquetFile(path).schema_arrow.names)
    if found != expected:
        missing = [name for name in expected if name not in found]
        extra = [name for name in found if name not in expected]
        if missing:
            raise ValueError(f"{label} is missing columns: {', '.join(missing)}")
        raise ValueError(f"{label} has unexpected columns: {', '.join(extra)}")
