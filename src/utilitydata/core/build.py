"""Build the drinking-water core for one quarter from reviewed Silver."""

import json
import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import shapely

from utilitydata.core.checks import (
    acceptance_blockers,
    require_buildable_sources,
    require_decision_coverage,
    require_federal_links,
    require_same_state,
    require_service_systems,
    require_source_counts,
)
from utilitydata.core.config import (
    ACTIVITY_STATUS,
    BLOCKED_CASES,
    DEFAULT_QUARTER,
    GOVERNMENT_UNITS_LAYER,
    IOU_AUTO_ACCEPT,
    MATCH_SAMPLE_SEED,
    MATCH_SAMPLE_SIZE,
    MISSING_ACTIVITY_STATUS,
    NAME_AUTO_ACCEPT,
    NAME_WITH_OVERLAP,
    REVIEW_QUEUE_LIMIT,
    SDWA_SYSTEMS_LAYER,
    THRESHOLDS_CALIBRATED,
    WHOLESALER_CODES,
)
from utilitydata.core.matching import match_water
from utilitydata.core.organization import link_organizations
from utilitydata.core.schema import (
    ATTRIBUTE_COLUMNS,
    EVIDENCE_COLUMNS,
    IDENTIFIER_COLUMNS,
    MANIFEST_COLUMNS,
    ORGANIZATION_COLUMNS,
    OVERRIDE_COLUMNS,
    PWSID_CANDIDATE_COLUMNS,
    SDWA_COLUMNS,
)
from utilitydata.core.service_areas import PART_COLUMNS, assemble_service_areas
from utilitydata.core.system import (
    build_systems_from_sdwa,
    preserve_first_seen,
    public_systems,
)
from utilitydata.core.text import require_columns
from utilitydata.registry import Layer, Source, load_registry

_QUARTER = re.compile(r"^[0-9]{4}-Q[1-4]$")
ASSERTION_READ = (
    "assertion_id",
    "source_id",
    "sector",
    "zone_role",
    "authority",
    "raw_name",
    "name_norm",
    "pwsid",
    "pwsid_raw",
    "geom_state",
    "source_vintage_date",
    "licence",
    "grain",
    "area_km2",
    "footprint_verified",
    "activity_status",
    "review_reason",
)


def build_water_core(home: Path, registry_dir: Path, *, quarter: str = DEFAULT_QUARTER) -> dict[str, object]:
    """Build systems, matches, service areas, and organizations for one quarter.

    Draft and empty-geometry snapshot rows are not read. Thresholds stay at the
    starting values; the 200-pair sample is not a labelled measurement.
    """
    if not _QUARTER.fullmatch(quarter):
        raise ValueError("Core quarter must be formatted YYYY-QN")
    if THRESHOLDS_CALIBRATED:
        raise ValueError("Core thresholds are marked calibrated without a recorded 200-pair measurement")
    silver = home / "silver" / quarter
    output = home / "core" / quarter
    state = home / "state"
    output.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    overrides = ensure_override_file(registry_dir.parent / "overrides" / "match_overrides.csv")
    sources = load_registry(registry_dir, require_reviewed=False)
    sdwa_source, sdwa_layer = _find_layer(sources, SDWA_SYSTEMS_LAYER)
    government_source, _government_layer = _find_layer(sources, GOVERNMENT_UNITS_LAYER)
    _require_sdwa_maps(sdwa_layer)
    if not sdwa_layer.sector:
        raise ValueError("SDWA systems layer has no sector")

    print("reading Silver tables", flush=True)
    sdwa = _read_columns(silver / "sdwa_public_water_system.parquet", SDWA_COLUMNS)
    assertions = _read_columns(silver / "boundary_assertion.parquet", ASSERTION_READ)
    candidate_columns = list(PWSID_CANDIDATE_COLUMNS)
    candidate_schema = pq.read_schema(silver / "pwsid_candidate.parquet")
    if "ordinal" in candidate_schema.names:
        candidate_columns.append("ordinal")
    pwsid_candidates = _read_columns(silver / "pwsid_candidate.parquet", tuple(candidate_columns))
    attributes = _read_columns(silver / "water_attribute.parquet", ATTRIBUTE_COLUMNS)
    government = _read_columns(silver / "ref_government_unit.parquet", ("CENSUS_ID_PID6", "UNIT_NAME", "STATE"))
    manifest = _read_columns(home / "snapshots" / quarter / "manifest.parquet", MANIFEST_COLUMNS)
    geometries = _read_geometries(silver / "boundary_assertion.parquet")
    require_buildable_sources(manifest, set(assertions["source_id"].dropna().astype(str)))

    print("building systems", flush=True)
    systems, identifiers, evidence = build_systems_from_sdwa(
        sdwa, release=quarter, source_id=sdwa_source.source_id, sector=sdwa_layer.sector
    )
    print("matching assertions", flush=True)
    matched = match_water(
        assertions,
        systems,
        geometries=geometries,
        overrides=overrides,
        candidates=pwsid_candidates,
        registry_path=state / "id_registry.parquet",
        release=quarter,
    )
    systems = matched.systems
    identifiers = pd.concat([identifiers, matched.identifiers], ignore_index=True)
    print("linking organizations", flush=True)
    systems, organizations, org_counts = link_organizations(
        systems,
        government,
        sdwa_source_id=sdwa_source.source_id,
        government_source_id=government_source.source_id,
        sector=sdwa_layer.sector,
    )
    decisions = matched.decisions
    require_decision_coverage(assertions, decisions)
    require_federal_links(assertions, decisions, set(overrides["assertion_id"].astype(str)))
    require_same_state(assertions, decisions, systems)
    require_source_counts(assertions, decisions)
    _require_known_identifiers(systems, identifiers, evidence)
    _require_attribute_systems(attributes, systems)
    _require_unnamed_multiples(assertions, decisions)
    blockers = acceptance_blockers(sources, set(assertions["source_id"].dropna().astype(str)))

    print("dissolving service areas", flush=True)
    areas = _service_areas(assertions, decisions, geometries)
    require_service_systems(areas, systems)
    if bool(areas.loc[areas["is_best"] & areas["zone_role"].isin(["onsite_noncommunity", "regional_wholesale_or_district"])].shape[0]):
        raise ValueError("An on-site or wholesale area was marked best")

    previous = output / "system.parquet"
    if previous.is_file():
        systems = preserve_first_seen(systems, pd.read_parquet(previous, columns=["system_id", "first_seen_release"]))
    published = public_systems(systems)
    _write_table(published, output / "system.parquet")
    _write_table(identifiers.loc[:, list(IDENTIFIER_COLUMNS)], output / "system_identifier.parquet")
    _write_table(evidence.loc[:, list(EVIDENCE_COLUMNS)], output / "system_evidence.parquet")
    _write_table(organizations.loc[:, list(ORGANIZATION_COLUMNS)], output / "organization.parquet")
    _write_table(decisions, output / "match_decision.parquet")
    areas.to_parquet(output / "service_area.parquet", index=False)
    unmatched = _unmatched(assertions, decisions)
    unmatched.to_csv(output / "unmatched_assertions.csv", index=False)
    matched.queue.to_csv(state / "review_queue.csv", index=False)
    matched.sample.to_csv(state / "match_sample_200.csv", index=False)

    report = _report(
        quarter,
        published,
        areas,
        decisions,
        organizations,
        evidence,
        matched.queue,
        matched.sample,
        unmatched,
        assertions,
        identifiers,
        org_counts,
        blockers,
        sources,
    )
    (output / "core_water_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"systems: {report['system_rows']}; service areas: {report['service_area_rows']}; "
        f"decisions: {report['match_decision_rows']}; organizations: {report['organization_rows']}; "
        f"review queue assertions: {report['review_queue_assertions']}",
        flush=True,
    )
    return report


def ensure_override_file(path: Path) -> pd.DataFrame:
    """Create an empty override file when it is missing, and never invent rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        pd.DataFrame(columns=list(OVERRIDE_COLUMNS)).to_csv(path, index=False)
    frame = pd.read_csv(path, dtype="string")
    require_columns(frame, OVERRIDE_COLUMNS, "match overrides")
    return frame


def _find_layer(sources: list[Source], layer_name: str) -> tuple[Source, Layer]:
    found = [(source, layer) for source in sources for layer in source.layers if layer.layer == layer_name]
    if len(found) != 1:
        raise ValueError(f"Expected one registry layer named {layer_name}, found {len(found)}")
    return found[0]


def _require_sdwa_maps(layer: Layer) -> None:
    if layer.status_field is None or dict(layer.status_field.values) != ACTIVITY_STATUS:
        raise ValueError("SDWA status map does not match the core config")
    if layer.status_field.on_null != MISSING_ACTIVITY_STATUS:
        raise ValueError("SDWA null activity policy does not match the core config")
    if layer.wholesaler_field is None or dict(layer.wholesaler_field.values) != WHOLESALER_CODES:
        raise ValueError("SDWA wholesaler map does not match the core config")


def _read_columns(path: Path, columns: tuple[str, ...]) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"Missing table {path.name}")
    schema = pq.read_schema(path)
    missing = [name for name in columns if name not in schema.names]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {', '.join(missing)}")
    return pd.read_parquet(path, columns=list(columns))


def _read_geometries(path: Path) -> pd.Series:
    table = pq.read_table(path, columns=["assertion_id", "geometry"])
    identifiers = table.column("assertion_id").to_pylist()
    blobs = table.column("geometry").to_pylist()
    if any(blob is None for blob in blobs):
        raise ValueError("A boundary assertion is missing geometry")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Boundary assertion ids are not unique")
    return pd.Series(list(shapely.from_wkb(blobs)), index=pd.Index([str(value) for value in identifiers], dtype="string"))


def _service_areas(assertions: pd.DataFrame, decisions: pd.DataFrame, geometries: pd.Series) -> pd.DataFrame:
    linked = assertions.merge(decisions.loc[:, ["assertion_id", "system_id"]], on="assertion_id", how="left")
    parts = linked.loc[linked["system_id"].notna()].copy()
    if parts.empty:
        raise ValueError("No assertion was linked to a system")
    parts["geometry"] = geometries.reindex(parts["assertion_id"].astype(str)).to_numpy()
    if any(geometry is None for geometry in parts["geometry"]):
        raise ValueError("A matched assertion is missing geometry")
    return assemble_service_areas(parts.loc[:, list(PART_COLUMNS)])


def _require_known_identifiers(systems: pd.DataFrame, identifiers: pd.DataFrame, evidence: pd.DataFrame) -> None:
    tribal = systems.loc[systems["system_id"].eq("SYS_PWS_090600058")]
    values = identifiers.loc[identifiers["value"].eq("090600058"), "value"]
    if len(tribal) != 1 or len(values) != 1 or values.iloc[0] != "090600058":
        raise ValueError("PWSID 090600058 was not preserved")
    if bool(systems["system_id"].eq("SYS_PWS_OKMCD0003").any()) or bool(identifiers["value"].eq("OKMCD0003").any()):
        raise ValueError("OKMCD0003 was minted as a federal identifier")
    inactive = evidence.loc[evidence["activity_code"].eq("I"), "system_id"]
    status = systems.set_index("system_id").loc[inactive, "status"]
    if not bool(status.eq("inactive").all()):
        raise ValueError("An inactive SDWA system was dropped or relabelled")
    if len(systems) < len(evidence):
        raise ValueError("SDWA systems are missing from the core system table")


def _require_attribute_systems(attributes: pd.DataFrame, systems: pd.DataFrame) -> None:
    require_columns(attributes, ATTRIBUTE_COLUMNS, "water attributes")
    missing = sorted(set(attributes["pwsid"].dropna().astype(str)) - set(systems["pwsid"].dropna().astype(str)))
    if missing:
        raise ValueError(f"A water attribute PWSID is missing from system, for example {missing[0]}")


def _require_unnamed_multiples(assertions: pd.DataFrame, decisions: pd.DataFrame) -> None:
    review = assertions["review_reason"].fillna("").astype(str)
    unnamed = assertions.loc[review.str.contains("multiple_identifiers") & assertions["name_norm"].isna() & assertions["pwsid"].isna()]
    if unnamed.empty:
        return
    linked = unnamed.merge(decisions.loc[:, ["assertion_id", "system_id"]], on="assertion_id", how="left")
    if bool(linked["system_id"].notna().any()):
        example = linked.loc[linked["system_id"].notna(), "assertion_id"].iloc[0]
        raise ValueError(f"An unnamed multi-identifier boundary was assigned to a system: {example}")


def _unmatched(assertions: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    rows = decisions.loc[decisions["system_id"].isna(), ["assertion_id", "evidence", "decided_by"]]
    columns = ["assertion_id", "source_id", "pwsid_raw", "raw_name", "name_norm", "geom_state", "zone_role", "review_reason"]
    return rows.merge(assertions.loc[:, columns], on="assertion_id", how="left").sort_values("assertion_id").reset_index(drop=True)


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    frame.to_parquet(path, index=False)


def _report(
    quarter: str,
    systems: pd.DataFrame,
    areas: pd.DataFrame,
    decisions: pd.DataFrame,
    organizations: pd.DataFrame,
    evidence: pd.DataFrame,
    queue: pd.DataFrame,
    sample: pd.DataFrame,
    unmatched: pd.DataFrame,
    assertions: pd.DataFrame,
    identifiers: pd.DataFrame,
    org_counts: dict[str, int],
    blockers: list[dict[str, object]],
    sources: list[Source],
) -> dict[str, object]:
    methods = decisions["method"].value_counts(dropna=False)
    method_counts = {("unmatched" if pd.isna(key) else str(key)): int(value) for key, value in methods.items()}
    reasons = unmatched["evidence"].fillna("unmatched").astype(str).str.split(";").str[0].value_counts()
    by_source = unmatched.groupby("source_id").size() if not unmatched.empty else pd.Series(dtype="int64")
    silver_counts = {str(key): int(value) for key, value in assertions.groupby("source_id").size().items()}
    draft_water = [
        source.source_id
        for source in sources
        if not source.reviewed and any(layer.sector == "water" for layer in source.layers)
    ]
    return {
        "quarter": quarter,
        "system_rows": len(systems),
        "service_area_rows": len(areas),
        "match_decision_rows": len(decisions),
        "organization_rows": len(organizations),
        "system_identifier_rows": len(identifiers),
        "review_queue_rows": len(queue),
        "review_queue_assertions": int(queue["assertion_id"].nunique()) if not queue.empty else 0,
        "method_counts": method_counts,
        "inactive_sdwa_systems": int(evidence["activity_code"].eq("I").sum()),
        "inactive_core_systems": int(systems["status"].eq("inactive").sum()),
        "federal_registry_systems": int(systems["in_federal_registry"].sum()),
        "best_service_areas": int(areas["is_best"].sum()),
        "government_unit_links": org_counts["government_matches"],
        "ambiguous_government_names": org_counts["ambiguous_government_names"],
        "unmatched_assertions": len(unmatched),
        "unmatched_by_reason": {str(key): int(value) for key, value in reasons.items()},
        "unmatched_by_source": {str(key): int(value) for key, value in by_source.items()},
        "silver_assertions_by_source": silver_counts,
        "done_when": {
            "federal_pwsid_links_same_system": True,
            "name_matches_stay_in_state": True,
            "service_area_systems_exist": True,
            "source_counts_reconcile": True,
        },
        "match_sample": {
            "rows": len(sample),
            "measured": False,
            "thresholds_changed": False,
            "thresholds_calibrated": THRESHOLDS_CALIBRATED,
            "seed": MATCH_SAMPLE_SEED,
            "requested_rows": MATCH_SAMPLE_SIZE,
            "by_decision": {str(key): int(value) for key, value in sample["decision"].value_counts().items()} if not sample.empty else {},
            "by_method": {str(key): int(value) for key, value in sample["method"].value_counts().items()} if not sample.empty else {},
        },
        "thresholds": {
            "name_auto_accept": NAME_AUTO_ACCEPT,
            "name_with_overlap": NAME_WITH_OVERLAP,
            "iou_auto_accept": IOU_AUTO_ACCEPT,
            "review_queue_limit": REVIEW_QUEUE_LIMIT,
        },
        "acceptance_cases": blockers,
        "draft_water_sources_not_consumed": len(draft_water),
        "blocked_case_ids": [case.case_id for case in BLOCKED_CASES],
    }
