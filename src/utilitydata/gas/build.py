"""Build natural-gas systems and same-state name links."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq

from utilitydata.core.config import DEFAULT_QUARTER
from utilitydata.core.geometry import union_geometries
from utilitydata.core.schema import IDENTIFIER_COLUMNS
from utilitydata.core.service_areas import assemble_service_areas
from utilitydata.core.text import normalize_name, require_columns
from utilitydata.electric.boundaries import load_counties
from utilitydata.electric.build import (
    RUS_LAYER,
    _require_declared_columns,
    ensure_pudl_files,
)
from utilitydata.gas.match import StateNameIndex
from utilitydata.gas.systems import build_gas_systems
from utilitydata.gold.scorecard import write_multi_sector_scorecard
from utilitydata.pipeline import writable_release_if_present
from utilitydata.registry import Source, load_registry
from utilitydata.release.editions import _split_geographic, split_sector_table
from utilitydata.release.reports import reject_absolute_paths, write_manifest
from utilitydata.sectors.areas import read_local_zones
from utilitydata.sectors.coverage import write_sector_gold
from utilitydata.sectors.overrides import (
    apply_match_overrides,
    load_match_overrides,
    write_used_overrides,
)
from utilitydata.sectors.promote import promote_reviewed_collection
from utilitydata.sectors.tables import layer_ending, read_csv_fields, snapshot_path
from utilitydata.sectors.zones import (
    LOCAL_AUTHORITIES,
    require_buildable,
    select_local_zones,
)
from utilitydata.silver.boundaries import _known_states

PHMSA_SOURCE = "pudl_v2026_10_0_phmsagas"
EIA_SOURCE = "federal_eia176_ng_companies"
# Gas has no federal boundary file with identifiers. A reviewed national
# compilation is read with the state layers and ranks below them.
GAS_ZONE_AUTHORITIES = LOCAL_AUTHORITIES | {"federal_modeled"}
PUDL_OBJECTS = (
    "core_phmsagas__yearly_distribution_operators.parquet",
    "core_phmsagas__yearly_distribution_by_install_decade.parquet",
)


def build_gas(
    home: Path,
    registry_dir: Path,
    repository_root: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
    release_id: str,
) -> dict[str, object]:
    """Build natural gas beside the existing release. Raw FERC filings are not parsed."""
    release = writable_release_if_present(home, release_id)
    sources = load_registry(registry_dir, require_reviewed=False)
    phmsa = _one(sources, PHMSA_SOURCE)
    eia = _one(sources, EIA_SOURCE)
    ensure_pudl_files(home, phmsa)
    _require_declared_columns(home, phmsa)
    _require_exact_objects(phmsa)
    gas_collection_ids = {
        s.source_id
        for s in sources
        if s.reviewed and s.storage == "collection" and any(l.sector == "natural_gas" for l in s.layers)
    } | {EIA_SOURCE}
    promoted = promote_reviewed_collection(home, quarter, sources, gas_collection_ids)
    layers = pd.read_parquet(home / "snapshots" / quarter / "layers.parquet")
    for layer in eia.layers:
        require_buildable(layers, eia.source_id, layer.layer)
    known_states = _known_states(home / "silver" / quarter / "ref_state.parquet")
    decade = _read_pudl(home, phmsa, "core_phmsagas__yearly_distribution_by_install_decade.parquet")
    operators = _read_pudl(home, phmsa, "core_phmsagas__yearly_distribution_operators.parquet")
    systems, identifiers, organizations, rejects, counts = build_gas_systems(
        decade,
        operators,
        source_id=phmsa.source_id,
        release=quarter,
        known_states=known_states,
    )
    jobs, drafts, skipped = select_local_zones(sources, layers, sector="natural_gas", authorities=GAS_ZONE_AUTHORITIES)
    zones, zone_rejects = read_local_zones(home, quarter, jobs, sources)
    zone_decisions, zone_queue = _link_zones(zones, systems, quarter)
    zone_decisions, used_overrides = apply_match_overrides(
        zone_decisions,
        systems,
        load_match_overrides(registry_dir.parent / "overrides" / "match_overrides.csv"),
    )
    _reject_cross_state(zone_decisions, zones, systems)
    companies, company_queue, company_identifiers = _link_eia(home, quarter, eia, systems, known_states)
    identifiers = pd.concat([identifiers, company_identifiers], ignore_index=True)
    areas, missing_proxy = _areas(zones, zone_decisions, systems, home, sources, phmsa, quarter)
    summary = {
        "quarter": quarter,
        "pudl_objects": list(PUDL_OBJECTS),
        "rus_downloaded": any(s.reviewed and any(layer.layer == RUS_LAYER for layer in s.layers) for s in sources),
        "promoted_sources": promoted,
        "drafts_not_read": drafts,
        "unbuildable_not_read": skipped,
        "systems": len(systems),
        "operator_state_pairs": len(systems),
        "organizations": len(organizations),
        "distribution": counts,
        "local_zones": len(zones),
        "zones_linked": int(zone_decisions["system_id"].notna().sum()) if not zone_decisions.empty else 0,
        "zone_link_methods": {str(key): int(value) for key, value in zone_decisions["method"].value_counts().items()} if not zone_decisions.empty else {},
        "zone_sources": sorted({source.source_id for source, _layer, _status in jobs}),
        "systems_with_local_area": int(areas.loc[~areas["authority"].eq("admin_proxy"), "system_id"].nunique()),
        "eia_companies": len(companies),
        "eia_links": len(company_identifiers),
        "service_areas": len(areas),
        "systems_without_county_proxy": missing_proxy,
        "thresholds_calibrated": False,
    }
    gold = home / "gold" / quarter
    gold.mkdir(parents=True, exist_ok=True)
    write_used_overrides(gold / "gas_overrides_used.csv", used_overrides)
    coverage = write_sector_gold(
        areas,
        systems,
        sector="natural_gas",
        file_prefix="gas",
        gold=gold,
        blocks=home / "silver" / quarter / "ref_block.parquet",
    )
    summary["territories_gas"] = coverage["territory_rows"]
    summary["gas_block_hits"] = coverage["block_hits"]
    _write(home, quarter, systems, identifiers, organizations, zone_decisions, zone_queue, company_queue, areas, rejects, zone_rejects, summary)
    if release is not None:
        _publish(home, repository_root, quarter, release, summary)
    return summary


def _one(sources: list[Source], source_id: str) -> Source:
    found = [source for source in sources if source.source_id == source_id]
    if len(found) != 1 or not found[0].reviewed:
        raise ValueError(f"{source_id} is not one reviewed source")
    return found[0]


def _require_exact_objects(source: Source) -> None:
    names = [layer.layer for layer in source.layers]
    if names != list(PUDL_OBJECTS) and set(names) != set(PUDL_OBJECTS):
        raise ValueError("PHMSA source layers are not the reviewed PUDL objects")


def _read_pudl(home: Path, source: Source, layer_name: str) -> pd.DataFrame:
    layer = next(item for item in source.layers if item.layer == layer_name)
    path = home / source.paths[0] / layer.layer
    columns = sorted(set(layer.attribute_fields.values()) | set(layer.id_fields.values()))
    schema = set(pq.read_schema(path).names)
    missing = [name for name in columns if name not in schema]
    if missing:
        raise ValueError(f"{layer.layer} is missing columns: {', '.join(missing)}")
    frame = pd.read_parquet(path, columns=columns)
    require_columns(frame, columns, layer.layer)
    renamed = {source_name: logical for logical, source_name in {**layer.id_fields, **layer.attribute_fields}.items()}
    return frame.rename(columns=renamed)


def _name_index(systems: pd.DataFrame) -> StateNameIndex:
    candidates = systems.loc[:, ["system_id", "primary_state", "name"]].copy()
    candidates["state"] = candidates["primary_state"]
    candidates["name_norm"] = candidates["name"].map(normalize_name)
    return StateNameIndex(candidates)


def _link_zones(zones: gpd.GeoDataFrame, systems: pd.DataFrame, release: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = _name_index(systems)
    decisions = []
    queue = []
    if zones.empty:
        return _decision_frame(decisions), pd.DataFrame(queue)
    for record in zones.itertuples(index=False):
        state = record.geom_state if _present(record.geom_state) else record.declared_state
        if bool(record.state_mismatch):
            decisions.append(_decision(record.assertion_id, None, "review_queue", "state_mismatch", release))
            queue.append(_queue(record, "state_mismatch", state))
            continue
        system_id, reason = index.match(record.name_norm, None if not _present(state) else str(state))
        if system_id is None:
            decisions.append(_decision(record.assertion_id, None, "review_queue", reason, release))
            queue.append(_queue(record, reason, state))
            continue
        decisions.append(_decision(record.assertion_id, system_id, reason, reason, release))
    if len(decisions) != len(zones):
        raise ValueError("Gas zone decisions do not cover every zone")
    return _decision_frame(decisions), pd.DataFrame(queue)


def _link_eia(
    home: Path,
    quarter: str,
    source: Source,
    systems: pd.DataFrame,
    known_states: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    archive = snapshot_path(home, quarter, source.paths[0])
    companies = read_csv_fields(archive, layer_ending(source, "all_company_176.csv"), ("company_id", "name"))
    activity = read_csv_fields(archive, layer_ending(source, "all_data_176.csv"), ("company_id", "state", "year"))
    activity["year_number"] = pd.to_numeric(activity["year"], errors="coerce")
    if bool(activity["year_number"].isna().any()):
        raise ValueError("EIA-176 year is not numeric")
    latest = activity["year_number"].max()
    current = activity.loc[activity["year_number"].eq(latest), ["company_id", "state"]].drop_duplicates()
    current = current.merge(companies, on="company_id", how="left")
    current["reason"] = [
        None if _present(state) and str(state).upper() in known_states else "unknown_state"
        for state in current["state"]
    ]
    current.loc[current["name"].isna() & current["reason"].isna(), "reason"] = "unknown_company"
    rejected = current.loc[current["reason"].notna()].copy()
    kept = current.loc[current["reason"].isna()].copy()
    kept["state"] = kept["state"].astype(str).str.upper()
    kept["name_norm"] = kept["name"].map(normalize_name)
    index = _name_index(systems)
    identifiers = []
    queue = []
    for record in kept.itertuples(index=False):
        system_id, reason = index.match(record.name_norm, record.state)
        if system_id is None:
            queue.append({"company_id": record.company_id, "state": record.state, "name": record.name, "reason": reason})
            continue
        identifiers.append({
            "system_id": system_id,
            "scheme": "eia176",
            "value": record.company_id,
            "source_id": source.source_id,
            "state": record.state,
        })
    identifier_frame = pd.DataFrame(identifiers, columns=["system_id", "scheme", "value", "source_id", "state"])
    _reject_cross_state_identifiers(identifier_frame, systems)
    if len(identifier_frame) + len(queue) + len(rejected) != len(current):
        raise ValueError("EIA-176 company rows do not reconcile")
    queue_frame = pd.DataFrame(queue, columns=["company_id", "state", "name", "reason"])
    published = identifier_frame.loc[:, list(IDENTIFIER_COLUMNS)] if not identifier_frame.empty else pd.DataFrame(columns=list(IDENTIFIER_COLUMNS))
    return kept, queue_frame, published.reset_index(drop=True)


def _reject_cross_state(decisions: pd.DataFrame, zones: gpd.GeoDataFrame, systems: pd.DataFrame) -> None:
    linked = decisions.loc[decisions["system_id"].notna(), ["assertion_id", "system_id"]]
    if linked.empty:
        return
    states = systems.set_index("system_id")["primary_state"]
    zone_states = zones.set_index("assertion_id")["geom_state"]
    for record in linked.itertuples(index=False):
        zone_state = zone_states.get(record.assertion_id)
        system_state = states.get(record.system_id)
        if _present(zone_state) and zone_state != system_state:
            raise ValueError("A gas name match crossed a state line")


def _reject_cross_state_identifiers(identifiers: pd.DataFrame, systems: pd.DataFrame) -> None:
    if identifiers.empty:
        return
    states = systems.set_index("system_id")["primary_state"]
    for record in identifiers.itertuples(index=False):
        if states.get(record.system_id) != record.state:
            raise ValueError("A gas name match crossed a state line")


def _areas(
    zones: gpd.GeoDataFrame,
    decisions: pd.DataFrame,
    systems: pd.DataFrame,
    home: Path,
    sources: list[Source],
    proxy_source: Source,
    quarter: str,
) -> tuple[gpd.GeoDataFrame, int]:
    parts = []
    linked_systems: set[str] = set()
    if not zones.empty and not decisions.empty:
        merged = zones.merge(decisions.loc[:, ["assertion_id", "system_id"]], on="assertion_id", how="left")
        linked = merged.loc[merged["system_id"].notna()]
        linked_systems.update(linked["system_id"].astype(str))
        if not linked.empty:
            cols = ["system_id", "sector", "zone_role", "source_id", "authority", "grain", "source_vintage_date", "licence", "boundary_representation", "geometry"]
            parts.append(linked.loc[:, [c for c in cols if c in linked.columns]])
    proxies = _county_proxies(home, sources, quarter)
    proxy_rows = []
    missing_proxy = 0
    for record in systems.itertuples(index=False):
        if record.system_id in linked_systems:
            continue
        geometry = proxies.get(str(record.primary_state))
        if geometry is None:
            missing_proxy += 1
            continue
        proxy_rows.append({
            "system_id": record.system_id,
            "sector": "natural_gas",
            "zone_role": "administrative_unit_proxy",
            "source_id": proxy_source.source_id,
            "authority": "admin_proxy",
            "grain": "service_area",
            "source_vintage_date": pd.NaT,
            "licence": proxy_source.licence,
            "boundary_representation": "modeled",
            "geometry": geometry,
        })
    if proxy_rows:
        parts.append(pd.DataFrame(proxy_rows))
    if not parts:
        raise ValueError("Natural gas service area build received no parts")
    combined = pd.concat(parts, ignore_index=True)
    combined["source_vintage_date"] = pd.to_datetime(combined["source_vintage_date"], errors="coerce")
    combined["footprint_verified"] = pd.Series(pd.NA, index=combined.index, dtype="boolean")
    combined.loc[combined["authority"].isin(["admin_proxy", "federal_modeled"]), "footprint_verified"] = False
    return assemble_service_areas(combined), missing_proxy


def _county_proxies(home: Path, sources: list[Source], quarter: str) -> dict[str, object]:
    geometries, geoids, _states = load_counties(home, sources)
    reference = pd.read_parquet(home / "silver" / quarter / "ref_state.parquet", columns=["state", "usps"])
    postal = {str(state).zfill(2): str(code) for state, code in zip(reference["state"], reference["usps"], strict=True)}
    grouped: dict[str, list[object]] = {}
    for geometry, geoid in zip(geometries, geoids, strict=True):
        code = postal.get(str(geoid)[:2])
        if code is not None:
            grouped.setdefault(code, []).append(geometry)
    return {code: union_geometries(parts) for code, parts in grouped.items()}


def _present(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and pd.isna(value)) and not pd.isna(value)


def _decision(assertion_id: object, system_id: object, method: str, evidence: str, release: str) -> dict[str, object]:
    return {
        "assertion_id": assertion_id,
        "system_id": system_id,
        "method": method,
        # Only an exact name carries a score. The key methods are rules, not similarity scores.
        "score": 100.0 if method == "exact_name_state" else None,
        "evidence": evidence,
        "decided_by": "rule",
        "release": release,
    }


def _queue(record: object, reason: str, state: object) -> dict[str, object]:
    return {
        "assertion_id": record.assertion_id,
        "source_id": record.source_id,
        "geom_state": state,
        "name_norm": record.name_norm,
        "reason": reason,
    }


def _decision_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["assertion_id", "system_id", "method", "score", "evidence", "decided_by", "release"])


def _write(home, quarter, systems, identifiers, organizations, decisions, zone_queue, company_queue, areas, rejects, zone_rejects, summary) -> None:
    silver = home / "silver" / quarter
    core = home / "core" / quarter
    gold = home / "gold" / quarter
    state = home / "state"
    for directory in (silver, core, gold, state):
        directory.mkdir(parents=True, exist_ok=True)
    systems.to_parquet(core / "gas_system.parquet", index=False)
    identifiers.to_parquet(core / "gas_system_identifier.parquet", index=False)
    organizations.to_parquet(core / "gas_organization.parquet", index=False)
    decisions.to_parquet(core / "gas_match_decision.parquet", index=False)
    areas.to_parquet(core / "gas_service_area.parquet", index=False)
    rejects.to_parquet(silver / "gas_rejects.parquet", index=False)
    if not zone_rejects.empty:
        zone_rejects.to_parquet(silver / "gas_zone_rejects.parquet", index=False)
    zone_queue.to_csv(state / "gas_review_queue.csv", index=False)
    company_queue.to_csv(state / "gas_eia_review_queue.csv", index=False)
    (gold / "gas_report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _publish(home, repository_root, quarter, release, summary) -> None:
    gold = home / "gold" / quarter
    areas = home / "core" / quarter / "gas_service_area.parquet"
    for name in (
        "gas_system_block_coverage.parquet",
        "gas_system_county_coverage.parquet",
        "gas_system_place_coverage.parquet",
        "gas_system_tract_coverage.parquet",
    ):
        split_sector_table(gold / name, release, geographic=False)
    split_sector_table(gold / "territories_gas.parquet", release, geographic=True)
    if areas.is_file():
        _split_geographic(areas, release)
    write_multi_sector_scorecard(home, quarter)
    if (gold / "state_sector_scorecard.parquet").is_file():
        (release / "internal" / "state_sector_scorecard.parquet").write_bytes(
            (gold / "state_sector_scorecard.parquet").read_bytes()
        )
    sql_path = release / "open_release.sql"
    if sql_path.is_file() and "VIEW gas_service_area " not in sql_path.read_text(encoding="utf-8"):
        extra = "\n\nCREATE OR REPLACE VIEW gas_service_area AS\nSELECT * FROM read_parquet('internal/gas_service_area.parquet')\nUNION ALL BY NAME\nSELECT * FROM read_parquet('shareable/gas_service_area.parquet');\n"
        sql_path.write_text(sql_path.read_text(encoding="utf-8").rstrip() + extra, encoding="utf-8")
    path = release / "change_report.md"
    if path.is_file() and "## Natural gas" not in path.read_text(encoding="utf-8"):
        drafts = ", ".join(summary["drafts_not_read"]) or "none"
        lines = [
            "",
            "## Natural gas",
            "",
            "PUDL objects: " + ", ".join(summary["pudl_objects"]) + ".",
            "RUS tables were not downloaded.",
            f"Gas systems, one per operator and state: {summary['systems']}.",
            f"EIA-176 links within a state: {summary['eia_links']}. A link uses the strictest unique name key in that state: exact normalized name, the name without legal-form words, or the name without legal-form and generic service words. A shared key is not linked, and a name in another state is not eligible. These keys are not calibrated.",
            "A state-regulator territory outranks a federal modeled territory. Federal modeled areas are not verified footprints. A system with no linked territory uses the counties of its operating state with authority admin_proxy, which is not a best serving area.",
            "Draft gas sources were not read: " + drafts + ".",
            "",
        ]
        path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    dictionary = release / "data_dictionary.md"
    if dictionary.is_file() and "## Natural gas tables" not in dictionary.read_text(encoding="utf-8"):
        section = """
## Natural gas tables

A gas system is one PHMSA operator in one operating state. `office_state` is the office location and is not the service state.

EIA-176 companies and gas territories link by a name key that is unique in one state. The strictest key that finds one system decides: the exact normalized name, the name without legal-form words, or the name without legal-form and generic service words. Two systems sharing a key are not linked. A system in another state is not eligible. The keys are not a calibrated measurement.

A state-regulator territory outranks a federal modeled territory when both link to the same system. Federal modeled areas have `footprint_verified` false. A system with no linked territory uses the counties of its operating state with authority `admin_proxy`, and that proxy is not a best serving area.

Unknown licences stay in `internal/`. PUDL tables use CC-BY-4.0.
"""
        dictionary.write_text(dictionary.read_text(encoding="utf-8").rstrip() + "\n" + section, encoding="utf-8")
    write_manifest(release, home, quarter, home / "gold" / quarter, repository_root)
    reject_absolute_paths(release)
