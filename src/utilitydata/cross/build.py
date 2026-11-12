"""Build cross-sector owners, facilities, and networks beside the sector tables."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from utilitydata.core.config import (
    DEFAULT_QUARTER,
    FACILITY_THRESHOLDS_CALIBRATED,
    GOVERNMENT_UNITS_LAYER,
    HIFLD_HOLDING_CONFIDENCE,
    SEC_PARENT_CONFIDENCE,
)
from utilitydata.core.text import as_string, require_columns
from utilitydata.cross.capacity import capacity_equality
from utilitydata.cross.features import (
    covered_unit_states,
    facilities_from_frame,
    network_frame,
    normalize_frame,
)
from utilitydata.cross.layers import LayerJob, read_layer, select_layers
from utilitydata.cross.location import write_location_tables
from utilitydata.cross.match import match_facilities
from utilitydata.cross.owners import link_cross_sector_governments
from utilitydata.cross.parents import (
    HIFLD_COVERAGE_NOTE,
    SEC_COVERAGE_NOTE,
    filing_relationships,
    parent_customer_totals,
    rank_parents,
    write_parent_review,
)
from utilitydata.cross.schema import (
    FACILITY_COLUMNS,
    MATCH_COLUMNS,
    REJECT_COLUMNS,
    RELATIONSHIP_COLUMNS,
    UNIT_COLUMNS,
    empty_frame,
)
from utilitydata.cross.vocab import (
    load_facility_types,
    require_known_facility_type,
    require_mapped_facility_types,
)
from utilitydata.electric.boundaries import parse_eia_id
from utilitydata.registry import Layer, Source, load_registry
from utilitydata.sectors.overrides import (
    apply_facility_overrides,
    load_facility_overrides,
)
from utilitydata.sectors.tables import field_name
from utilitydata.sectors.zones import BUILDABLE, UNBUILDABLE
from utilitydata.silver.boundaries import _load_state_regions, parse_vintage
from utilitydata.silver.geometry import containing_state_codes

_ORG_TABLES = {
    "water": "organization.parquet",
    "electric": "electric_organization.parquet",
    "wastewater": "wastewater_organization.parquet",
    "natural_gas": "gas_organization.parquet",
}
_PARENT_FIELDS = (
    "parent_company_name",
    "subsidiary_company_name",
    "parent_company_utility_id_eia",
    "subsidiary_company_utility_id_eia",
    "report_date",
)


def build_cross_sector(
    home: Path,
    registry_dir: Path,
    repository_root: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
) -> dict[str, object]:
    """Build organization links, facilities, units, and network segments."""
    print("loading cross-sector sources", flush=True)
    sources = load_registry(registry_dir, require_reviewed=False)
    layers = pd.read_parquet(home / "snapshots" / quarter / "layers.parquet")
    vocabulary = load_facility_types(repository_root / "registry" / "vocab" / "facility_type.yaml")
    observed_types = _assert_facility_types(home, quarter, sources, layers, vocabulary)
    print("linking governments and parents", flush=True)
    organizations, organization_counts = _organizations(home, quarter)
    government = _government_source(sources)
    govid_links = link_cross_sector_governments(
        organizations,
        _government_units(home, quarter),
        source_id=government.source_id,
        as_of=_listing_year(government),
    )
    relationships, parent_review, parent_summary, parent_rejects = _parents(home, quarter, sources, layers, vocabulary)
    relationships = _concat_frames([govid_links, relationships], RELATIONSHIP_COLUMNS)
    print("reading facilities", flush=True)
    facilities, units, feature_rejects, facility_skipped, wind_measures = _facilities(
        home, quarter, sources, layers, vocabulary
    )
    _assign_missing_state(home, quarter, sources, facilities)
    print("matching facilities", flush=True)
    decisions = match_facilities(_match_frame(facilities))
    decisions = apply_facility_overrides(
        decisions,
        facilities,
        load_facility_overrides(registry_dir.parent / "overrides" / "facility_match_overrides.csv"),
    )
    print("reading networks", flush=True)
    network_counts, network_skipped, network_rejects = _networks(home, quarter, sources, layers, vocabulary)
    feature_rejects = _concat_frames([feature_rejects, network_rejects], REJECT_COLUMNS)
    michigan = _michigan_wind(sources, layers, wind_measures)
    summary = _summary(
        quarter,
        organization_counts,
        relationships,
        govid_links,
        facilities,
        units,
        network_counts,
        decisions,
        parent_review,
        parent_summary,
        feature_rejects,
        parent_rejects,
        facility_skipped + network_skipped + parent_summary["holding_skipped"],
        observed_types,
        michigan,
    )
    print("locating facilities and places", flush=True)
    summary.update(write_location_tables(home, quarter, sources, facilities))
    summary["phmsa_operator_policy"] = "owner_org_id unchanged; no PHMSA operator added"
    _write(home, quarter, facilities, units, relationships, decisions, feature_rejects, parent_rejects, summary)
    return summary


def _assert_facility_types(home: Path, quarter: str, sources: list[Source], layers: pd.DataFrame, vocabulary) -> list[str]:
    for source in sources:
        for layer in source.layers:
            if layer.facility_type_fixed:
                require_known_facility_type(vocabulary, layer.facility_type_fixed)
    jobs, _skipped = select_layers(sources, layers, attribute="facility_type")
    observed: set[str] = set()
    for job in jobs:
        frame, _geometries = read_layer(home, quarter, job, layers)
        column = job.layer.attribute_fields["facility_type"]
        if column not in frame.columns:
            raise ValueError(f"{job.source.source_id} {job.layer.layer} is missing columns: {column}")
        for value in frame[column].unique():
            if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "":
                continue
            if not isinstance(value, str):
                raise ValueError(f"Unmapped facility type: {value!r}")
            observed.add(value)
    require_mapped_facility_types(vocabulary, observed)
    return sorted(observed)


def _organizations(home: Path, quarter: str) -> tuple[pd.DataFrame, dict[str, int]]:
    frames = []
    counts = {}
    for sector, name in _ORG_TABLES.items():
        path = home / "core" / quarter / name
        if not path.is_file():
            raise ValueError(f"Organization table is missing: {name}")
        frame = pd.read_parquet(path)
        if sector == "electric" and not frame.empty:
            frame = frame.loc[~frame["org_id"].astype(str).str.startswith("ORG_HOLD_")].reset_index(drop=True)
        require_columns(
            frame,
            ("org_id", "name", "name_norm", "sector", "state", "owner_type", "government_unit_id"),
            name,
        )
        counts[sector] = len(frame)
        frames.append(frame)
    organizations = pd.concat(frames, ignore_index=True)
    if bool(organizations["org_id"].duplicated().any()):
        raise ValueError("Organization id is duplicated across sectors")
    return organizations, counts


def _government_units(home: Path, quarter: str) -> pd.DataFrame:
    path = home / "silver" / quarter / "ref_government_unit.parquet"
    if not path.is_file():
        raise ValueError("ref_government_unit is missing")
    frame = pd.read_parquet(path, columns=["CENSUS_ID_PID6", "UNIT_NAME", "STATE"])
    require_columns(frame, ("CENSUS_ID_PID6", "UNIT_NAME", "STATE"), "ref_government_unit")
    return frame


def _government_source(sources: list[Source]) -> Source:
    found = [source for source in sources if any(layer.layer == GOVERNMENT_UNITS_LAYER for layer in source.layers)]
    if len(found) != 1:
        raise ValueError("Expected one government-unit reference")
    return found[0]


def _listing_year(source: Source) -> str:
    years = sorted({match for path in source.paths if (match := _year(path))})
    if len(years) != 1:
        raise ValueError("Government units path has no single listing year")
    return years[0]


def _year(path: str) -> str | None:
    digits = [token for token in Path(path).name.replace(".", "_").split("_") if token.isdigit() and len(token) == 4 and token.startswith("20")]
    if len(digits) != 1:
        return None
    return digits[0]


def _parents(home, quarter, sources, layers, vocabulary):
    del vocabulary
    source, layer = _one_attribute(sources, "parent_company_name", "subsidiary_company_name")
    if not source.reviewed:
        raise ValueError("Parent table is not reviewed")
    filings = _read_home_table(home, source, layer)
    latest = pd.to_datetime(filings["report_date"], errors="coerce").max()
    if pd.isna(latest):
        raise ValueError("Parent table has no report date")
    sec_note = (
        SEC_COVERAGE_NOTE
        + f" The latest report date is {latest.date().isoformat()}."
        + " Customers are summed within this source and are not deduplicated across sources."
    )
    org_by_utility, customers = _electric_customers(home, quarter)
    minted_orgs: dict[str, dict[str, object]] = {}
    sec_relationships, sec_rejects = filing_relationships(
        filings,
        source_id=source.source_id,
        confidence=SEC_PARENT_CONFIDENCE,
        experimental=True,
        coverage_note=sec_note,
        org_by_utility=org_by_utility,
        minted_orgs=minted_orgs,
    )
    sec_totals = parent_customer_totals(
        filings,
        customers,
        source_id=source.source_id,
        experimental=True,
        coverage_note=sec_note,
    )
    holding_relationships, holding_rejects, holding_totals, holding_skipped = _holding_companies(
        home, quarter, sources, layers, customers, org_by_utility, minted_orgs
    )
    if minted_orgs:
        _persist_holding_organizations(home, quarter, minted_orgs)
    totals = _concat_frames([sec_totals, holding_totals], list(sec_totals.columns) if not sec_totals.empty else list(holding_totals.columns))
    review = rank_parents(totals if not totals.empty else sec_totals)
    review["list_note"] = "This list is not hand-verified. SEC parent rows are experimental and incomplete."
    relationships = _concat_frames([sec_relationships, holding_relationships], RELATIONSHIP_COLUMNS)
    rejects = _concat_frames([sec_rejects, holding_rejects], REJECT_COLUMNS)
    summary = {
        "sec_source_id": source.source_id,
        "sec_rows": len(filings),
        "sec_relationships": len(sec_relationships),
        "sec_rejects": len(sec_rejects),
        "sec_latest_report_date": latest.date().isoformat(),
        "sec_experimental": True,
        "sec_coverage_note": sec_note,
        "holding_relationships": len(holding_relationships),
        "holding_skipped": holding_skipped,
        "parent_review_rows": len(review),
        "parent_review_verified": False,
    }
    return relationships, review, summary, rejects


def _holding_companies(home, quarter, sources, layers, customers, org_by_utility, minted_orgs):
    jobs, skipped = select_layers(sources, layers, attribute="holding_company")
    frames = []
    rejects = []
    totals = []
    hifld_note = HIFLD_COVERAGE_NOTE + " Customers are summed within this source and are not deduplicated across sources."
    for job in jobs:
        print(f"reading holding companies {job.source.source_id}", flush=True)
        raw, _geometries = read_layer(home, quarter, job, layers)
        filings = _holding_filings(raw, job.layer)
        relationships, rejected = filing_relationships(
            filings,
            source_id=job.source.source_id,
            confidence=HIFLD_HOLDING_CONFIDENCE,
            experimental=False,
            coverage_note=hifld_note,
            org_by_utility=org_by_utility,
            minted_orgs=minted_orgs,
        )
        totals.append(parent_customer_totals(
            filings,
            customers,
            source_id=job.source.source_id,
            experimental=False,
            coverage_note=hifld_note,
        ))
        frames.append(relationships)
        rejects.append(rejected)
    return (
        _concat_frames(frames, RELATIONSHIP_COLUMNS),
        _concat_frames(rejects, REJECT_COLUMNS),
        _concat_frames(totals, list(totals[0].columns) if totals else ["parent_name", "customers", "source_id", "as_of", "experimental", "coverage_note"]),
        [_public_skip(row) for row in skipped],
    )


def _persist_holding_organizations(home: Path, quarter: str, minted_orgs: dict[str, dict[str, object]]) -> None:
    elec_org_path = home / "core" / quarter / "electric_organization.parquet"
    existing_all = set()
    for name in _ORG_TABLES.values():
        p = home / "core" / quarter / name
        if p.is_file():
            df = pd.read_parquet(p, columns=["org_id"])
            if name == "electric_organization.parquet":
                df = df.loc[~df["org_id"].astype(str).str.startswith("ORG_HOLD_")]
            existing_all.update(df["org_id"].dropna().astype(str))
    elec = pd.read_parquet(elec_org_path)
    elec = elec.loc[~elec["org_id"].astype(str).str.startswith("ORG_HOLD_")].copy()
    new_rows = [row for oid, row in sorted(minted_orgs.items()) if oid not in existing_all]
    if not new_rows:
        elec.to_parquet(elec_org_path, index=False)
        return
    extra = pd.DataFrame(new_rows, columns=list(elec.columns))
    for col in elec.columns:
        extra[col] = extra[col].astype("string")
    combined = pd.concat([elec, extra], ignore_index=True).sort_values("org_id").reset_index(drop=True)
    combined.to_parquet(elec_org_path, index=False)


def _holding_filings(frame: pd.DataFrame, layer: Layer) -> pd.DataFrame:
    if "holding_company" not in layer.attribute_fields or not layer.name_field:
        raise ValueError(f"{layer.layer} does not name a holding company and a utility")
    dates = [parse_vintage(value) for value in frame[layer.vintage_field]] if layer.vintage_field else [None] * len(frame)
    eia_column = layer.id_fields.get("eia_utility_id")
    if eia_column and eia_column not in frame.columns:
        raise ValueError(f"{layer.layer} is missing columns: {eia_column}")
    eia_values = frame[eia_column] if eia_column else pd.Series(pd.NA, index=frame.index)
    return pd.DataFrame({
        "parent_company_name": as_string(frame[layer.attribute_fields["holding_company"]]),
        "subsidiary_company_name": as_string(frame[layer.name_field]),
        "parent_company_utility_id_eia": pd.Series(pd.NA, index=frame.index),
        "subsidiary_company_utility_id_eia": [parse_eia_id(value) for value in eia_values],
        "report_date": dates,
    })


def _electric_customers(home: Path, quarter: str) -> tuple[dict[int, str], pd.DataFrame]:
    identifiers = pd.read_parquet(home / "core" / quarter / "electric_system_identifier.parquet")
    systems = pd.read_parquet(home / "core" / quarter / "electric_system.parquet", columns=["system_id", "customers", "owner_org_id"])
    require_columns(identifiers, ("system_id", "scheme", "value"), "electric identifiers")
    eia = identifiers.loc[identifiers["scheme"].eq("eia_utility"), ["system_id", "value"]]
    merged = eia.merge(systems, on="system_id", how="left")
    utility_id = pd.to_numeric(merged["value"], errors="coerce")
    if bool((merged["value"].notna() & utility_id.isna()).any()):
        raise ValueError("Electric utility id is not numeric")
    if bool(utility_id.duplicated().any()):
        raise ValueError("Electric utility id is duplicated")
    org_by_utility = {
        int(utility): str(org)
        for utility, org in zip(utility_id, merged["owner_org_id"], strict=True)
        if pd.notna(utility) and pd.notna(org)
    }
    customers = pd.DataFrame({"utility_id": utility_id, "customers": pd.to_numeric(merged["customers"], errors="coerce")})
    return org_by_utility, customers


def _facilities(home, quarter, sources, layers, vocabulary):
    jobs, skipped = select_layers(sources, layers, grain="facility")
    facilities = []
    units = []
    rejects = []
    wind_measures = []
    state_inventories = covered_unit_states(sources)
    for job in jobs:
        print(f"reading facility {job.source.source_id} {job.layer.layer}", flush=True)
        raw, geometries = read_layer(home, quarter, job, layers)
        kept, rejected, mask = normalize_frame(raw, job.layer, job.source, vocabulary)
        kept_geometries = _filter_geometries(geometries, mask, job)
        identified = len(kept)
        kept, kept_geometries, state_rejected = _without_state_inventory(kept, kept_geometries, job, state_inventories)
        if not state_rejected.empty:
            rejects.append(state_rejected)
        facility_rows, unit_rows, capacity_rejects = facilities_from_frame(kept, kept_geometries, job.layer, job.source)
        if identified + len(rejected) != len(raw) or len(kept) + len(state_rejected) != identified:
            raise ValueError(f"{job.source.source_id} {job.layer.layer} rows do not reconcile")
        facilities.append(facility_rows)
        units.append(unit_rows)
        rejects.append(rejected)
        if not capacity_rejects.empty:
            capacity_rejects = capacity_rejects.copy()
            capacity_rejects["raw_name"] = pd.NA
            rejects.append(capacity_rejects.loc[:, ["source_id", "source_layer", "source_feature_id", "reason", "raw_name"]])
        if job.layer.state_fixed == "MI" and job.layer.facility_level == "unit":
            wind_measures.append(_measure_wind(kept, unit_rows, job))
    return (
        _concat_frames(facilities, FACILITY_COLUMNS),
        _concat_frames(units, UNIT_COLUMNS),
        _concat_frames(rejects, REJECT_COLUMNS),
        [_public_skip(row) for row in skipped],
        wind_measures,
    )


def _without_state_inventory(
    kept: pd.DataFrame,
    geometries: list | None,
    job: LayerJob,
    inventories: dict[str, set[str]],
) -> tuple[pd.DataFrame, list | None, pd.DataFrame]:
    """Reject unit rows a reviewed state inventory already covers.

    The state inventory itself is kept. A national file's rows in that state
    are returned as rejects with a reason, and the rest of the file is kept.
    """
    facility_type = job.layer.facility_type_fixed
    states = set() if job.layer.state_fixed or not facility_type else inventories.get(facility_type, set())
    if not states:
        return kept, geometries, _state_reject_frame(kept.iloc[0:0], job)
    drop = kept["state"].isin(states)
    if not bool(drop.any()):
        return kept, geometries, _state_reject_frame(kept.iloc[0:0], job)
    rejected = _state_reject_frame(kept.loc[drop], job)
    remaining = kept.loc[~drop].reset_index(drop=True)
    if geometries is None:
        return remaining, None, rejected
    kept_geometries = [geometry for geometry, removed in zip(geometries, drop.tolist(), strict=True) if not removed]
    return remaining, kept_geometries, rejected


def _state_reject_frame(rows: pd.DataFrame, job: LayerJob) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=list(REJECT_COLUMNS))
    return pd.DataFrame({
        "source_id": job.source.source_id,
        "source_layer": job.layer.layer,
        "source_feature_id": rows["feature_id"].to_numpy(),
        "reason": "state_unit_inventory",
        "raw_name": rows["name"].to_numpy(),
    })


def _measure_wind(kept: pd.DataFrame, unit_rows: pd.DataFrame, job: LayerJob) -> dict[str, object]:
    plant = kept.loc[:, ["feature_id", "plant_capacity_mw"]].rename(columns={"feature_id": "source_feature_id"})
    merged = unit_rows.merge(plant, on="source_feature_id", how="left")
    merged["unit_capacity_mw"] = pd.to_numeric(merged["capacity_mw"], errors="coerce")
    if len(merged) != len(unit_rows):
        raise ValueError(f"{job.source.source_id} wind units do not reconcile")
    stats = capacity_equality(merged)
    stats.update({
        "source_id": job.source.source_id,
        "reviewed": True,
        "snapshot_status": job.status,
        "capacity_fields": sorted(
            name for name in ("unit_capacity_kw", "unit_capacity_mw", "plant_capacity_mw", "turbine_count")
            if name in job.layer.attribute_fields
        ),
        "note": (
            "Published capacity is the sum of unit ratings grouped into projects. "
            "A plant total repeated on every unit is rejected and is not multiplied by the turbine count."
        ),
    })
    return stats


def _networks(home, quarter, sources, layers, vocabulary):
    jobs, skipped = select_layers(sources, layers, grain="network")
    by_sector: dict[str, list[Path]] = {}
    network_rejects = []
    core = home / "core" / quarter
    part_root = core / "_network_parts"
    if part_root.exists():
        shutil.rmtree(part_root)
    part_root.mkdir(parents=True, exist_ok=True)
    try:
        for index, job in enumerate(jobs):
            print(f"reading network {job.source.source_id}", flush=True)
            raw, geometries = read_layer(home, quarter, job, layers)
            if geometries is None:
                raise ValueError(f"{job.source.source_id} {job.layer.layer} is a network without geometry")
            kept, rejected, mask = normalize_frame(raw, job.layer, job.source, vocabulary)
            if len(kept) + len(rejected) != len(raw):
                raise ValueError(f"{job.source.source_id} {job.layer.layer} network rows do not reconcile")
            if len(rejected):
                network_rejects.append(rejected)
            kept_geometries = _filter_geometries(geometries, mask, job)
            segments = network_frame(kept, kept_geometries, job.layer, job.source)
            if len(segments) + len(rejected) != len(raw):
                raise ValueError(f"{job.source.source_id} {job.layer.layer} network rows do not reconcile")
            geodata = gpd.GeoDataFrame(segments.drop(columns=["geometry"]), geometry=segments["geometry"].tolist(), crs="EPSG:4326")
            part = part_root / f"{index}.parquet"
            geodata.to_parquet(part, index=False)
            by_sector.setdefault(str(job.layer.sector), []).append(part)
        counts = {}
        for sector, parts in sorted(by_sector.items()):
            if not _safe_name(sector):
                raise ValueError(f"Sector cannot be a path: {sector}")
            frames = [gpd.read_parquet(part) for part in parts]
            combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
            combined = gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")
            combined.to_parquet(core / f"network_segments_{sector}.parquet", index=False)
            counts[sector] = len(combined)
            print(f"wrote network_segments_{sector}.parquet {counts[sector]}", flush=True)
    finally:
        if part_root.exists():
            shutil.rmtree(part_root)
    return counts, [_public_skip(row) for row in skipped], _concat_frames(network_rejects, REJECT_COLUMNS)


def _michigan_wind(sources: list[Source], layers: pd.DataFrame, measures: list[dict[str, object]]) -> dict[str, object]:
    """Report Michigan unit capacity. Do not invent a total when it cannot be computed."""
    candidates = [
        (source, layer)
        for source in sources
        for layer in source.layers
        if layer.state_fixed == "MI" and layer.facility_level == "unit"
    ]
    if not candidates:
        return {
            "equal": None,
            "capacity_mw": None,
            "reason": "The Michigan wind layer has no capacity field, so the equality cannot be computed.",
        }
    if measures:
        return measures[0] if len(measures) == 1 else {"layers": measures}
    reports = []
    for source, layer in candidates:
        fields = layer.attribute_fields
        has_capacity = any(name in fields for name in ("unit_capacity_kw", "unit_capacity_mw", "plant_capacity_mw"))
        if not source.reviewed:
            reports.append(_cannot_compute(source.source_id, "unreviewed"))
            continue
        match = layers[(layers["source_id"] == source.source_id) & (layers["layer"] == layer.layer)]
        if len(match) != 1:
            reports.append(_cannot_compute(source.source_id, "snapshot status is missing"))
            continue
        status = str(match.iloc[0]["status"])
        if status in UNBUILDABLE or status not in BUILDABLE:
            reports.append(_cannot_compute(source.source_id, f"snapshot status is {status}"))
            continue
        if not has_capacity:
            reports.append(_cannot_compute(source.source_id, "no capacity field"))
            continue
        reports.append(_cannot_compute(source.source_id, "the layer was not built"))
    if len(reports) == 1:
        return reports[0]
    return {"layers": reports}


def _cannot_compute(source_id: str, reason: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "reviewed": None,
        "equal": None,
        "capacity_mw": None,
        "sum_of_project_capacity_mw": None,
        "reason": f"Michigan wind equality cannot be computed: {reason}.",
    }


def _assign_missing_state(home: Path, quarter: str, sources: list[Source], facilities: pd.DataFrame) -> None:
    missing = facilities["state"].isna() & facilities["longitude"].notna() & facilities["latitude"].notna()
    if not bool(missing.any()):
        return
    state_geometries, state_codes = _load_state_regions(home, sources, home / "silver" / quarter / "ref_state.parquet")
    points = shapely.points(
        facilities.loc[missing, "longitude"].to_numpy(dtype=float),
        facilities.loc[missing, "latitude"].to_numpy(dtype=float),
    )
    facilities.loc[missing, "state"] = containing_state_codes(points, state_geometries, state_codes)


def _match_frame(facilities: pd.DataFrame) -> pd.DataFrame:
    columns = ["facility_id", "sector", "source_id", "name_norm", "state", "longitude", "latitude"]
    usable = facilities["name_norm"].notna() & (facilities["longitude"].notna() | facilities["state"].notna())
    return facilities.loc[usable, columns]


def _write(home, quarter, facilities, units, relationships, decisions, feature_rejects, parent_rejects, summary) -> None:
    core = home / "core" / quarter
    core.mkdir(parents=True, exist_ok=True)
    fac_table = pa.Table.from_pandas(facilities.loc[:, list(FACILITY_COLUMNS)], preserve_index=False)
    geo_meta = json.dumps({
        "version": "1.1.0",
        "primary_column": "geometry_wkb",
        "columns": {
            "geometry_wkb": {
                "encoding": "WKB",
                "geometry_types": ["Point", "Polygon", "MultiPolygon"],
            }
        },
    }).encode("utf-8")
    existing_meta = dict(fac_table.schema.metadata or {})
    existing_meta[b"geo"] = geo_meta
    pq.write_table(fac_table.replace_schema_metadata(existing_meta), core / "facility.parquet")
    units.loc[:, list(UNIT_COLUMNS)].to_parquet(core / "facility_unit.parquet", index=False)
    relationships.to_parquet(core / "organization_relationship.parquet", index=False)
    matched = decisions.loc[decisions["decision"].eq("match")] if not decisions.empty else empty_frame(MATCH_COLUMNS)
    review = decisions.loc[decisions["decision"].eq("review")] if not decisions.empty else empty_frame(MATCH_COLUMNS)
    matched.to_parquet(core / "facility_match.parquet", index=False)
    review.to_parquet(core / "facility_review_queue.parquet", index=False)
    _concat_frames([feature_rejects, parent_rejects], REJECT_COLUMNS).to_parquet(core / "cross_sector_reject.parquet", index=False)
    review_path = home / "review" / "parents_top100.csv"
    if not review_path.resolve().is_relative_to(home.resolve()):
        raise ValueError("Parent review path escapes the data root")
    write_parent_review(summary.pop("_parent_review_frame"), review_path)
    text = json.dumps(summary, indent=2, default=str) + "\n"
    if ":\\" in text or "/Users/" in text or "/home/" in text:
        raise ValueError("Cross-sector report contains an absolute path")
    (core / "cross_sector_report.json").write_text(text, encoding="utf-8")


def _summary(
    quarter,
    organization_counts,
    relationships,
    govid_links,
    facilities,
    units,
    network_counts,
    decisions,
    parent_review,
    parent_summary,
    feature_rejects,
    parent_rejects,
    skipped,
    observed_types,
    michigan,
) -> dict[str, object]:
    unreadable = [row for row in skipped if row["status"] in {"draft", "no_geometry", "unreviewed"} or row["reason"] in {"draft", "no_geometry", "unreviewed"}]
    summary = {
        "quarter": quarter,
        "organizations": organization_counts,
        "relationships": len(relationships),
        "relationships_by_type": relationships["relationship_type"].value_counts().astype(int).to_dict() if not relationships.empty else {},
        "govid_links": len(govid_links),
        "facilities": len(facilities),
        "facilities_by_sector": facilities["sector"].value_counts().astype(int).to_dict() if not facilities.empty else {},
        "units": len(units),
        "units_by_sector": units["sector"].value_counts().astype(int).to_dict() if not units.empty else {},
        "network_segments": network_counts,
        "facility_matches": int(decisions["decision"].eq("match").sum()) if not decisions.empty else 0,
        "facility_review_queue": int(decisions["decision"].eq("review").sum()) if not decisions.empty else 0,
        "facility_rejects": len(feature_rejects),
        "parent_rejects": len(parent_rejects),
        "parent_review_file": "review/parents_top100.csv",
        "parent_review_verified": False,
        "parent_review_rows": len(parent_review),
        "parents": parent_summary,
        "observed_facility_types": observed_types,
        "unmapped_facility_types": [],
        "facility_thresholds_calibrated": FACILITY_THRESHOLDS_CALIBRATED,
        "draft_or_empty_not_read": unreadable,
        "michigan_wind": michigan,
        "_parent_review_frame": parent_review,
    }
    return summary


def _read_home_table(home: Path, source: Source, layer: Layer) -> pd.DataFrame:
    if source.storage != "home" or len(source.paths) != 1:
        raise ValueError(f"{source.source_id} is not one home table")
    root = (home / source.paths[0]).resolve()
    path = (root / layer.layer).resolve()
    if not path.is_relative_to(home.resolve()) or not path.is_file():
        raise ValueError(f"Missing table {layer.layer}")
    columns = [field_name(layer, name) for name in _PARENT_FIELDS]
    frame = pd.read_parquet(path, columns=columns)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{layer.layer} is missing columns: {', '.join(missing)}")
    return frame.rename(columns={source_name: logical for logical, source_name in zip(_PARENT_FIELDS, columns, strict=True)})


def _one_attribute(sources: list[Source], *logical: str) -> tuple[Source, Layer]:
    found = [
        (source, layer)
        for source in sources
        for layer in source.layers
        if all(name in layer.attribute_fields for name in logical)
    ]
    if len(found) != 1:
        raise ValueError("Expected one source table for " + ", ".join(logical))
    return found[0]


def _filter_geometries(geometries: list | None, mask, job: LayerJob) -> list | None:
    if geometries is None:
        return None
    if len(geometries) != len(mask):
        raise ValueError(f"{job.source.source_id} {job.layer.layer} geometries do not match its rows")
    return [geometry for geometry, keep in zip(geometries, mask, strict=True) if bool(keep)]


def _concat_frames(frames: list[pd.DataFrame], columns) -> pd.DataFrame:
    columns = list(columns)
    usable = [frame for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame(columns=columns)
    combined = pd.concat(usable, ignore_index=True)
    for column in columns:
        if column not in combined.columns:
            combined[column] = pd.NA
    return combined.loc[:, columns]


def _public_skip(row: dict) -> dict[str, object]:
    return {
        "source_id": row["source_id"],
        "layer": row["layer"],
        "status": row["status"],
        "reason": row["reason"],
        "grain": row["grain"],
    }


def _safe_name(sector: str) -> bool:
    return bool(sector) and "/" not in sector and "\\" not in sector and not sector.startswith(".")
