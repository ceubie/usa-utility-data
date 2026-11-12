"""SPARQL prefix block shared by the guard, the schema card, and the prompt."""

from __future__ import annotations

_STANDARD = (
    ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
    ("owl", "http://www.w3.org/2002/07/owl#"),
    ("xsd", "http://www.w3.org/2001/XMLSchema#"),
)


def ontology_namespace(base_iri: str) -> str:
    """Return the class and predicate namespace for a base IRI."""
    if not base_iri.endswith("/"):
        raise ValueError("Graph base IRI must end with /")
    return f"{base_iri}ontology/"


def standard_prefixes(base_iri: str) -> tuple[tuple[str, str], ...]:
    """Return the prefix map every query can use."""
    return (*_STANDARD, ("ud", ontology_namespace(base_iri)))


def prefix_block(base_iri: str) -> str:
    """Return the standard prefix block."""
    return "\n".join(f"PREFIX {name}: <{iri}>" for name, iri in standard_prefixes(base_iri))
