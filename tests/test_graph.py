"""Graph export rules: served edges, escaped literals, and the ontology."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rdflib import Graph

from utilitydata.core.config import GRAPH_BASE_IRI, GRAPH_QUERY_TIMEOUT_S
from utilitydata.cross.schema import RELATIONSHIP_COLUMNS
from utilitydata.gold.schema import TRAVIS_COUNTY_GEOID
from utilitydata.graph.export_nt import write_ntriples
from utilitydata.graph.export_tables import (
    export_graph,
    forbidden_output_columns,
    travis_served_ids,
)
from utilitydata.graph.fuseki import documented_commands
from utilitydata.graph.literals import (
    XSD_STRING,
    escape_literal,
    literal_token,
    term_iri,
    triple,
)
from utilitydata.graph.ontology import render_assembler, render_ontology
from utilitydata.graph.spec import EDGE_FIELDS, LINKS, NODE_FIELDS, SECTOR_CLASSES
from utilitydata.pipeline import open_release

REPO = Path(__file__).resolve().parents[1]
NASTY = 'Say "hello"\\\n\r\t'


def test_ontology_uses_the_requested_classes_and_sparql():
    text = render_ontology(REPO)
    for name in (
        "Organization", "UtilitySystem", "ServiceArea", "Facility", "County", "State",
        "Place", "Source", "CountyCoverage",
    ):
        assert f"ud:{name} a rdfs:Class" in text
    for class_name in SECTOR_CLASSES.values():
        assert f"ud:{class_name} a rdfs:Class" in text
        assert "rdfs:subClassOf ud:UtilitySystem" in text
    for link in LINKS:
        assert f"ud:{link} a owl:ObjectProperty" in text
    assert "is_served is true" in text
    assert "experimental and incomplete" in text
    assert "SPARQL" in text
    lowered = text.lower()
    assert "cypher" not in lowered
    assert "blazegraph" not in lowered
    assert "npuc" not in lowered
    assert "geometry_wkb" not in text


def test_assembler_exposes_query_and_the_timeout():
    text = render_assembler()
    assert GRAPH_QUERY_TIMEOUT_S == 20
    assert 'ja:cxtValue "20000"' in text
    assert 'fuseki:serviceQuery "query"' in text
    assert "serviceUpdate" not in text
    assert "serviceUpload" not in text


def test_fuseki_commands_stay_on_the_loopback_interface():
    load, server = documented_commands("2026Q4.2")
    assert "127.0.0.1:3030:3030" in server
    assert "0.0.0.0" not in server
    assert "tdb2.tdbloader" in load
    assert "$UTILITYDATA_HOME/releases/2026Q4.2/graph" in load


def test_graph_package_does_not_branch_on_source_or_name_another_store():
    for path in (REPO / "src" / "utilitydata" / "graph").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "source_id ==" not in text
        assert "cypher" not in lowered
        assert "blazegraph" not in lowered
        assert "npuc" not in lowered
        assert "c:\\users" not in lowered


def test_literals_round_trip_through_ntriples():
    token = literal_token(NASTY, pa.string())
    line = triple(f"{GRAPH_BASE_IRI}facility/FAC_1", term_iri("name"), token)
    assert '\\"' in line
    assert "\\n" in line
    assert "\\r" in line
    assert "\\t" in line
    assert "\\\\" in line
    graph = Graph()
    graph.parse(data=line, format="nt")
    values = list(graph.objects())
    assert len(values) == 1
    assert str(values[0]) == NASTY
    assert escape_literal("plain") == "plain"
    assert token.endswith(f"^^<{XSD_STRING}>")


def test_ten_thousand_line_sample_parses(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    _empty_graph(graph_dir)
    fields = _empty_types(NODE_FIELDS["organization"])
    rows = []
    for index in range(5000):
        row = {name: None for name in fields}
        row["iri"] = f"{GRAPH_BASE_IRI}org/ORG_{index}"
        row["rdf_types"] = ["Organization"]
        row["name"] = f"Org {index}"
        rows.append(row)
    _write(graph_dir / "nodes" / "organization.parquet", fields, rows)
    for name, node_fields in NODE_FIELDS.items():
        if name == "organization":
            continue
        _write(graph_dir / "nodes" / f"{name}.parquet", _empty_types(node_fields), [])
    result = write_ntriples(graph_dir, base=GRAPH_BASE_IRI)
    lines = (graph_dir / "graph.nt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10000
    assert result["triples"] == 10000
    parsed = Graph()
    parsed.parse(data="\n".join(lines), format="nt")
    assert len(parsed) == 10000


def test_serves_county_follows_is_served_and_keeps_share_off_the_edge(tmp_path: Path):
    home = tmp_path / "home"
    registry = tmp_path / "registry"
    _mini_inputs(home, registry)
    open_release(home, "mini")
    summary = export_graph(home, REPO, quarter="2026-Q4", release_id="mini", registry_dir=registry, base=GRAPH_BASE_IRI)
    graph_dir = home / "releases" / "mini" / "graph"
    served = pq.read_table(graph_dir / "edges" / "serves_county.parquet").to_pydict()
    assert served["system_id"] == ["SYS_SERVED"]
    assert "pop_share_of_county" not in served
    assert "evidence" not in served
    assert "authority" not in served
    assert forbidden_output_columns(graph_dir) == []
    parents = pq.read_table(graph_dir / "edges" / "parent_of.parquet").to_pydict()
    assert parents["subject_iri"] == [f"{GRAPH_BASE_IRI}org/ORG_PARENT"]
    assert parents["object_iri"] == [f"{GRAPH_BASE_IRI}org/ORG_TX"]
    assert parents["experimental"] == [True]
    assert "experimental" in parents["coverage_note"][0]
    assert "incomplete" in parents["coverage_note"][0]
    sources = pq.read_table(graph_dir / "nodes" / "source.parquet").to_pydict()
    assert sources["source_id"] == ["example_water"]
    outside = pq.read_table(graph_dir / "reconciliation" / "state_outside_reference.parquet").to_pydict()
    assert "ORG_BC" in outside["entity_id"]
    states = pq.read_table(graph_dir / "edges" / "in_state.parquet").to_pydict()
    assert "ORG_BC" not in states["subject_id"]
    assert pq.ParquetFile(graph_dir / "edges" / "operates_system.parquet").metadata.num_rows == 0
    assert pq.ParquetFile(graph_dir / "edges" / "located_in_county.parquet").metadata.num_rows == 0
    assert summary["node_rows"]["county_coverage"] == 2
    assert summary["edge_rows"]["serves_county"] == 1
    nt = write_ntriples(graph_dir)
    sample = (graph_dir / "graph.nt").read_text(encoding="utf-8")
    served_lines = [line for line in sample.splitlines() if "servesCounty" in line]
    assert len(served_lines) == 1
    assert "SYS_SERVED" in served_lines[0]
    assert "SYS_UNSERVED" not in served_lines[0]
    parsed = Graph()
    parsed.parse(data=sample, format="nt")
    assert NASTY in {str(value) for value in parsed.objects()}
    assert nt["type_counts"]["WaterSystem"] == 3
    assert nt["type_counts"]["UtilitySystem"] == 3
    assert nt["type_counts"]["CountyCoverage"] == 2


def test_travis_county_water_served_set_matches_gold():
    home = REPO / "data"
    gold = home / "gold" / "2026-Q4" / "system_county_coverage.parquet"
    if not gold.is_file():
        pytest.skip("Gold county coverage is not in the data directory")
    edge = home / "releases" / "2026Q4.1" / "graph" / "edges" / "serves_county.parquet"
    assert edge.is_file(), "Graph export has not been written"
    gold_ids, edge_ids = travis_served_ids(home, "2026-Q4", "2026Q4.1")
    assert gold_ids == edge_ids
    assert len(gold_ids) == 84
    assert TRAVIS_COUNTY_GEOID == "48453"
    assert forbidden_output_columns(home / "releases" / "2026Q4.1" / "graph") == []
    nt_path = home / "releases" / "2026Q4.1" / "graph" / "graph.nt"
    assert nt_path.is_file()
    lines: list[str] = []
    with nt_path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index == 10000:
                break
            lines.append(line)
    assert len(lines) == 10000
    parsed = Graph()
    parsed.parse(data="".join(lines), format="nt")
    assert len(parsed) == 10000


def _empty_graph(graph_dir: Path) -> None:
    (graph_dir / "nodes").mkdir(parents=True)
    (graph_dir / "edges").mkdir(parents=True)
    (graph_dir / "export_meta.json").write_text(
        '{"base_iri": "http://utilities.local/", "ontology_iri": "http://utilities.local/ontology/", "query_language": "SPARQL"}\n',
        encoding="utf-8",
    )
    for name, fields in EDGE_FIELDS.items():
        _write(graph_dir / "edges" / f"{name}.parquet", _empty_types(fields), [])


def _empty_types(fields: tuple[str, ...]) -> dict[str, pa.DataType]:
    types: dict[str, pa.DataType] = {}
    for name in fields:
        if name == "rdf_types":
            types[name] = pa.list_(pa.string())
        elif name in {"experimental", "is_served", "reviewed", "out_of_scope", "in_federal_registry", "is_best", "footprint_verified"}:
            types[name] = pa.bool_()
        elif name in {"confidence", "customers", "sales_mwh", "area_km2", "capacity_mw", "longitude", "latitude", "pop_share_of_county", "pop_share_of_system", "area_share"}:
            types[name] = pa.float64()
        elif name in {"population_served", "service_connections", "part_count", "unit_count", "pop20", "pop_in_area", "housing_in_area"}:
            types[name] = pa.int64()
        elif name in {"source_vintage_date", "as_of"}:
            types[name] = pa.date32()
        else:
            types[name] = pa.string()
    return types


def _write(path: Path, fields: dict[str, pa.DataType], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = [pa.array([row.get(name) for row in rows], type=dtype) for name, dtype in fields.items()]
    pq.write_table(pa.Table.from_arrays(arrays, names=list(fields)), path)


def _mini_inputs(home: Path, registry: Path) -> None:
    core = home / "core" / "2026-Q4"
    gold = home / "gold" / "2026-Q4"
    silver = home / "silver" / "2026-Q4"
    system_fields = _empty_types((
        "system_id", "sector", "name", "status", "system_type", "primary_state", "population_served",
        "service_connections", "customers", "sales_mwh", "owner_org_id", "operator_org_id",
        "in_federal_registry", "first_seen_release", "last_seen_release",
    ))
    systems = [
        _system("SYS_SERVED", "ORG_TX", "TX", "Served Water"),
        _system("SYS_UNSERVED", "ORG_TX", "TX", "Unserved Water"),
        _system("SYS_BC", "ORG_BC", "BC", "British Columbia Water"),
    ]
    _write(core / "system.parquet", system_fields, systems)
    null_system = dict(system_fields)
    null_system["population_served"] = pa.null()
    null_system["service_connections"] = pa.null()
    null_system["operator_org_id"] = pa.null()
    for name in ("electric_system.parquet", "wastewater_system.parquet", "gas_system.parquet"):
        fields = null_system if name.startswith("electric") else system_fields
        _write(core / name, fields, [])
    org_fields = _empty_types((
        "org_id", "name", "name_norm", "state", "owner_type", "owner_type_code",
        "government_unit_id", "sector", "source_id",
    ))
    orgs = [
        _org("ORG_TX", "TX"),
        _org("ORG_BC", "BC"),
        _org("ORG_PARENT", "TX"),
    ]
    _write(core / "organization.parquet", org_fields, orgs)
    for name in ("electric_organization.parquet", "wastewater_organization.parquet", "gas_organization.parquet"):
        _write(core / name, org_fields, [])
    area_fields = _empty_types((
        "service_area_id", "system_id", "sector", "zone_role", "source_id", "authority", "grain",
        "source_vintage_date", "is_best", "part_count", "area_km2", "footprint_verified", "licence",
    ))
    area = {
        "service_area_id": "AREA_1", "system_id": "SYS_SERVED", "sector": "water",
        "zone_role": "active_retail_service", "source_id": "example_water", "authority": "utility_direct",
        "grain": "service_area", "source_vintage_date": dt.date(2024, 1, 1), "is_best": True,
        "part_count": 1, "area_km2": 1.5, "footprint_verified": False, "licence": "public_domain",
    }
    water_area = dict(area_fields)
    water_area["geometry"] = pa.binary()
    _write(core / "service_area.parquet", water_area, [{**area, "geometry": b"not-exported"}])
    for name in ("wastewater_service_area.parquet", "gas_service_area.parquet"):
        _write(core / name, water_area, [])
    electric_attributes = dict(area_fields)
    electric_attributes["boundary_representation"] = pa.string()
    _write(core / "electric_service_area_attributes.parquet", electric_attributes, [])
    electric_geometry = dict(electric_attributes)
    electric_geometry["geometry"] = pa.binary()
    _write(core / "electric_service_area.parquet", electric_geometry, [])
    _write(core / "electric_system_state.parquet", {
        "system_id": pa.string(), "utility_id_eia": pa.int64(), "state": pa.string(),
        "customers": pa.float64(), "sales_mwh": pa.float64(), "report_date": pa.string(),
    }, [])
    facility_fields = _empty_types((
        "facility_id", "sector", "facility_type", "name", "name_norm", "state", "owner_name", "status",
        "capacity_mw", "unit_count", "source_id", "source_layer", "source_feature_id", "licence",
        "longitude", "latitude",
    ))
    facility_fields["geometry_wkb"] = pa.binary()
    _write(core / "facility.parquet", facility_fields, [{
        "facility_id": "FAC_1", "sector": "water", "facility_type": "Treatment Plant", "name": NASTY,
        "name_norm": "say hello", "state": "TX", "owner_name": "Example", "status": "active",
        "capacity_mw": None, "unit_count": 1, "source_id": "example_water", "source_layer": "plants",
        "source_feature_id": "1", "licence": "public_domain", "longitude": -97.7, "latitude": 30.3,
        "geometry_wkb": b"not-exported",
    }])
    _write(core / "facility_county.parquet", _empty_types(("subject_id", "county_geoid", "subject_class")), [])
    _write(core / "place_county.parquet", _empty_types(("subject_id", "county_geoid", "subject_class")), [])
    relationship_fields = _empty_types(RELATIONSHIP_COLUMNS)
    note = "out_sec10k__parents_and_subsidiaries is experimental and incomplete. It is not a complete parent map."
    _write(core / "organization_relationship.parquet", relationship_fields, [
        _relationship("REL_PARENT", "parent", "ORG_TX", "ORG_PARENT", True, note),
        _relationship("REL_MISSING", "parent", None, None, True, note),
        _relationship("REL_GOV", "same_government", "ORG_TX", "ORG_BC", False, "Shared govid."),
    ])
    coverage_fields = _empty_types((
        "system_id", "county_geoid", "state", "sector", "pop_in_area", "housing_in_area",
        "pop_share_of_county", "pop_share_of_system", "area_share", "evidence", "authority",
        "is_served", "licence", "source_id", "in_federal_registry",
    ))
    _write(gold / "system_county_coverage.parquet", coverage_fields, [
        _coverage("SYS_SERVED", True, 0.2, "polygon", "utility_direct"),
        _coverage("SYS_UNSERVED", False, None, "tabular", None),
    ])
    _write(gold / "electric_system_county_coverage.parquet", coverage_fields, [])
    _write(gold / "wastewater_system_county_coverage.parquet", coverage_fields, [])
    _write(gold / "gas_system_county_coverage.parquet", coverage_fields, [])
    _write(silver / "ref_state.parquet", _empty_types(("state", "geoid", "usps", "name", "pop20")), [
        {"state": "48", "geoid": "48", "usps": "TX", "name": "Texas", "pop20": 100},
    ])
    _write(silver / "ref_county.parquet", _empty_types(("county_geoid", "state", "countyfp", "name", "namelsad", "pop20")), [
        {"county_geoid": "48453", "state": "48", "countyfp": "453", "name": "Travis", "namelsad": "Travis County", "pop20": 100},
    ])
    _write(silver / "ref_place.parquet", _empty_types(("place_geoid", "state", "placefp", "name", "namelsad", "pop20")), [
        {"place_geoid": "4805000", "state": "48", "placefp": "05000", "name": "Austin", "namelsad": "Austin city", "pop20": 100},
    ])
    registry.mkdir()
    (registry / "sources.yaml").write_text(
        """sources:
- source_id: example_water
  publisher: Example Publisher
  driver: http
  url: "https://example.local/water"
  cadence: annual
  licence: public_domain
  redistribution: shareable
  reviewed: true
  out_of_scope: true
  paths:
  - example/water.csv
  notes: "Reviewed source: drinking water"
- source_id: example_draft
  reviewed: false
  notes: "Draft source: keep out"
""",
        encoding="utf-8",
    )


def _system(system_id: str, owner: str, state: str, name: str) -> dict[str, object]:
    return {
        "system_id": system_id, "sector": "water", "name": name, "status": "active", "system_type": "CWS",
        "primary_state": state, "population_served": 10, "service_connections": 1, "customers": None,
        "sales_mwh": None, "owner_org_id": owner, "operator_org_id": None, "in_federal_registry": True,
        "first_seen_release": "2026-Q4", "last_seen_release": "2026-Q4",
    }


def _org(org_id: str, state: str) -> dict[str, object]:
    return {
        "org_id": org_id, "name": org_id, "name_norm": org_id.lower(), "state": state, "owner_type": "local",
        "owner_type_code": "L", "government_unit_id": None, "sector": "water", "source_id": "example_water",
    }


def _relationship(identifier: str, kind: str, child: str | None, parent: str | None, experimental: bool, note: str) -> dict[str, object]:
    return {
        "relationship_id": identifier, "relationship_type": kind, "subject_org_id": child, "related_org_id": parent,
        "subject_name": child, "related_name": parent, "subject_sector": "water", "related_sector": "water",
        "subject_utility_id": None, "related_utility_id": None, "govid": None, "confidence": 0.5,
        "source_id": "example_water", "as_of": dt.date(2023, 10, 1), "experimental": experimental, "coverage_note": note,
    }


def _coverage(system_id: str, served: bool, share: float | None, evidence: str, authority: str | None) -> dict[str, object]:
    return {
        "system_id": system_id, "county_geoid": "48453", "state": "48", "sector": "water",
        "pop_in_area": 200 if served else 1, "housing_in_area": 10, "pop_share_of_county": share,
        "pop_share_of_system": share, "area_share": share, "evidence": evidence, "authority": authority,
        "is_served": served, "licence": "public_domain", "source_id": "example_water", "in_federal_registry": True,
    }
