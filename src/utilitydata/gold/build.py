"""Build the drinking-water Gold tables for one quarter."""

import json
from pathlib import Path

import duckdb
import pandas as pd

from utilitydata.core.config import DEFAULT_QUARTER
from utilitydata.gold.coverage import build_coverage
from utilitydata.gold.display import write_display
from utilitydata.gold.facilities import build_compliance, build_facilities
from utilitydata.gold.scorecard import write_scorecard
from utilitydata.gold.search import build_entity_search, north_st_paul_status
from utilitydata.gold.territories import write_territories
from utilitydata.registry import Source, load_registry


def build_water_gold(
    home: Path,
    registry_dir: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
    rebuild_coverage: bool = True,
) -> dict[str, object]:
    """Build coverage, territories, facilities, compliance, the scorecard, display geometry, and search."""
    sources = load_registry(registry_dir, require_reviewed=False)
    sdwa = _source_for_layer(sources, "SDWA_FACILITIES.csv")
    violations = _source_for_layer(sources, "SDWA_VIOLATIONS_ENFORCEMENT.csv")
    if sdwa.source_id != violations.source_id or sdwa.licence != violations.licence:
        raise ValueError("SDWA facilities and violations are not the same licensed source")
    if not sdwa.licence:
        raise ValueError("SDWA source has no licence")
    output = home / "gold" / quarter
    silver = home / "silver" / quarter
    core = home / "core" / quarter
    output.mkdir(parents=True, exist_ok=True)
    coverage_summary: dict[str, object]
    if rebuild_coverage or not (output / "system_county_coverage.parquet").is_file():
        coverage_summary = build_coverage(
            service_areas=core / "service_area.parquet",
            systems=core / "system.parquet",
            blocks=silver / "ref_block.parquet",
            assertions=silver / "boundary_assertion.parquet",
            geographic=silver / "sdwa_geographic_area.parquet",
            states=silver / "ref_state.parquet",
            counties=silver / "ref_county.parquet",
            places=silver / "ref_place.parquet",
            alias=silver / "ref_county_alias.parquet",
            identifiers=core / "system_identifier.parquet",
            output=output,
            work=output / "_work",
            sdwa_licence=sdwa.licence,
            sdwa_source_id=sdwa.source_id,
        )
    else:
        coverage_summary = {"reused_coverage": True}
    print("writing territories", flush=True)
    territory_rows = write_territories(output / "_work" / "best_areas_wkb.parquet", output / "territories_water.parquet")
    print("writing facilities and compliance", flush=True)
    lookup = _system_lookup(core / "system.parquet", core / "system_identifier.parquet")
    facility_rows = build_facilities(
        silver / "sdwa_facility.parquet",
        lookup,
        output / "water_facilities.parquet",
        licence=sdwa.licence,
        source_id=sdwa.source_id,
    )
    compliance = build_compliance(
        silver / "sdwa_violation.parquet",
        lookup,
        output / "water_compliance_summary.parquet",
        licence=sdwa.licence,
        source_id=sdwa.source_id,
    )
    as_of = pd.to_datetime(str(compliance["as_of_date"])).date()
    print("writing scorecard and display", flush=True)
    write_scorecard(
        blocks=silver / "ref_block.parquet",
        block_coverage=output / "system_block_coverage.parquet",
        territories=output / "territories_water.parquet",
        systems=core / "system.parquet",
        states=silver / "ref_state.parquet",
        destination=output / "state_sector_scorecard.parquet",
        as_of=as_of,
    )
    display = write_display(output / "territories_water.parquet", output / "service_area_display.parquet")
    print("writing search", flush=True)
    search = _search(output, silver, core, sources, sdwa.licence)
    summary = {
        "quarter": quarter,
        "coverage": coverage_summary,
        "territories_water": territory_rows,
        "water_facilities": facility_rows,
        "water_compliance_summary": compliance,
        "service_area_display": display,
        "entity_search": search,
    }
    (output / "gold_water_report.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return summary


def _search(
    output: Path,
    silver: Path,
    core: Path,
    sources: list[Source],
    federal_licence: str,
) -> dict[str, object]:
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        assertions = connection.execute(
            f"""
            SELECT d.system_id, a.raw_name AS label, a.licence, a.source_id
            FROM read_parquet('{_path(core / "match_decision.parquet")}') d
            JOIN read_parquet('{_path(silver / "boundary_assertion.parquet")}') a USING (assertion_id)
            WHERE d.system_id IS NOT NULL
            """
        ).fetchdf()
        states = connection.execute(
            f"SELECT usps FROM read_parquet('{_path(silver / 'ref_state.parquet')}')"
        ).fetchall()
    finally:
        connection.close()
    systems = pd.read_parquet(
        core / "system.parquet",
        columns=["system_id", "name", "primary_state", "in_federal_registry", "owner_org_id"],
    )
    identifiers = pd.read_parquet(core / "system_identifier.parquet")
    organizations = pd.read_parquet(core / "organization.parquet", columns=["org_id", "name", "source_id"])
    licences = {source.source_id: source.licence for source in sources if source.licence}
    frame = build_entity_search(
        systems,
        identifiers,
        assertions,
        organizations,
        state_codes={str(row[0]) for row in states},
        federal_licence=federal_licence,
        licence_by_source=licences,
    )
    frame.to_parquet(output / "entity_search.parquet", index=False)
    status = north_st_paul_status(frame, state_codes={str(row[0]) for row in states})
    status["rows"] = len(frame)
    return status


def _system_lookup(systems: Path, identifiers: Path) -> pd.DataFrame:
    system = pd.read_parquet(systems, columns=["system_id", "in_federal_registry"])
    identifier = pd.read_parquet(identifiers, columns=["system_id", "scheme", "value"])
    identifier = identifier.loc[identifier["scheme"].eq("pwsid"), ["system_id", "value"]]
    identifier = identifier.rename(columns={"value": "pwsid"}).drop_duplicates()
    lookup = system.merge(identifier, on="system_id", how="inner")
    if bool(lookup["pwsid"].duplicated().any()):
        raise ValueError("A PWSID is linked to more than one system")
    return lookup


def _source_for_layer(sources: list[Source], layer_name: str) -> Source:
    found = [source for source in sources for layer in source.layers if layer.layer == layer_name]
    if len(found) != 1:
        raise ValueError(f"Expected one source for layer {layer_name}, found {len(found)}")
    return found[0]


def _path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
