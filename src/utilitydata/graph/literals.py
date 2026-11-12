"""N-Triples tokens. The full export writes these lines directly and does not build a graph."""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Mapping

import pyarrow as pa
import pyarrow.types as pat

from utilitydata.core.config import GRAPH_BASE_IRI

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
XSD_DOUBLE = "http://www.w3.org/2001/XMLSchema#double"
XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"
XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDF_STATEMENT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#Statement"
RDF_SUBJECT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#subject"
RDF_PREDICATE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate"
RDF_OBJECT = "http://www.w3.org/1999/02/22-rdf-syntax-ns#object"
_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")
_LOCAL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_IRI_FORBIDDEN = set('<>"{}|\\^` ')


def require_base(base: str) -> str:
    """Return the base IRI. It is the one configured value, with a trailing slash."""
    if base != base.strip() or not base.endswith("/") or not base.startswith(("http://", "https://")):
        raise ValueError("Graph base IRI must be an absolute HTTP IRI ending with /")
    if any(char in base for char in _IRI_FORBIDDEN):
        raise ValueError("Graph base IRI contains a character N-Triples cannot quote")
    return base


def ontology_iri(base: str = GRAPH_BASE_IRI) -> str:
    """Return the predicate and class namespace derived from the base IRI."""
    return f"{require_base(base)}ontology/"


def entity_iri(kind: str, identifier: str, base: str = GRAPH_BASE_IRI) -> str:
    """Return one entity IRI. The identifier is a single safe path segment."""
    if not _SEGMENT.fullmatch(identifier or ""):
        raise ValueError(f"{kind} identifier is not safe in an IRI")
    if kind not in {"system", "org", "facility", "county", "state", "source", "place", "area", "relationship"}:
        raise ValueError(f"Unknown IRI kind: {kind}")
    return f"{require_base(base)}{kind}/{identifier}"


def coverage_iri(system_id: str, county_geoid: str, base: str = GRAPH_BASE_IRI) -> str:
    """Return the county-coverage IRI for one system and county."""
    if not _SEGMENT.fullmatch(system_id or "") or not _SEGMENT.fullmatch(county_geoid or ""):
        raise ValueError("County coverage identifier is not safe in an IRI")
    return f"{require_base(base)}coverage/{system_id}/{county_geoid}"


def term_iri(local: str, base: str = GRAPH_BASE_IRI) -> str:
    """Return a class or predicate IRI."""
    if not _LOCAL.fullmatch(local):
        raise ValueError(f"Graph term is not a local name: {local}")
    return f"{ontology_iri(base)}{local}"


def escape_literal(text: str) -> str:
    """Escape one literal for N-Triples."""
    pieces: list[str] = []
    for char in text:
        code = ord(char)
        if char == "\\":
            pieces.append("\\\\")
        elif char == '"':
            pieces.append('\\"')
        elif char == "\n":
            pieces.append("\\n")
        elif char == "\r":
            pieces.append("\\r")
        elif char == "\t":
            pieces.append("\\t")
        elif code < 32 or code == 127:
            pieces.append(f"\\u{code:04X}")
        else:
            pieces.append(char)
    return "".join(pieces)


def iri_ref(value: str) -> str:
    """Return an absolute IRI in N-Triples brackets."""
    if not value.startswith(("http://", "https://")):
        raise ValueError("IRI is not absolute")
    if any(char in value for char in _IRI_FORBIDDEN):
        raise ValueError("IRI contains a character N-Triples cannot quote")
    return f"<{value}>"


def literal_token(value: object, arrow_type: pa.DataType) -> str:
    """Return one typed literal token. Null is rejected so callers skip it explicitly."""
    if value is None:
        raise ValueError("Literal value is null")
    if pat.is_string(arrow_type) or pat.is_large_string(arrow_type):
        if not isinstance(value, str):
            raise ValueError("String literal is not text")
        return f'"{escape_literal(value)}"^^<{XSD_STRING}>'
    if pat.is_boolean(arrow_type):
        if not isinstance(value, bool):
            raise ValueError("Boolean literal is not a bool")
        return f'"{"true" if value else "false"}"^^<{XSD_BOOLEAN}>'
    if pat.is_integer(arrow_type):
        return f'"{int(value)}"^^<{XSD_INTEGER}>'
    if pat.is_floating(arrow_type):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite double")
        return f'"{number!r}"^^<{XSD_DOUBLE}>'
    if pat.is_date(arrow_type):
        if not isinstance(value, dt.date) or isinstance(value, dt.datetime):
            raise ValueError("Date literal is not a date")
        return f'"{value.isoformat()}"^^<{XSD_DATE}>'
    if pat.is_timestamp(arrow_type):
        if not isinstance(value, dt.datetime):
            raise ValueError("Timestamp literal is not a datetime")
        return f'"{value.isoformat()}"^^<{XSD_DATETIME}>'
    raise ValueError(f"Unsupported literal type: {arrow_type}")


def triple(subject: str, predicate: str, object_token: str) -> str:
    """Return one N-Triples line."""
    return f"{iri_ref(subject)} {iri_ref(predicate)} {object_token} .\n"


def turtle_string(text: str) -> str:
    """Quote a Turtle string."""
    return f'"{escape_literal(text)}"'


def require_local_names(names: Mapping[str, str]) -> None:
    """Raise when a hand-written label map is incomplete or unsafe."""
    for key in names:
        if not _LOCAL.fullmatch(key):
            raise ValueError(f"Graph term is not a local name: {key}")
