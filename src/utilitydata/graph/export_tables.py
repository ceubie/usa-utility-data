"""Write node and edge tables for the SPARQL export.

Derived county coverage is read from Gold. The tables do not include geometry,
block coverage, monthly series, or individual violations.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from utilitydata.core.config import DEFAULT_QUARTER, GRAPH_BASE_IRI
from utilitydata.core.schema import (
    ORGANIZATION_COLUMNS,
    SERVICE_AREA_COLUMNS,
    SYSTEM_COLUMNS,
)
from utilitydata.cross.schema import FACILITY_COLUMNS, RELATIONSHIP_COLUMNS
from utilitydata.gold.schema import COUNTY_COVERAGE_COLUMNS, TRAVIS_COUNTY_GEOID
from utilitydata.graph.literals import entity_iri, require_base
from utilitydata.graph.ontology import write_assembler, write_ontology
from utilitydata.graph.spec import (
    COUNTY_FIELDS,
    COVERAGE_FIELDS,
    EDGE_FIELDS,
    EXCLUDED_EXPORT_COLUMNS,
    FACILITY_FIELDS,
    FIELD_SQL,
    FORBIDDEN_OUTPUT_MARKERS,
    NODE_FIELDS,
    NOT_EXPORTED,
    ORGANIZATION_FIELDS,
    PLACE_FIELDS,
    SECTOR_CLASSES,
    SERVICE_AREA_FIELDS,
    STATE_FIELDS,
    SYSTEM_FIELDS,
    sector_class_name,
)
from utilitydata.pipeline import release_dir, validate_release_id, writable_release
from utilitydata.registry import Source, load_registry

_QUARTER = re.compile(r"[0-9]{4}-Q[1-4]")
_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")
_SYSTEM_FILES = (
    "system.parquet",
    "electric_system.parquet",
    "wastewater_system.parquet",
    "gas_system.parquet",
)
_ORG_FILES = (
    "organization.parquet",
    "electric_organization.parquet",
    "wastewater_organization.parquet",
    "gas_organization.parquet",
)
_AREA_FILES = (
    ("service_area.parquet", "service_area.parquet"),
    ("electric_service_area_attributes.parquet", "electric_service_area.parquet"),
    ("wastewater_service_area.parquet", "wastewater_service_area.parquet"),
    ("gas_service_area.parquet", "gas_service_area.parquet"),
)
_SYSTEM_STATE_USED = ("system_id", "state")
_SYSTEM_STATE_RETAINED = ("utility_id_eia", "customers", "sales_mwh", "report_date")
_SERVICE_REQUIRED = tuple(name for name in SERVICE_AREA_COLUMNS if name not in EXCLUDED_EXPORT_COLUMNS)


def export_graph(
    home: Path,
    repository_root: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
    release_id: str,
    registry_dir: Path = Path("registry/sources"),
    base: str = GRAPH_BASE_IRI,
) -> dict[str, object]:
    """Write the query-language-neutral graph tables under the release directory."""
    checked = require_base(base)
    if not _QUARTER.fullmatch(quarter):
        raise ValueError("Quarter has an unexpected form")
    validate_release_id(release_id)
    _require_contract_alignment()
    release = writable_release(home, release_id)
    core = home / "core" / quarter
    gold = home / "gold" / quarter
    silver = home / "silver" / quarter
    _require_inputs(core, gold, silver)
    sources = load_registry(registry_dir, require_reviewed=False)
    staging = release / ".graph-staging"
    if staging.exists():
        shutil.rmtree(staging)
    for folder in ("nodes", "edges", "reconciliation"):
        (staging / folder).mkdir(parents=True)
    ontology = write_ontology(repository_root, checked)
    assembler = write_assembler(repository_root)
    shutil.copyfile(ontology, staging / "ontology.ttl")
    connection = duckdb.connect()
    try:
        _create_inputs(connection, core, gold, silver, sources, checked)
        _validate_inputs(connection, sources)
        counts = _write_outputs(connection, staging, checked)
        _validate_outputs(connection, counts)
        manifest = _manifest(counts, checked, quarter, release_id)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (staging / "export_meta.json").write_text(
            json.dumps(
                {
                    "base_iri": checked,
                    "ontology_iri": f"{checked}ontology/",
                    "query_language": "SPARQL",
                    "store": "Apache Jena Fuseki",
                    "assembler": assembler.name,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    connection.close()
    graph = release / "graph"
    if graph.exists():
        shutil.rmtree(graph)
    staging.rename(graph)
    print(f"graph tables: {graph.relative_to(home).as_posix()}", flush=True)
    return manifest


def travis_served_ids(home: Path, quarter: str, release_id: str) -> tuple[set[str], set[str]]:
    """Return the Gold and servesCounty system ids for Travis County water."""
    edge = release_dir(home, release_id) / "graph" / "edges" / "serves_county.parquet"
    gold = home / "gold" / quarter / "system_county_coverage.parquet"
    connection = duckdb.connect()
    try:
        gold_ids = _id_set(connection, gold, "AND is_served AND sector = 'water'")
        edge_ids = _id_set(connection, edge, "AND sector = 'water'")
    finally:
        connection.close()
    return gold_ids, edge_ids


def forbidden_output_columns(graph_dir: Path) -> list[str]:
    """Return geometry or block-coverage columns in node and edge tables."""
    found: list[str] = []
    for folder in ("nodes", "edges"):
        for path in sorted((graph_dir / folder).glob("*.parquet")):
            for name in pq.ParquetFile(path).schema_arrow.names:
                lowered = name.casefold()
                if any(marker in lowered for marker in FORBIDDEN_OUTPUT_MARKERS):
                    found.append(f"{folder}/{path.name}.{name}")
    return found


def _require_contract_alignment() -> None:
    if tuple(SYSTEM_COLUMNS) != SYSTEM_FIELDS:
        raise ValueError("System columns do not match the graph")
    if tuple(ORGANIZATION_COLUMNS) != ORGANIZATION_FIELDS:
        raise ValueError("Organization columns do not match the graph")
    if tuple(COUNTY_COVERAGE_COLUMNS) != COVERAGE_FIELDS:
        raise ValueError("County coverage columns do not match the graph")
    if _SERVICE_REQUIRED + ("boundary_representation",) != SERVICE_AREA_FIELDS:
        raise ValueError("Service area columns do not match the graph")
    facility = tuple(name for name in FACILITY_COLUMNS if name not in EXCLUDED_EXPORT_COLUMNS)
    if facility != FACILITY_FIELDS:
        raise ValueError("Facility columns do not match the graph")
    if "geometry" not in SERVICE_AREA_COLUMNS or "geometry_wkb" not in FACILITY_COLUMNS:
        raise ValueError("Geometry columns are no longer named on the source tables")


def _require_inputs(core: Path, gold: Path, silver: Path) -> None:
    required = [core / name for name in _SYSTEM_FILES + _ORG_FILES]
    required.extend(core / name for pair in _AREA_FILES for name in pair)
    required.extend(
        [
            core / "electric_system_state.parquet",
            core / "facility.parquet",
            core / "organization_relationship.parquet",
            gold / "system_county_coverage.parquet",
            gold / "electric_system_county_coverage.parquet",
            gold / "wastewater_system_county_coverage.parquet",
            gold / "gas_system_county_coverage.parquet",
            silver / "ref_county.parquet",
            silver / "ref_state.parquet",
            silver / "ref_place.parquet",
            core / "facility_county.parquet",
            core / "place_county.parquet",
        ]
    )
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"Graph input is missing: {missing[0]}")


def _create_inputs(
    connection: duckdb.DuckDBPyConnection,
    core: Path,
    gold: Path,
    silver: Path,
    sources: list[Source],
    base: str,
) -> None:
    _view_union(connection, "system_rows", [core / name for name in _SYSTEM_FILES], SYSTEM_FIELDS, "systems")
    _view_union(connection, "organization_rows", [core / name for name in _ORG_FILES], ORGANIZATION_FIELDS, "organizations")
    _view_areas(connection, core)
    _view_exact(connection, "facility_rows", core / "facility.parquet", FACILITY_FIELDS, "facilities", ("geometry_wkb",))
    _view_exact(connection, "relationship_rows", core / "organization_relationship.parquet", RELATIONSHIP_COLUMNS, "relationships")
    _view_union(
        connection,
        "coverage_rows",
        [
            gold / "system_county_coverage.parquet",
            gold / "electric_system_county_coverage.parquet",
            gold / "wastewater_system_county_coverage.parquet",
            gold / "gas_system_county_coverage.parquet",
        ],
        COVERAGE_FIELDS,
        "county coverage",
    )
    _view_exact(connection, "county_rows", silver / "ref_county.parquet", COUNTY_FIELDS, "counties")
    _view_exact(connection, "state_rows", silver / "ref_state.parquet", STATE_FIELDS, "states")
    _view_exact(connection, "place_rows", silver / "ref_place.parquet", PLACE_FIELDS, "places")
    _view_exact(
        connection,
        "facility_county_rows",
        core / "facility_county.parquet",
        ("subject_id", "county_geoid", "subject_class"),
        "facility counties",
    )
    _view_exact(
        connection,
        "place_county_rows",
        core / "place_county.parquet",
        ("subject_id", "county_geoid", "subject_class"),
        "place counties",
    )
    state_file = core / "electric_system_state.parquet"
    state_schema = _require_names(
        state_file,
        _SYSTEM_STATE_USED,
        "electric system states",
        _SYSTEM_STATE_RETAINED,
    )
    used = ", ".join(_typed(state_schema, name) for name in _SYSTEM_STATE_USED)
    connection.execute(
        f"CREATE VIEW electric_system_state AS SELECT {used} FROM read_parquet({_sql_path(state_file)})"
    )
    _register_sources(connection, sources, base)
    _create_node_views(connection, base)


def _create_node_views(connection: duckdb.DuckDBPyConnection, base: str) -> None:
    literal = _sql_string(base)
    sector_class = _sector_case()
    connection.execute(
        f"""
        CREATE VIEW utility_system AS
        SELECT {literal} || 'system/' || system_id AS iri,
               list_value('UtilitySystem', {sector_class}) AS rdf_types,
               {", ".join(SYSTEM_FIELDS)}
        FROM system_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW organization AS
        SELECT {literal} || 'org/' || org_id AS iri,
               list_value('Organization') AS rdf_types,
               {", ".join(ORGANIZATION_FIELDS)}
        FROM organization_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW service_area AS
        SELECT {literal} || 'area/' || service_area_id AS iri,
               list_value('ServiceArea') AS rdf_types,
               {", ".join(SERVICE_AREA_FIELDS)}
        FROM area_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW facility AS
        SELECT {literal} || 'facility/' || facility_id AS iri,
               list_value('Facility') AS rdf_types,
               {", ".join(FACILITY_FIELDS)}
        FROM facility_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW county AS
        SELECT {literal} || 'county/' || county_geoid AS iri,
               list_value('County') AS rdf_types,
               {", ".join(COUNTY_FIELDS)}
        FROM county_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW state AS
        SELECT {literal} || 'state/' || usps AS iri,
               list_value('State') AS rdf_types,
               {", ".join(STATE_FIELDS)}
        FROM state_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW place AS
        SELECT {literal} || 'place/' || place_geoid AS iri,
               list_value('Place') AS rdf_types,
               {", ".join(PLACE_FIELDS)}
        FROM place_rows
        """
    )
    connection.execute(
        f"""
        CREATE VIEW county_coverage AS
        SELECT {literal} || 'coverage/' || system_id || '/' || county_geoid AS iri,
               list_value('CountyCoverage') AS rdf_types,
               {literal} || 'system/' || system_id AS system_iri,
               {literal} || 'county/' || county_geoid AS county_iri,
               {", ".join(COVERAGE_FIELDS)}
        FROM coverage_rows
        """
    )


def _validate_inputs(connection: duckdb.DuckDBPyConnection, sources: list[Source]) -> None:
    _fail(connection, f"""
        SELECT system_id, sector FROM system_rows
        WHERE system_id IS NULL OR NOT regexp_matches(system_id, '^[A-Za-z0-9_]+$')
           OR {_sector_case()} IS NULL
        LIMIT 1
    """, "System id or sector cannot be exported")
    _fail(connection, """
        SELECT system_id FROM system_rows GROUP BY 1 HAVING count(*) > 1 LIMIT 1
    """, "System id is duplicated")
    _fail(connection, """
        SELECT org_id, sector FROM organization_rows
        WHERE org_id IS NULL OR NOT regexp_matches(org_id, '^[A-Za-z0-9_]+$')
        LIMIT 1
    """, "Organization id cannot be exported")
    _fail(connection, "SELECT org_id FROM organization_rows GROUP BY 1 HAVING count(*) > 1 LIMIT 1", "Organization id is duplicated")
    _fail(connection, """
        SELECT service_area_id FROM area_rows
        WHERE service_area_id IS NULL OR system_id IS NULL
           OR NOT regexp_matches(service_area_id, '^[A-Za-z0-9_]+$')
        LIMIT 1
    """, "Service area id cannot be exported")
    _fail(connection, """
        SELECT service_area_id FROM area_rows GROUP BY 1 HAVING count(*) > 1 LIMIT 1
    """, "Service area id is duplicated")
    _fail(connection, """
        SELECT a.service_area_id, a.system_id
        FROM area_rows a LEFT JOIN system_rows s USING (system_id)
        WHERE s.system_id IS NULL LIMIT 1
    """, "Service area system is missing")
    _fail(connection, """
        SELECT facility_id FROM facility_rows
        WHERE facility_id IS NULL OR NOT regexp_matches(facility_id, '^[A-Za-z0-9_]+$')
        LIMIT 1
    """, "Facility id cannot be exported")
    _fail(connection, "SELECT facility_id FROM facility_rows GROUP BY 1 HAVING count(*) > 1 LIMIT 1", "Facility id is duplicated")
    _fail(connection, """
        SELECT facility_id, sector FROM facility_rows WHERE sector IS NULL LIMIT 1
    """, "Facility sector is missing")
    for sector_sql in (
        "SELECT sector FROM system_rows",
        "SELECT sector FROM organization_rows",
        "SELECT sector FROM facility_rows WHERE sector IS NOT NULL",
        "SELECT sector FROM coverage_rows",
    ):
        rows = connection.execute(f"SELECT DISTINCT sector FROM ({sector_sql}) WHERE sector IS NOT NULL").fetchall()
        for (sector,) in rows:
            sector_class_name(str(sector))
    _fail(connection, """
        SELECT county_geoid FROM county_rows
        WHERE county_geoid IS NULL OR NOT regexp_matches(county_geoid, '^[0-9]{5}$')
        LIMIT 1
    """, "County GEOID cannot be exported")
    _fail(connection, "SELECT county_geoid FROM county_rows GROUP BY 1 HAVING count(*) > 1 LIMIT 1", "County GEOID is duplicated")
    _fail(connection, """
        SELECT place_geoid FROM place_rows
        WHERE place_geoid IS NULL OR NOT regexp_matches(place_geoid, '^[A-Za-z0-9_]+$')
        LIMIT 1
    """, "Place GEOID cannot be exported")
    _fail(connection, """
        SELECT usps FROM state_rows
        WHERE usps IS NULL OR NOT regexp_matches(usps, '^[A-Z]{2}$')
           OR state IS NULL OR NOT regexp_matches(state, '^[0-9]{2}$')
        LIMIT 1
    """, "State code cannot be exported")
    _fail(connection, "SELECT usps FROM state_rows GROUP BY 1 HAVING count(*) > 1 LIMIT 1", "State USPS code is duplicated")
    _fail(connection, """
        SELECT c.county_geoid, c.state FROM county_rows c
        LEFT JOIN state_rows s ON c.state = s.state
        WHERE s.state IS NULL LIMIT 1
    """, "County state is missing from the state table")
    _fail(connection, """
        SELECT p.place_geoid, p.state FROM place_rows p
        LEFT JOIN state_rows s ON p.state = s.state
        WHERE s.state IS NULL LIMIT 1
    """, "Place state is missing from the state table")
    _fail(connection, """
        SELECT system_id, county_geoid, sector FROM coverage_rows
        WHERE system_id IS NULL OR county_geoid IS NULL OR sector IS NULL OR is_served IS NULL
           OR evidence IS NULL OR source_id IS NULL
           OR NOT regexp_matches(system_id, '^[A-Za-z0-9_]+$')
           OR NOT regexp_matches(county_geoid, '^[0-9]{5}$')
        LIMIT 1
    """, "County coverage row cannot be exported")
    _fail(connection, """
        SELECT system_id, county_geoid FROM coverage_rows
        GROUP BY 1, 2 HAVING count(*) > 1 LIMIT 1
    """, "County coverage key is duplicated")
    _fail(connection, """
        SELECT c.system_id, c.county_geoid
        FROM coverage_rows c
        LEFT JOIN system_rows s USING (system_id)
        LEFT JOIN county_rows county ON c.county_geoid = county.county_geoid
        WHERE s.system_id IS NULL OR county.county_geoid IS NULL
        LIMIT 1
    """, "County coverage system or county is missing")
    _fail(connection, """
        SELECT s.system_id, s.owner_org_id
        FROM system_rows s LEFT JOIN organization_rows o ON s.owner_org_id = o.org_id
        WHERE s.owner_org_id IS NOT NULL AND o.org_id IS NULL LIMIT 1
    """, "Owner organization is missing")
    _fail(connection, """
        SELECT s.system_id, s.operator_org_id
        FROM system_rows s LEFT JOIN organization_rows o ON s.operator_org_id = o.org_id
        WHERE s.operator_org_id IS NOT NULL AND o.org_id IS NULL LIMIT 1
    """, "Operator organization is missing")
    _fail(connection, """
        SELECT r.relationship_id
        FROM relationship_rows r
        LEFT JOIN organization_rows child ON r.subject_org_id = child.org_id
        LEFT JOIN organization_rows parent ON r.related_org_id = parent.org_id
        WHERE r.relationship_type = 'parent'
          AND r.subject_org_id IS NOT NULL AND r.related_org_id IS NOT NULL
          AND (child.org_id IS NULL OR parent.org_id IS NULL)
        LIMIT 1
    """, "Parent relationship organization is missing")
    _fail(connection, """
        SELECT relationship_type, count(*) FROM relationship_rows
        WHERE relationship_type NOT IN ('parent', 'same_government')
        GROUP BY 1 LIMIT 1
    """, "Relationship type is not accounted for")
    _fail(connection, """
        SELECT relationship_id FROM relationship_rows
        WHERE relationship_type = 'parent'
          AND subject_org_id IS NOT NULL AND related_org_id IS NOT NULL
          AND (coverage_note IS NULL OR experimental IS NULL
               OR NOT regexp_matches(relationship_id, '^[A-Za-z0-9_]+$'))
        LIMIT 1
    """, "Exportable parent relationship is missing its label or id")
    _fail(connection, """
        SELECT e.system_id, e.state
        FROM electric_system_state e
        LEFT JOIN state_rows s ON e.state = s.usps OR lpad(e.state, 2, '0') = s.state
        WHERE e.state IS NOT NULL AND s.usps IS NULL
        LIMIT 1
    """, "Electric system state is outside the state table")
    _fail(connection, """
        SELECT e.system_id
        FROM electric_system_state e
        LEFT JOIN system_rows s ON e.system_id = s.system_id
        WHERE s.system_id IS NULL
        LIMIT 1
    """, "Electric system state does not match a system")
    _cited_sources(connection, sources)


def _cited_sources(connection: duckdb.DuckDBPyConnection, sources: list[Source]) -> None:
    rows = connection.execute(
        """
        SELECT DISTINCT source_id FROM (
            SELECT source_id FROM organization_rows
            UNION ALL SELECT source_id FROM area_rows
            UNION ALL SELECT source_id FROM facility_rows
            UNION ALL SELECT source_id FROM coverage_rows
            UNION ALL SELECT source_id FROM relationship_rows
                WHERE relationship_type = 'parent'
                  AND subject_org_id IS NOT NULL AND related_org_id IS NOT NULL
        ) WHERE source_id IS NOT NULL
        """
    ).fetchall()
    allowed = {source.source_id for source in sources if source.reviewed or _reference_source(source)}
    drafts = {source.source_id for source in sources if source.source_id not in allowed}
    cited = [str(row[0]) for row in rows]
    draft_cited = sorted(source_id for source_id in cited if source_id in drafts)
    if draft_cited:
        raise ValueError(f"Draft source is in a graph input: {draft_cited[0]}")
    unknown = sorted(source_id for source_id in cited if source_id not in allowed)
    if unknown:
        raise ValueError(f"Unknown source is in a graph input: {unknown[0]}")
    nulls = _count(connection, """
        SELECT count(*) FROM (
            SELECT source_id FROM organization_rows
            UNION ALL SELECT source_id FROM area_rows
            UNION ALL SELECT source_id FROM facility_rows
            UNION ALL SELECT source_id FROM coverage_rows
        ) WHERE source_id IS NULL
    """)
    if nulls:
        raise ValueError("A graph input source_id is null")


def _write_outputs(connection: duckdb.DuckDBPyConnection, staging: Path, base: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in NODE_FIELDS:
        counts[f"node:{name}"] = _copy(connection, f"SELECT {', '.join(NODE_FIELDS[name])} FROM {name if name != 'utility_system' else 'utility_system'}", staging / "nodes" / f"{name}.parquet", NODE_FIELDS[name], name)
    _write_edges(connection, staging, base)
    for name in EDGE_FIELDS:
        counts[f"edge:{name}"] = _rows(staging / "edges" / f"{name}.parquet")
    counts["reconciliation:parent_unresolved"] = _copy(
        connection,
        """
        SELECT relationship_id,
               CASE
                   WHEN subject_org_id IS NULL AND related_org_id IS NULL THEN 'missing_both_orgs'
                   WHEN related_org_id IS NULL THEN 'missing_parent_org'
                   ELSE 'missing_subsidiary_org'
               END AS reason,
               experimental, coverage_note, subject_org_id, related_org_id, source_id
        FROM relationship_rows
        WHERE relationship_type = 'parent'
          AND (subject_org_id IS NULL OR related_org_id IS NULL)
        """,
        staging / "reconciliation" / "parent_unresolved.parquet",
        ("relationship_id", "reason", "experimental", "coverage_note", "subject_org_id", "related_org_id", "source_id"),
        "parent unresolved",
    )
    counts["reconciliation:same_government"] = _copy(
        connection,
        """
        SELECT relationship_id, subject_org_id, related_org_id, govid, source_id,
               coverage_note, experimental, 'not_a_listed_graph_link' AS reason
        FROM relationship_rows
        WHERE relationship_type = 'same_government'
        """,
        staging / "reconciliation" / "same_government.parquet",
        ("relationship_id", "subject_org_id", "related_org_id", "govid", "source_id", "coverage_note", "experimental", "reason"),
        "same government",
    )
    counts["reconciliation:state_outside_reference"] = _copy(
        connection,
        """
        SELECT 'utility_system' AS entity_class, system_id AS entity_id, primary_state AS state_code
        FROM system_rows s
        LEFT JOIN state_rows st ON s.primary_state = st.usps OR lpad(s.primary_state, 2, '0') = st.state
        WHERE s.primary_state IS NOT NULL AND st.usps IS NULL
        UNION ALL
        SELECT 'organization', org_id, o.state
        FROM organization_rows o
        LEFT JOIN state_rows st ON o.state = st.usps OR lpad(o.state, 2, '0') = st.state
        WHERE o.state IS NOT NULL AND st.usps IS NULL
        UNION ALL
        SELECT 'facility', facility_id, f.state
        FROM facility_rows f
        LEFT JOIN state_rows st ON f.state = st.usps OR lpad(f.state, 2, '0') = st.state
        WHERE f.state IS NOT NULL AND st.usps IS NULL
        """,
        staging / "reconciliation" / "state_outside_reference.parquet",
        ("entity_class", "entity_id", "state_code"),
        "state outside reference",
    )
    _register_output_views(connection, staging)
    return counts


def _write_edges(connection: duckdb.DuckDBPyConnection, staging: Path, base: str) -> None:
    literal = _sql_string(base)
    edges = staging / "edges"
    _copy(connection, """
        SELECT o.iri AS subject_iri, s.iri AS object_iri, 'ownsSystem' AS predicate,
               s.owner_org_id AS org_id, s.system_id
        FROM utility_system s
        JOIN organization o ON s.owner_org_id = o.org_id
        WHERE s.owner_org_id IS NOT NULL
    """, edges / "owns_system.parquet", EDGE_FIELDS["owns_system"], "ownsSystem")
    _copy(connection, """
        SELECT o.iri AS subject_iri, s.iri AS object_iri, 'operatesSystem' AS predicate,
               s.operator_org_id AS org_id, s.system_id
        FROM utility_system s
        JOIN organization o ON s.operator_org_id = o.org_id
        WHERE s.operator_org_id IS NOT NULL
    """, edges / "operates_system.parquet", EDGE_FIELDS["operates_system"], "operatesSystem")
    _copy(connection, f"""
        SELECT parent.iri AS subject_iri, child.iri AS object_iri, 'parentOf' AS predicate,
               {literal} || 'relationship/' || r.relationship_id AS relationship_iri,
               r.related_org_id AS parent_org_id, r.subject_org_id AS child_org_id,
               r.relationship_id, r.experimental, r.coverage_note, r.confidence,
               CAST(r.as_of AS DATE) AS as_of, r.source_id
        FROM relationship_rows r
        JOIN organization parent ON r.related_org_id = parent.org_id
        JOIN organization child ON r.subject_org_id = child.org_id
        WHERE r.relationship_type = 'parent'
          AND r.subject_org_id IS NOT NULL AND r.related_org_id IS NOT NULL
    """, edges / "parent_of.parquet", EDGE_FIELDS["parent_of"], "parentOf")
    _copy(connection, """
        SELECT s.iri AS subject_iri, a.iri AS object_iri, 'hasServiceArea' AS predicate,
               a.system_id, a.service_area_id
        FROM service_area a
        JOIN utility_system s ON a.system_id = s.system_id
    """, edges / "has_service_area.parquet", EDGE_FIELDS["has_service_area"], "hasServiceArea")
    _copy(connection, """
        SELECT subject_iri, object_iri, 'assertedBy' AS predicate, subject_id, source_id, subject_class
        FROM (
            SELECT o.iri AS subject_iri, src.iri AS object_iri, o.org_id AS subject_id,
                   o.source_id, 'organization' AS subject_class
            FROM organization o JOIN source src ON o.source_id = src.source_id
            UNION ALL
            SELECT a.iri, src.iri, a.service_area_id, a.source_id, 'service_area'
            FROM service_area a JOIN source src ON a.source_id = src.source_id
            UNION ALL
            SELECT f.iri, src.iri, f.facility_id, f.source_id, 'facility'
            FROM facility f JOIN source src ON f.source_id = src.source_id
            UNION ALL
            SELECT c.iri, src.iri, c.system_id || '/' || c.county_geoid, c.source_id, 'county_coverage'
            FROM county_coverage c JOIN source src ON c.source_id = src.source_id
            UNION ALL
            SELECT p.relationship_iri, src.iri, p.relationship_id, p.source_id, 'relationship'
            FROM read_parquet(?) p JOIN source src ON p.source_id = src.source_id
        )
    """.replace("read_parquet(?)", f"read_parquet({_sql_path(edges / 'parent_of.parquet')})"), edges / "asserted_by.parquet", EDGE_FIELDS["asserted_by"], "assertedBy")
    _copy(connection, """
        SELECT DISTINCT subject_iri, object_iri, predicate, subject_id, state_usps, subject_class FROM (
            SELECT s.iri AS subject_iri, st.iri AS object_iri, 'inState' AS predicate,
                   s.system_id AS subject_id, st.usps AS state_usps, 'utility_system' AS subject_class
            FROM utility_system s
            JOIN state st ON s.primary_state = st.usps OR lpad(s.primary_state, 2, '0') = st.state
            UNION ALL
            SELECT s.iri, st.iri, 'inState', e.system_id, st.usps, 'utility_system'
            FROM electric_system_state e
            JOIN utility_system s ON e.system_id = s.system_id
            JOIN state st ON e.state = st.usps OR lpad(e.state, 2, '0') = st.state
            UNION ALL
            SELECT o.iri, st.iri, 'inState', o.org_id, st.usps, 'organization'
            FROM organization o
            JOIN state st ON o.state = st.usps OR lpad(o.state, 2, '0') = st.state
            UNION ALL
            SELECT f.iri, st.iri, 'inState', f.facility_id, st.usps, 'facility'
            FROM facility f
            JOIN state st ON f.state = st.usps OR lpad(f.state, 2, '0') = st.state
            UNION ALL
            SELECT c.iri, st.iri, 'inState', c.county_geoid, st.usps, 'county'
            FROM county c JOIN state st ON c.state = st.state
            UNION ALL
            SELECT p.iri, st.iri, 'inState', p.place_geoid, st.usps, 'place'
            FROM place p JOIN state st ON p.state = st.state
        )
    """, edges / "in_state.parquet", EDGE_FIELDS["in_state"], "inState")
    _copy(connection, """
        SELECT f.iri AS subject_iri, c.iri AS object_iri, 'locatedInCounty' AS predicate,
               loc.subject_id, loc.county_geoid, 'facility' AS subject_class
        FROM facility_county_rows loc
        JOIN facility f ON loc.subject_id = f.facility_id
        JOIN county c ON loc.county_geoid = c.county_geoid
        WHERE loc.subject_class = 'facility'
        UNION ALL
        SELECT p.iri, c.iri, 'locatedInCounty', loc.subject_id, loc.county_geoid, 'place'
        FROM place_county_rows loc
        JOIN place p ON loc.subject_id = p.place_geoid
        JOIN county c ON loc.county_geoid = c.county_geoid
        WHERE loc.subject_class = 'place'
    """, edges / "located_in_county.parquet", EDGE_FIELDS["located_in_county"], "locatedInCounty")
    _copy(connection, """
        SELECT s.iri AS subject_iri, c.iri AS object_iri, 'servesCounty' AS predicate,
               cov.system_id, cov.county_geoid, cov.sector
        FROM county_coverage cov
        JOIN utility_system s ON cov.system_id = s.system_id
        JOIN county c ON cov.county_geoid = c.county_geoid
        WHERE cov.is_served
    """, edges / "serves_county.parquet", EDGE_FIELDS["serves_county"], "servesCounty")


def _validate_outputs(connection: duckdb.DuckDBPyConnection, counts: dict[str, int]) -> None:
    expected = {
        "node:utility_system": _count(connection, "SELECT count(*) FROM system_rows"),
        "node:organization": _count(connection, "SELECT count(*) FROM organization_rows"),
        "node:service_area": _count(connection, "SELECT count(*) FROM area_rows"),
        "node:facility": _count(connection, "SELECT count(*) FROM facility_rows"),
        "node:county": _count(connection, "SELECT count(*) FROM county_rows"),
        "node:state": _count(connection, "SELECT count(*) FROM state_rows"),
        "node:place": _count(connection, "SELECT count(*) FROM place_rows"),
        "node:source": _count(connection, "SELECT count(*) FROM source"),
        "node:county_coverage": _count(connection, "SELECT count(*) FROM coverage_rows"),
        "edge:has_service_area": _count(connection, "SELECT count(*) FROM area_rows"),
        "edge:serves_county": _count(connection, "SELECT count(*) FROM coverage_rows WHERE is_served"),
        "edge:owns_system": _count(connection, "SELECT count(*) FROM system_rows WHERE owner_org_id IS NOT NULL"),
        "edge:operates_system": _count(connection, "SELECT count(*) FROM system_rows WHERE operator_org_id IS NOT NULL"),
        "edge:located_in_county": _count(connection, """
            SELECT count(*) FROM (
                SELECT loc.subject_id, loc.county_geoid
                FROM facility_county_rows loc
                JOIN facility_rows f ON loc.subject_id = f.facility_id
                JOIN county_rows c ON loc.county_geoid = c.county_geoid
                WHERE loc.subject_class = 'facility'
                UNION ALL
                SELECT loc.subject_id, loc.county_geoid
                FROM place_county_rows loc
                JOIN place_rows p ON loc.subject_id = p.place_geoid
                JOIN county_rows c ON loc.county_geoid = c.county_geoid
                WHERE loc.subject_class = 'place'
            )
        """),
    }
    for name, value in expected.items():
        if counts[name] != value:
            raise ValueError(f"{name} has {counts[name]} rows, expected {value}")
    parent_rows = _count(connection, "SELECT count(*) FROM relationship_rows WHERE relationship_type = 'parent'")
    same_rows = _count(connection, "SELECT count(*) FROM relationship_rows WHERE relationship_type = 'same_government'")
    if counts["edge:parent_of"] + counts["reconciliation:parent_unresolved"] != parent_rows:
        raise ValueError("Parent relationships do not reconcile")
    if counts["reconciliation:same_government"] != same_rows:
        raise ValueError("Same-government relationships do not reconcile")
    if parent_rows + same_rows != _count(connection, "SELECT count(*) FROM relationship_rows"):
        raise ValueError("Organization relationships do not reconcile")
    mismatch = _count(connection, """
        SELECT count(*) FROM (
            SELECT system_id, county_geoid, sector FROM serves_edge
            EXCEPT
            SELECT system_id, county_geoid, sector FROM coverage_rows WHERE is_served
        )
    """)
    reverse = _count(connection, """
        SELECT count(*) FROM (
            SELECT system_id, county_geoid, sector FROM coverage_rows WHERE is_served
            EXCEPT
            SELECT system_id, county_geoid, sector FROM serves_edge
        )
    """)
    if mismatch or reverse:
        raise ValueError("servesCounty does not match served county coverage")
    false_edge = _count(connection, """
        SELECT count(*) FROM serves_edge e
        JOIN coverage_rows c USING (system_id, county_geoid)
        WHERE NOT c.is_served
    """)
    if false_edge:
        raise ValueError("servesCounty contains a row whose is_served is false")
    _fail(connection, """
        SELECT relationship_id FROM parent_edge
        WHERE experimental AND (
            coverage_note IS NULL OR coverage_note NOT LIKE '%experimental%'
            OR coverage_note NOT LIKE '%incomplete%'
        )
        LIMIT 1
    """, "Experimental parent rows must stay labeled experimental and incomplete")
    _account_states(connection, counts)


def _account_states(connection: duckdb.DuckDBPyConnection, counts: dict[str, int]) -> None:
    for entity, total_sql, state_sql, state_column in (
        ("utility_system", "SELECT count(*) FROM system_rows", "SELECT count(*) FROM system_rows WHERE primary_state IS NOT NULL", "primary_state"),
        ("organization", "SELECT count(*) FROM organization_rows", "SELECT count(*) FROM organization_rows WHERE state IS NOT NULL", "state"),
        ("facility", "SELECT count(*) FROM facility_rows", "SELECT count(*) FROM facility_rows WHERE state IS NOT NULL", "state"),
    ):
        outside = _count(connection, f"SELECT count(*) FROM state_outside WHERE entity_class = '{entity}'")
        with_state = _count(connection, state_sql)
        linked_codes = _count(
            connection,
            f"""
            SELECT count(*) FROM {entity if entity != 'utility_system' else 'system'}_rows s
            JOIN state st ON s.{state_column} = st.usps OR lpad(s.{state_column}, 2, '0') = st.state
            """,
        )
        if linked_codes + outside != with_state:
            raise ValueError(f"{entity} states do not reconcile")
        if _count(connection, total_sql) != counts[f"node:{entity}"]:
            raise ValueError(f"{entity} node count changed")
    if _count(connection, "SELECT count(*) FROM county_rows") != _count(
        connection, "SELECT count(*) FROM in_state_edge WHERE subject_class = 'county'"
    ):
        raise ValueError("County inState rows do not match counties")
    if _count(connection, "SELECT count(*) FROM place_rows") != _count(
        connection, "SELECT count(*) FROM in_state_edge WHERE subject_class = 'place'"
    ):
        raise ValueError("Place inState rows do not match places")


def _manifest(counts: dict[str, int], base: str, quarter: str, release_id: str) -> dict[str, object]:
    return {
        "release": release_id,
        "quarter": quarter,
        "base_iri": base,
        "query_language": "SPARQL",
        "store": "Apache Jena Fuseki",
        "node_rows": {name: counts[f"node:{name}"] for name in NODE_FIELDS},
        "edge_rows": {name: counts[f"edge:{name}"] for name in EDGE_FIELDS},
        "reconciliation": {
            "parent_unresolved": counts["reconciliation:parent_unresolved"],
            "same_government": counts["reconciliation:same_government"],
            "state_outside_reference": counts["reconciliation:state_outside_reference"],
        },
        "travis_county_geoid": TRAVIS_COUNTY_GEOID,
        "served_matches_gold": True,
        "not_exported": list(NOT_EXPORTED),
        "parent_label": "SEC parent rows are experimental and incomplete and are not verified.",
    }


def _view_union(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    paths: list[Path],
    columns: tuple[str, ...],
    label: str,
) -> None:
    branches: list[str] = []
    for path in paths:
        schema = _require_names(path, columns, f"{label} {path.name}")
        exprs = [_typed(schema, column) for column in columns]
        branches.append(f"SELECT {', '.join(exprs)} FROM read_parquet({_sql_path(path)})")
    connection.execute(f"CREATE VIEW {name} AS " + " UNION ALL ".join(branches))


def _view_exact(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    path: Path,
    columns: tuple[str, ...],
    label: str,
    allowed_extra: tuple[str, ...] = (),
) -> None:
    required = tuple(name for name in columns if name not in allowed_extra)
    schema = _require_names(path, required, label, allowed_extra)
    for extra in allowed_extra:
        if extra not in schema.names:
            raise ValueError(f"{label} is missing columns: {extra}")
    exprs = [_typed(schema, column) for column in required]
    connection.execute(f"CREATE VIEW {name} AS SELECT {', '.join(exprs)} FROM read_parquet({_sql_path(path)})")


def _view_areas(connection: duckdb.DuckDBPyConnection, core: Path) -> None:
    branches: list[str] = []
    for attributes, geometry in _AREA_FILES:
        attribute_path = core / attributes
        geometry_path = core / geometry
        schema = _require_names(attribute_path, _SERVICE_REQUIRED, attributes, ("geometry", "boundary_representation"))
        geometry_schema = _require_names(geometry_path, _SERVICE_REQUIRED, geometry, ("geometry", "boundary_representation"))
        if "geometry" not in geometry_schema.names:
            raise ValueError(f"{geometry} is missing columns: geometry")
        if pq.ParquetFile(attribute_path).metadata.num_rows != pq.ParquetFile(geometry_path).metadata.num_rows:
            raise ValueError(f"{attributes} row count does not match {geometry}")
        exprs = [_typed(schema, column) for column in _SERVICE_REQUIRED]
        if "boundary_representation" in schema.names:
            exprs.append(_typed(schema, "boundary_representation"))
        else:
            exprs.append("CAST(NULL AS VARCHAR) AS boundary_representation")
        branches.append(f"SELECT {', '.join(exprs)} FROM read_parquet({_sql_path(attribute_path)})")
    connection.execute("CREATE VIEW area_rows AS " + " UNION ALL ".join(branches))


def _register_sources(connection: duckdb.DuckDBPyConnection, sources: list[Source], base: str) -> None:
    rows = []
    seen: set[str] = set()
    for source in sources:
        if source.source_id in seen:
            raise ValueError(f"Duplicate source_id in registry: {source.source_id}")
        seen.add(source.source_id)
        if not source.reviewed and not _reference_source(source):
            continue
        if not _SEGMENT.fullmatch(source.source_id):
            raise ValueError(f"Source id is not safe in an IRI: {source.source_id}")
        rows.append(
            {
                "iri": entity_iri("source", source.source_id, base),
                "rdf_types": ["Source"],
                "source_id": source.source_id,
                "publisher": source.publisher,
                "driver": source.driver,
                "url": source.url,
                "licence": source.licence,
                "cadence": source.cadence,
                "redistribution": source.redistribution,
                "out_of_scope": source.out_of_scope,
                "notes": source.notes,
                "reviewed": source.reviewed,
            }
        )
    if not rows:
        raise ValueError("No reviewed sources")
    table = pa.Table.from_pylist(rows).select(list(NODE_FIELDS["source"]))
    connection.register("source_input", table)
    connection.execute(f"CREATE VIEW source AS SELECT {', '.join(NODE_FIELDS['source'])} FROM source_input")


def _copy(
    connection: duckdb.DuckDBPyConnection,
    select_sql: str,
    destination: Path,
    columns: tuple[str, ...],
    label: str,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(f"COPY ({select_sql}) TO {_sql_path(destination)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    found = tuple(pq.ParquetFile(destination).schema_arrow.names)
    if found != columns:
        missing = [name for name in columns if name not in found]
        if missing:
            raise ValueError(f"{label} is missing columns: {', '.join(missing)}")
        extra = [name for name in found if name not in columns]
        raise ValueError(f"{label} has unexpected columns: {', '.join(extra)}")
    lowered = [name.casefold() for name in found]
    forbidden = [name for name in lowered if any(marker in name for marker in FORBIDDEN_OUTPUT_MARKERS)]
    if forbidden:
        raise ValueError(f"{label} has forbidden columns: {', '.join(forbidden)}")
    rows = pq.ParquetFile(destination).metadata.num_rows
    print(f"{label}: {rows}", flush=True)
    return int(rows)


def _register_output_views(connection: duckdb.DuckDBPyConnection, staging: Path) -> None:
    """Register written tables so the reconciliation queries can read them."""
    _parquet_view(connection, "serves_edge", staging / "edges" / "serves_county.parquet", EDGE_FIELDS["serves_county"])
    _parquet_view(connection, "parent_edge", staging / "edges" / "parent_of.parquet", EDGE_FIELDS["parent_of"])
    _parquet_view(connection, "in_state_edge", staging / "edges" / "in_state.parquet", EDGE_FIELDS["in_state"])
    _parquet_view(
        connection,
        "state_outside",
        staging / "reconciliation" / "state_outside_reference.parquet",
        ("entity_class", "entity_id", "state_code"),
    )


def _parquet_view(connection: duckdb.DuckDBPyConnection, name: str, path: Path, columns: tuple[str, ...]) -> None:
    listed = ", ".join(columns)
    connection.execute(f"CREATE VIEW {name} AS SELECT {listed} FROM read_parquet({_sql_path(path)})")


def _rows(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def _require_names(
    path: Path,
    required: tuple[str, ...],
    label: str,
    allowed_extra: tuple[str, ...] = (),
) -> pa.Schema:
    schema = pq.ParquetFile(path).schema_arrow
    missing = [name for name in required if name not in schema.names]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")
    allowed = set(required) | set(allowed_extra)
    extra = [name for name in schema.names if name not in allowed]
    if extra:
        raise ValueError(f"{label} has unexpected columns: {', '.join(extra)}")
    return schema


def _typed(schema: pa.Schema, column: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
        raise ValueError(f"Column name is not safe: {column}")
    sql_type = FIELD_SQL[column]
    if pa.types.is_null(schema.field(column).type):
        return f"CAST(NULL AS {sql_type}) AS {column}"
    return f"CAST({column} AS {sql_type}) AS {column}"


def _reference_source(source: Source) -> bool:
    """Census reference entries are not the utility drafts kept out of the graph."""
    return bool(source.layers) and all(layer.sector == "reference" for layer in source.layers)


def _sector_case() -> str:
    branches = " ".join(f"WHEN '{sector}' THEN '{class_name}'" for sector, class_name in SECTOR_CLASSES.items())
    return f"CASE sector {branches} ELSE NULL END"


def _fail(connection: duckdb.DuckDBPyConnection, sql: str, message: str) -> None:
    row = connection.execute(sql).fetchone()
    if row:
        detail = ", ".join("" if value is None else str(value) for value in row)
        raise ValueError(f"{message}: {detail}")


def _count(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    if row is None:
        raise ValueError("Count query returned no row")
    return int(row[0])


def _id_set(connection: duckdb.DuckDBPyConnection, path: Path, where_suffix: str) -> set[str]:
    rows = connection.execute(
        f"""
        SELECT system_id FROM read_parquet({_sql_path(path)})
        WHERE county_geoid = {_sql_string(TRAVIS_COUNTY_GEOID)} {where_suffix}
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_path(path: Path) -> str:
    return _sql_string(path.resolve().as_posix())
