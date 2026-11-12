"""Schema card coverage."""

import pytest
from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from app.backend.agent.schema_card import build_schema_card
from app.backend.settings import get_settings, repository_root

_CLASS_COUNTS = {
    "Organization": 403_693,
    "UtilitySystem": 492_011,
    "WaterSystem": 446_100,
    "ElectricSystem": 17_552,
    "WastewaterSystem": 26_938,
    "NaturalGasSystem": 1_421,
    "ServiceArea": 170_759,
    "Facility": 1_898_364,
    "County": 3_235,
    "State": 56,
    "Place": 32_629,
    "Source": 139,
    "CountyCoverage": 154_444,
}
_LINK_COUNTS = {
    "ownsSystem": 419_997,
    "operatesSystem": 0,
    "parentOf": 3_998,
    "hasServiceArea": 170_759,
    "assertedBy": 2_631_258,
    "inState": 1_224_263,
    "locatedInCounty": 0,
    "servesCounty": 39_502,
    "system": 154_444,
    "county": 154_444,
}


@pytest.mark.requires_release
def test_every_ontology_class_and_link_is_in_the_schema_card():
    card = build_schema_card(get_settings())
    parsed = Graph()
    parsed.parse(repository_root() / "graph" / "ontology.ttl")
    classes = {_local(str(iri)) for iri in parsed.subjects(RDF.type, RDFS.Class)}
    links = {_local(str(iri)) for iri in parsed.subjects(RDF.type, OWL.ObjectProperty)}
    card_classes = {item.name for item in card.classes}
    card_links = {item.name for item in card.links}
    assert classes <= card_classes
    assert links <= card_links
    assert card.prefixes.startswith("PREFIX rdf:")
    assert card.iri_patterns

    by_class = {item.name: item.count for item in card.classes}
    by_link = {item.name: item.count for item in card.links}
    for name, count in _CLASS_COUNTS.items():
        assert by_class[name] == count
    for name, count in _LINK_COUNTS.items():
        assert by_link[name] == count

    authority = next(item for item in card.attributes if item.name == "authority")
    assert authority.values is not None
    assert {"utility_direct", "state_regulator", "federal_submitted", "federal_modeled", "admin_proxy"} <= set(authority.values)


def _local(uri: str) -> str:
    if "/ontology/" in uri:
        return uri.split("/ontology/", 1)[1]
    return uri.rstrip("/").rsplit("/", 1)[-1]
