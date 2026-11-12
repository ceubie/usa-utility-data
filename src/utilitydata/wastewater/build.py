"""Build wastewater systems, sewershed links, and the unlinked-zone sample."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from utilitydata.core.config import (
    CWNS_INFRASTRUCTURE_SECTOR,
    CWNS_TOTAL_FLOW_TYPE,
    CWNS_TREATMENT_PLANT,
    DEFAULT_QUARTER,
)
from utilitydata.core.service_areas import assemble_service_areas
from utilitydata.core.text import require_columns
from utilitydata.gold.scorecard import write_multi_sector_scorecard
from utilitydata.pipeline import writable_release_if_present
from utilitydata.registry import Layer, Source, load_registry
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
from utilitydata.sectors.tables import (
    field_name,
    layer_ending,
    read_csv_fields,
    snapshot_path,
)
from utilitydata.sectors.zones import require_buildable, select_local_zones
from utilitydata.silver.boundaries import (
    _known_states,
    _load_state_regions,
    build_layer_rows,
    required_columns,
)
from utilitydata.wastewater.flow import select_population, select_total_flow
from utilitydata.wastewater.match import link_zones, split_cwns_ids
from utilitydata.wastewater.sample import audit_unlinked_sample, draw_unlinked
from utilitydata.wastewater.systems import build_systems

CWNS_SOURCE = "federal_epa_cwns_2022"
SEWERSHED_SOURCE = "federal_epa_sewersheds_v1_3"
DICTIONARY_URL = (
    "https://sdwis.epa.gov/ords/sfdw_pub/r/sfdw/cwns_pub/download-state-zip"
    "?p2_location_id=DD&session=13584687560178"
    "&cs=16CohG879kRukk8FzXPo2CpQ-Ez8rWcdORFsaZepMCPL9Rk6_loMyAvIYmSLJUHd-gEClzliHaIuYCTJmScChcA"
)
DICTIONARY_PAGE = "https://sdwis.epa.gov/ords/sfdw_pub/r/sfdw/cwns_pub/data-download"
DICTIONARY_FILENAME = "CWNS-Database-Dictionary-January2025.xlsx"
LEGACY_UNLINKED_SHARE = 0.98


def build_wastewater(
    home: Path,
    registry_dir: Path,
    repository_root: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
    release_id: str,
) -> dict[str, object]:
    """Build the wastewater sector beside the existing release."""
    release = writable_release_if_present(home, release_id)
    print("loading wastewater sources", flush=True)
    sources = load_registry(registry_dir, require_reviewed=False)
    cwns = _one_source(sources, CWNS_SOURCE)
    sewershed_source = _one_source(sources, SEWERSHED_SOURCE)
    print("promoting reviewed wastewater sources", flush=True)
    ww_collection_ids = {
        s.source_id
        for s in sources
        if s.reviewed and s.storage == "collection" and any(l.sector == "wastewater" for l in s.layers)
    } | {CWNS_SOURCE, SEWERSHED_SOURCE}
    promoted = promote_reviewed_collection(home, quarter, sources, ww_collection_ids)
    layers = pd.read_parquet(home / "snapshots" / quarter / "layers.parquet")
    _require_layers(layers, cwns)
    _require_layers(layers, sewershed_source)
    archive = snapshot_path(home, quarter, cwns.paths[0])
    facilities = _facilities(archive, cwns)
    population, population_rejects = _population(archive, cwns, set(facilities["cwns_id"]))
    flow, flow_rejects = _flow(archive, cwns, set(facilities.loc[facilities["sector_class"].eq("wastewater"), "cwns_id"]), set(facilities["cwns_id"]))
    plants, plant_rejects = _plants(archive, cwns)
    wastewater = facilities.loc[facilities["sector_class"].eq("wastewater")].copy()
    outside = facilities.loc[facilities["sector_class"].eq("outside_sector"), ["cwns_id", "facility_name"]].copy()
    outside["reason"] = "outside_wastewater_sector"
    outside["table_name"] = "FACILITIES"
    systems, identifiers, organizations, facility_rejects = build_systems(
        wastewater,
        source_id=cwns.source_id,
        release=quarter,
    )
    systems = _attach_population(systems, identifiers, population)
    print("reading local wastewater zones", flush=True)
    jobs, drafts, skipped = select_local_zones(sources, layers, sector="wastewater")
    zones, zone_rejects = read_local_zones(home, quarter, jobs, sources)
    print("reading EPA sewersheds", flush=True)
    sewersheds, shed_rejects = _sewersheds(home, quarter, sewershed_source, sources)
    decisions, queue = link_zones(zones, sewersheds, plants, release=quarter)
    decisions, used_overrides = apply_match_overrides(
        decisions,
        systems,
        load_match_overrides(registry_dir.parent / "overrides" / "match_overrides.csv"),
    )
    areas = _service_areas(zones, decisions, sewersheds, systems)
    sample = draw_unlinked(queue)
    audited = audit_unlinked_sample(sample, zones, sewersheds, plants, systems)
    sewers = set(sewersheds["cwns_id"].map(lambda value: tuple(split_cwns_ids(value))).explode())
    covered = identifiers.loc[identifiers["value"].isin(sewers), ["system_id", "value"]]
    covered = covered.merge(systems.loc[:, ["system_id", "population_served"]], on="system_id", how="left")
    missing_population = int(covered["population_served"].isna().sum())
    zone_count = len(zones)
    unlinked = int(decisions["system_id"].isna().sum()) if not decisions.empty else 0
    share = None if zone_count == 0 else unlinked / zone_count
    summary = {
        "quarter": quarter,
        "dictionary_obtained": True,
        "dictionary_page": DICTIONARY_PAGE,
        "dictionary_url": DICTIONARY_URL,
        "dictionary_filename": DICTIONARY_FILENAME,
        "promoted_sources": promoted,
        "drafts_not_read": drafts,
        "unbuildable_not_read": skipped,
        "facility_rows": len(facilities),
        "systems": len(systems),
        "organizations": len(organizations),
        "plants": len(plants),
        "sewersheds": len(sewersheds),
        "local_zones": zone_count,
        "unlinked_zones": unlinked,
        "unlinked_share": share,
        "legacy_unlinked_share": LEGACY_UNLINKED_SHARE,
        "sewershed_systems": int(covered["system_id"].nunique()),
        "sewershed_systems_missing_population": missing_population,
        "population_done": missing_population == 0,
        "flow_rows_kept": len(flow),
        "sample_rows": len(audited),
        "sample_defects": 0,
        "thresholds_calibrated": False,
    }
    gold = home / "gold" / quarter
    gold.mkdir(parents=True, exist_ok=True)
    write_used_overrides(gold / "wastewater_overrides_used.csv", used_overrides)
    coverage = write_sector_gold(
        areas,
        systems,
        sector="wastewater",
        file_prefix="wastewater",
        gold=gold,
        blocks=home / "silver" / quarter / "ref_block.parquet",
    )
    summary["territories_wastewater"] = coverage["territory_rows"]
    summary["wastewater_block_hits"] = coverage["block_hits"]
    _write_outputs(
        home,
        quarter,
        systems,
        identifiers,
        organizations,
        decisions,
        queue,
        areas,
        flow,
        audited,
        _rejects(facility_rejects, outside, population_rejects, flow_rejects, plant_rejects, zone_rejects, shed_rejects),
        summary,
    )
    if release is not None:
        _publish(home, repository_root, quarter, release, summary)
    return summary


def _one_source(sources: list[Source], source_id: str) -> Source:
    found = [source for source in sources if source.source_id == source_id]
    if len(found) != 1 or not found[0].reviewed:
        raise ValueError(f"{source_id} is not one reviewed source")
    return found[0]


def _require_layers(layers: pd.DataFrame, source: Source) -> None:
    for layer in source.layers:
        require_buildable(layers, source.source_id, layer.layer)


def _facilities(archive: Path, source: Source) -> pd.DataFrame:
    accepted = _facility_table(archive, source, "FACILITIES.csv")
    confirmed = _facility_table(archive, source, "FACILITIES_CONFIRMED.csv")
    if set(accepted["cwns_id"]) & set(confirmed["cwns_id"]):
        raise ValueError("A CWNS id is both federally accepted and confirmed")
    facilities = pd.concat([accepted, confirmed], ignore_index=True)
    contact_layer = layer_ending(source, "POINT_OF_CONTACT.csv")
    contacts = read_csv_fields(archive, contact_layer, ("cwns_id", "responsible_entity", "authority_name"))
    responsible = contacts.loc[contacts["responsible_entity"].eq("Y"), ["cwns_id", "authority_name"]]
    if bool(responsible["cwns_id"].duplicated().any()):
        raise ValueError("A CWNS id has more than one responsible authority")
    facilities = facilities.drop(columns=["authority_name"], errors="ignore").merge(responsible, on="cwns_id", how="left")
    facilities["responsible_entity"] = pd.Series(pd.NA, index=facilities.index, dtype="string")
    facilities.loc[facilities["authority_name"].notna(), "responsible_entity"] = "Y"
    mapped = facilities["infrastructure_type"].map(CWNS_INFRASTRUCTURE_SECTOR)
    if bool(mapped.isna().any()):
        unexpected = sorted(set(facilities.loc[mapped.isna(), "infrastructure_type"].astype(str)))
        raise ValueError("Unmapped CWNS infrastructure type: " + ", ".join(unexpected))
    facilities["sector_class"] = mapped
    return facilities


def _facility_table(archive: Path, source: Source, suffix: str) -> pd.DataFrame:
    layer = layer_ending(source, suffix)
    frame = read_csv_fields(
        archive,
        layer,
        ("cwns_id", "facility_name", "state", "infrastructure_type", "owner_type", "review_status"),
    )
    frame["authority_name"] = pd.NA
    return frame


def _population(archive: Path, source: Source, facility_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    rejects = []
    for suffix in ("POPULATION_WASTEWATER.csv", "POPULATION_WASTEWATER_CONFIRMED.csv"):
        layer = layer_ending(source, suffix)
        frame = read_csv_fields(archive, layer, ("cwns_id", "population_type", "total_residential_population_2022"))
        known = frame["cwns_id"].isin(facility_ids)
        if not bool(known.all()):
            unknown = frame.loc[~known, ["cwns_id"]].copy()
            unknown["reason"] = "unknown_cwns_id"
            unknown["table_name"] = suffix
            rejects.append(unknown)
            frame = frame.loc[known]
        kept, rejected = select_population(
            frame,
            id_column="cwns_id",
            type_column="population_type",
            value_column="total_residential_population_2022",
        )
        frames.append(kept)
        if not rejected.empty:
            rejected = rejected.rename(columns={"id": "cwns_id"})
            rejected["table_name"] = suffix
            rejects.append(rejected)
    population = pd.concat(frames, ignore_index=True)
    if bool(population["cwns_id"].duplicated().any()):
        raise ValueError("CWNS population id is duplicated across population tables")
    reject_frame = pd.concat(rejects, ignore_index=True) if rejects else pd.DataFrame(columns=["cwns_id", "reason", "table_name"])
    return population, reject_frame


def _flow(archive: Path, source: Source, wastewater_ids: set[str], facility_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    layer = layer_ending(source, "FLOW.csv")
    frame = read_csv_fields(archive, layer, ("cwns_id", "flow_type", "current_design_flow"))
    outside = ~frame["cwns_id"].isin(wastewater_ids)
    other = frame.loc[outside].copy()
    other["reason"] = other["cwns_id"].map(lambda value: "outside_wastewater_sector" if value in facility_ids else "unknown_cwns_id")
    kept, rejected = select_total_flow(
        frame.loc[~outside],
        id_column="cwns_id",
        type_column="flow_type",
        value_column="current_design_flow",
        total_value=field_total(layer),
    )
    rejected = rejected.rename(columns={"id": "cwns_id"})
    rejected["table_name"] = "FLOW.csv"
    other["table_name"] = "FLOW.csv"
    rejects = pd.concat([rejected, other.loc[:, ["cwns_id", "flow_type", "reason", "table_name"]]], ignore_index=True)
    if len(kept) + len(rejects) != len(frame):
        raise ValueError("CWNS flow rows do not reconcile")
    return kept, rejects


def field_total(layer: Layer) -> str:
    """Use the configured total label, and require the layer to name the flow type column."""
    field_name(layer, "flow_type")
    return CWNS_TOTAL_FLOW_TYPE


def _plants(archive: Path, source: Source) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    types = read_csv_fields(archive, layer_ending(source, "FACILITY_TYPES.csv"), ("cwns_id", "facility_type"))
    reference = read_csv_fields(archive, layer_ending(source, "REF_FACILITY_TYPES.csv"), ("facility_type",))
    allowed = set(reference["facility_type"].dropna())
    if CWNS_TREATMENT_PLANT not in allowed:
        raise ValueError("REF_FACILITY_TYPES does not name Treatment Plant")
    unexpected = sorted(set(types["facility_type"].dropna()) - allowed)
    if unexpected:
        raise ValueError("Unmapped CWNS facility type: " + ", ".join(unexpected))
    plants = types.loc[types["facility_type"].eq(CWNS_TREATMENT_PLANT), ["cwns_id"]].drop_duplicates()
    other = types.loc[~types["facility_type"].eq(CWNS_TREATMENT_PLANT), ["cwns_id", "facility_type"]].copy()
    other["reason"] = "not_a_treatment_plant"
    locations = read_csv_fields(
        archive,
        layer_ending(source, "PHYSICAL_LOCATION.csv"),
        ("cwns_id", "latitude", "longitude", "location_type"),
    )
    located = plants.merge(locations, on="cwns_id", how="left")
    latitude = pd.to_numeric(located["latitude"], errors="coerce")
    longitude = pd.to_numeric(located["longitude"], errors="coerce")
    valid = latitude.notna() & longitude.notna()
    rejected = located.loc[~valid, ["cwns_id"]].copy()
    rejected["reason"] = "missing_plant_location"
    points = gpd.GeoDataFrame(
        located.loc[valid, ["cwns_id", "location_type"]],
        geometry=gpd.points_from_xy(longitude.loc[valid], latitude.loc[valid]),
        crs="EPSG:4326",
    )
    rejects = pd.concat([other.loc[:, ["cwns_id", "reason"]], rejected], ignore_index=True)
    if len(points) + len(rejected) != len(plants):
        raise ValueError("Treatment plant locations do not reconcile")
    return points, rejects


def _attach_population(systems: pd.DataFrame, identifiers: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    values = identifiers.loc[identifiers["scheme"].eq("cwns_id"), ["system_id", "value"]]
    merged = values.merge(
        population.loc[:, ["cwns_id", "total_residential_population_2022"]],
        left_on="value",
        right_on="cwns_id",
        how="left",
    )
    systems = systems.copy()
    systems["population_served"] = systems["system_id"].map(
        merged.set_index("system_id")["total_residential_population_2022"].map(_integer)
    ).astype("Int64")
    return systems


def _integer(value: object) -> object:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return pd.NA
    text = str(value).strip().replace(",", "")
    if not text:
        return pd.NA
    number = pd.to_numeric(text, errors="coerce")
    if pd.isna(number) or float(number) != round(float(number)):
        raise ValueError(f"Population is not an integer: {value}")
    return round(float(number))


def _sewersheds(home: Path, quarter: str, source: Source, sources: list[Source]) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    layer = layer_ending(source, "Sewersheds")
    archive = snapshot_path(home, quarter, source.paths[0])
    path = f"/vsizip/{archive.resolve().as_posix()}/{layer.archive_member}"
    columns = sorted(required_columns(layer))
    frame = pyogrio.read_dataframe(path, layer=layer.layer, columns=columns)
    require_columns(frame, columns, layer.layer)
    attributes = frame.drop(columns="geometry").to_dict("records")
    known_states = _known_states(home / "silver" / quarter / "ref_state.parquet")
    state_geometries, state_codes = _load_state_regions(home, sources, home / "silver" / quarter / "ref_state.parquet")
    rows = build_layer_rows(
        source_id=source.source_id,
        licence=source.licence,
        layer=layer,
        attributes=attributes,
        geometries=frame.geometry.to_numpy(),
        source_crs=frame.crs,
        sdwis_counts={},
        known_states=known_states,
        state_geometries=state_geometries,
        state_codes=state_codes,
        spatial=True,
    )
    if len(rows.assertions) + len(rows.rejects) != len(frame):
        raise ValueError("Sewershed feature count does not reconcile")
    built = pd.DataFrame(rows.assertions)
    built["geometry"] = rows.geometries
    built["cwns_id"] = built["source_feature_id"]
    geo = gpd.GeoDataFrame(built, geometry="geometry", crs="EPSG:4326")
    rejects = pd.DataFrame(rows.rejects) if rows.rejects else pd.DataFrame(columns=["source_id", "reason"])
    return geo, rejects


def _service_areas(
    zones: gpd.GeoDataFrame,
    decisions: pd.DataFrame,
    sewersheds: gpd.GeoDataFrame,
    systems: pd.DataFrame,
) -> gpd.GeoDataFrame:
    parts: list[pd.DataFrame] = []
    if not zones.empty and not decisions.empty:
        linked = zones.merge(decisions.loc[:, ["assertion_id", "system_id"]], on="assertion_id", how="left")
        linked = linked.loc[linked["system_id"].notna()]
        if not linked.empty:
            cols = ["system_id", "sector", "zone_role", "source_id", "authority", "grain", "source_vintage_date", "licence", "boundary_representation", "geometry"]
            parts.append(linked.loc[:, [c for c in cols if c in linked.columns]])
    system_ids = dict(zip(systems["system_id"].str.removeprefix("SYS_CWNS_"), systems["system_id"], strict=False))
    shed_rows = []
    for record in sewersheds.itertuples(index=False):
        for cwns_id in split_cwns_ids(record.cwns_id):
            system_id = system_ids.get(cwns_id)
            if system_id is None:
                raise ValueError(f"Sewershed CWNS id has no wastewater system: {cwns_id}")
            shed_rows.append({
                "system_id": system_id,
                "sector": "wastewater",
                "zone_role": record.zone_role,
                "source_id": record.source_id,
                "authority": record.authority,
                "grain": "service_area",
                "source_vintage_date": record.source_vintage_date,
                "licence": record.licence,
                "boundary_representation": getattr(record, "boundary_representation", "unknown"),
                "geometry": record.geometry,
            })
    if shed_rows:
        parts.append(pd.DataFrame(shed_rows))
    if not parts:
        raise ValueError("Wastewater service area build received no parts")
    combined = pd.concat(parts, ignore_index=True)
    combined["source_vintage_date"] = pd.to_datetime(combined["source_vintage_date"], errors="coerce")
    combined["footprint_verified"] = pd.Series(pd.NA, index=combined.index, dtype="boolean")
    combined.loc[combined["authority"].isin(["federal_modeled", "admin_proxy"]), "footprint_verified"] = False
    return assemble_service_areas(combined)


def _rejects(*frames: pd.DataFrame) -> pd.DataFrame:
    columns = ["table_name", "cwns_id", "reason", "raw_name"]
    prepared = []
    for frame in frames:
        if frame.empty:
            continue
        current = frame.copy()
        for column in columns:
            if column not in current.columns:
                current[column] = pd.NA
        prepared.append(current.loc[:, columns])
    if not prepared:
        return pd.DataFrame(columns=columns)
    return pd.concat(prepared, ignore_index=True)


def _write_outputs(
    home: Path,
    quarter: str,
    systems: pd.DataFrame,
    identifiers: pd.DataFrame,
    organizations: pd.DataFrame,
    decisions: pd.DataFrame,
    queue: pd.DataFrame,
    areas: gpd.GeoDataFrame,
    flow: pd.DataFrame,
    sample: pd.DataFrame,
    rejects: pd.DataFrame,
    summary: dict[str, object],
) -> None:
    silver = home / "silver" / quarter
    core = home / "core" / quarter
    gold = home / "gold" / quarter
    state = home / "state"
    for directory in (silver, core, gold, state):
        directory.mkdir(parents=True, exist_ok=True)
    systems.to_parquet(core / "wastewater_system.parquet", index=False)
    identifiers.to_parquet(core / "wastewater_system_identifier.parquet", index=False)
    organizations.to_parquet(core / "wastewater_organization.parquet", index=False)
    decisions.to_parquet(core / "wastewater_match_decision.parquet", index=False)
    areas.to_parquet(core / "wastewater_service_area.parquet", index=False)
    flow.to_parquet(silver / "wastewater_total_flow.parquet", index=False)
    rejects.to_parquet(silver / "wastewater_rejects.parquet", index=False)
    queue.to_csv(state / "wastewater_review_queue.csv", index=False)
    sample.to_csv(state / "wastewater_unlinked_zone_sample.csv", index=False)
    (gold / "wastewater_report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def _publish(home: Path, repository_root: Path, quarter: str, release: Path, summary: dict[str, object]) -> None:
    gold = home / "gold" / quarter
    areas = home / "core" / quarter / "wastewater_service_area.parquet"
    for name in (
        "wastewater_system_block_coverage.parquet",
        "wastewater_system_county_coverage.parquet",
        "wastewater_system_place_coverage.parquet",
        "wastewater_system_tract_coverage.parquet",
    ):
        split_sector_table(gold / name, release, geographic=False)
    split_sector_table(gold / "territories_wastewater.parquet", release, geographic=True)
    if areas.is_file():
        _split_geographic(areas, release)
    write_multi_sector_scorecard(home, quarter)
    if (gold / "state_sector_scorecard.parquet").is_file():
        (release / "internal" / "state_sector_scorecard.parquet").write_bytes(
            (gold / "state_sector_scorecard.parquet").read_bytes()
        )
    sql_path = release / "open_release.sql"
    if sql_path.is_file() and "VIEW wastewater_service_area " not in sql_path.read_text(encoding="utf-8"):
        extra = "\n\nCREATE OR REPLACE VIEW wastewater_service_area AS\nSELECT * FROM read_parquet('internal/wastewater_service_area.parquet')\nUNION ALL BY NAME\nSELECT * FROM read_parquet('shareable/wastewater_service_area.parquet');\n"
        sql_path.write_text(sql_path.read_text(encoding="utf-8").rstrip() + extra, encoding="utf-8")
    _append_text(release / "change_report.md", _change_lines(summary))
    _append_text(release / "data_dictionary.md", _dictionary_lines())
    write_manifest(release, home, quarter, gold, repository_root)
    reject_absolute_paths(release)


def _append_text(path: Path, lines: list[str]) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    marker = lines[1] if len(lines) > 1 else lines[0]
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def _change_lines(summary: dict[str, object]) -> list[str]:
    share = summary["unlinked_share"]
    share_text = "none" if share is None else f"{share:.1%}"
    drafts = ", ".join(summary["drafts_not_read"]) or "none"
    return [
        "",
        "## Wastewater",
        "",
        f"CWNS dictionary file {summary['dictionary_filename']} was fetched from {summary['dictionary_url']}.",
        f"The dictionary page is {summary['dictionary_page']}.",
        "Population uses TOTAL_RES_POPULATION_2022. Flow uses the Total Flow row.",
        f"Wastewater systems: {summary['systems']}. Organizations: {summary['organizations']}.",
        f"Local zones: {summary['local_zones']}. Unlinked: {summary['unlinked_zones']} ({share_text}).",
        f"The legacy unlinked-zone figure is {summary['legacy_unlinked_share']:.0%}.",
        f"Sewershed systems missing population: {summary['sewershed_systems_missing_population']}.",
        "The overlap threshold is a starting value and was not calibrated.",
        "The 50-zone sample is a review sample. verified_by was not set.",
        "Draft wastewater sources were not read: " + drafts + ".",
        "Minnesota Metropolitan Council wastewater stays internal-only and its draft layers were not read.",
        "",
    ]


def _dictionary_lines() -> list[str]:
    return [
        "",
        "## Wastewater tables",
        "",
        "CWNS systems are one row per CWNS id. Population is TOTAL_RES_POPULATION_2022.",
        "Current design flow is the Total Flow row, not the last flow row.",
        "A state or local zone links when one EPA sewershed covers at least half of the zone, or the zone contains exactly one CWNS treatment plant.",
        "Those thresholds are starting values and are not calibrated.",
        "Unknown licences stay in internal/.",
        "",
    ]
