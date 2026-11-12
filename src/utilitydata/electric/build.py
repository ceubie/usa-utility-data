"""Build the electric sector beside the drinking-water tables."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely

from utilitydata.core.config import (
    BEST_ROLES,
    DEFAULT_QUARTER,
    EIA_NONUTILITY_IDS,
    ELECTRIC_BEST_AREA_LAND_RATIO,
    ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER,
    ELECTRIC_DIRECT_SERVICE_YEARS,
    ELECTRIC_THRESHOLDS_CALIBRATED,
)
from utilitydata.core.geometry import union_geometries
from utilitydata.core.service_areas import assemble_service_areas, mark_best
from utilitydata.core.text import require_columns
from utilitydata.electric.boundaries import build_boundary_assertions, parse_eia_id
from utilitydata.electric.coverage import build_electric_coverage, write_territories
from utilitydata.electric.match import RULE, area_is_eligible, match_zones
from utilitydata.electric.sales import (
    aggregate_retail,
    build_systems,
    direct_service_utilities,
    electric_system_id,
    entity_types_for_year,
    split_sales,
)
from utilitydata.electric.schema import (
    CODE_COLUMNS,
    DECISION_COLUMNS,
    ENTITY_COLUMNS,
    RELIABILITY_COLUMNS,
    SALES_COLUMNS,
    TERRITORY_COLUMNS,
)
from utilitydata.gold.scorecard import write_multi_sector_scorecard
from utilitydata.pipeline import writable_release
from utilitydata.registry import Source, load_registry
from utilitydata.release.accuracy import evaluate_truth, load_truth
from utilitydata.release.editions import _split_attribute, _split_geographic
from utilitydata.release.reports import reject_absolute_paths, write_manifest
from utilitydata.sectors.overrides import (
    apply_match_overrides,
    load_match_overrides,
    write_used_overrides,
)
from utilitydata.sectors.promote import promote_reviewed_collection
from utilitydata.silver.boundaries import _known_states

SALES_LAYER = "core_eia861__yearly_sales.parquet"
TERRITORY_LAYER = "core_eia861__yearly_service_territory.parquet"
CODE_LAYER = "core_eia860__scd_utilities.parquet"
ENTITY_LAYER = "core_eia__entity_utilities.parquet"
RELIABILITY_LAYER = "core_eia861__yearly_reliability.parquet"
RUS_LAYER = "_core_rus7__forensics_entity_resolution_borrowers.parquet"
PROFILE_LAYERS = (
    "core_eia__entity_plants.parquet",
    "out_eia__yearly_generators.parquet",
    "out_eia860__yearly_ownership.parquet",
    "out_sec10k__parents_and_subsidiaries.parquet",
    "core_eia861__yearly_operational_data_misc.parquet",
    "core_eia861__yearly_mergers.parquet",
    "core_pudl__assn_eia_pudl_utilities.parquet",
    "out_eia861__yearly_utility_service_territory.parquet",
)


def build_electric(
    home: Path,
    registry_dir: Path,
    repository_root: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
    release_id: str,
) -> dict[str, object]:
    """Build electric silver, core, and gold and add them to the existing release."""
    release = writable_release(home, release_id)
    sources = load_registry(registry_dir, require_reviewed=False)
    electric_collection_ids = {
        s.source_id
        for s in sources
        if s.reviewed and s.storage == "collection" and any(l.sector == "electric" and l.grain == "service_area" for l in s.layers)
    }
    if electric_collection_ids:
        promote_reviewed_collection(home, quarter, sources, electric_collection_ids)
    source = _source_with_layer(sources, SALES_LAYER)
    ensure_pudl_files(home, source)
    rus_sources = [s for s in sources if s.reviewed and any(layer.layer == RUS_LAYER for layer in s.layers)]
    if len(rus_sources) > 1:
        raise ValueError(f"Expected at most one reviewed source for {RUS_LAYER}")
    if rus_sources:
        ensure_pudl_files(home, rus_sources[0])
        _require_declared_columns(home, rus_sources[0])
    _require_declared_columns(home, source)
    known_states = _known_states(home / "silver" / quarter / "ref_state.parquet")
    sales = _read(home, source, SALES_LAYER, SALES_COLUMNS)
    kept, prior, sale_rejects, sale_counts = split_sales(sales, known_states=known_states)
    retail, by_state = aggregate_retail(kept)
    direct_service = direct_service_utilities(
        sales,
        years=ELECTRIC_DIRECT_SERVICE_YEARS,
        mwh_per_customer=ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER,
    )
    entities = _read(home, source, ENTITY_LAYER, ENTITY_COLUMNS)
    entity_names = entities.set_index(entities["utility_id_eia"].astype(int))["utility_name_eia"]
    retail_names = retail.set_index(retail["utility_id_eia"].astype(int))["utility_name_eia"]
    names = entity_names.combine_first(retail_names)
    codes = entity_types_for_year(_read(home, source, CODE_LAYER, CODE_COLUMNS), sale_counts["report_date"])
    code_source = _source_with_layer(sources, CODE_LAYER)
    systems, identifiers, system_states, organizations, code_rejects = build_systems(
        entities,
        retail,
        by_state,
        codes,
        release=quarter,
        source_id=source.source_id,
        code_source_id=code_source.source_id,
    )
    if rus_sources:
        identifiers = _attach_rus_identifiers(home, rus_sources[0], systems, identifiers)
    territory = _read(home, source, TERRITORY_LAYER, TERRITORY_COLUMNS)
    silver = home / "silver" / quarter
    silver.mkdir(parents=True, exist_ok=True)
    assertions, boundary_rejects, county_rejects, boundary_report, county_geometries, county_index, reported = _cached_boundaries(
        home, sources, quarter, territory, names, silver
    )
    print("matching electric zones", flush=True)
    decisions, queue = _link(assertions, systems, identifiers, system_states, reported, county_geometries, county_index, quarter)
    decisions, used_overrides = apply_match_overrides(
        decisions,
        systems,
        load_match_overrides(registry_dir.parent / "overrides" / "match_overrides.csv"),
    )
    direct_service_systems = {electric_system_id(value) for value in direct_service["utility_id_eia"]}
    areas = _service_areas(assertions, decisions, reported, county_geometries, county_index, direct_service_systems)
    active_best = _gold_areas(areas, systems)
    core = home / "core" / quarter
    gold = home / "gold" / quarter
    for directory in (silver, core, gold, home / "state"):
        directory.mkdir(parents=True, exist_ok=True)
    write_used_overrides(gold / "electric_overrides_used.csv", used_overrides)
    assertions = _coerce_assertions(assertions)
    assertions.to_parquet(silver / "electric_boundary_assertion.parquet", index=False)
    _write_frame(systems, core / "electric_system.parquet")
    _write_frame(identifiers, core / "electric_system_identifier.parquet")
    _write_frame(system_states, core / "electric_system_state.parquet")
    _write_frame(organizations, core / "electric_organization.parquet")
    _write_frame(decisions, core / "electric_match_decision.parquet")
    areas.drop(columns=["geometry"]).to_parquet(core / "electric_service_area_attributes.parquet", index=False)
    areas.to_parquet(core / "electric_service_area.parquet", index=False)
    queue.to_csv(home / "state" / "electric_review_queue.csv", index=False)
    rejects = pd.concat([sale_rejects, county_rejects, code_rejects], ignore_index=True)
    _write_frame(rejects, silver / "electric_rejects.parquet")
    _write_frame(prior, silver / "electric_sales_history.parquet")
    _write_frame(kept, silver / "electric_sales_retail.parquet")
    reliability, reliability_rejects = _reliability(_read_all(home, source, RELIABILITY_LAYER), set(names.index.astype(int)))
    _write_frame(reliability, silver / "electric_reliability.parquet")
    if not reliability_rejects.empty:
        _write_frame(pd.concat([rejects, reliability_rejects], ignore_index=True), silver / "electric_rejects.parquet")
    profiles = {name: _profile(home / source.paths[0] / name) for name in PROFILE_LAYERS}
    print("writing electric territories", flush=True)
    prev_territories_hash = (
        pq.read_table(gold / "territories_electric.parquet", columns=["service_area_id", "licence", "boundary_representation"]).to_pydict()
        if (gold / "territories_electric.parquet").is_file()
        else None
    )
    territory_rows = write_territories(active_best, gold / "territories_electric.parquet", sector="electric")
    curr_territories_hash = pq.read_table(
        gold / "territories_electric.parquet", columns=["service_area_id", "licence", "boundary_representation"]
    ).to_pydict()
    if prev_territories_hash != curr_territories_hash:
        for stale_cov in (
            "electric_system_block_coverage.parquet",
            "electric_system_county_coverage.parquet",
            "electric_system_place_coverage.parquet",
            "electric_system_tract_coverage.parquet",
        ):
            (gold / stale_cov).unlink(missing_ok=True)
    print("assigning electric block internal points", flush=True)
    coverage = build_electric_coverage(
        territories=gold / "territories_electric.parquet",
        blocks=silver / "ref_block.parquet",
        states=silver / "ref_state.parquet",
        output=gold,
        work=gold / "electric_work",
        home=home,
        sources=sources,
        quarter=quarter,
    )
    latest_reliability = reliability.loc[reliability["report_date"].astype(str).str.slice(0, 10) == sale_counts["report_date"]].copy()
    if latest_reliability.empty:
        latest_date = str(pd.to_datetime(reliability["report_date"]).max().date())
        latest_reliability = reliability.loc[reliability["report_date"].astype(str).str.slice(0, 10) == latest_date].copy()
    latest_reliability["licence"] = source.licence
    latest_reliability["source_id"] = source.source_id
    _write_frame(latest_reliability, gold / "electric_reliability.parquet")
    agreement = _county_agreement(active_best, reported, county_geometries, county_index)
    truth = evaluate_truth(load_truth(repository_root / "registry" / "truth" / "electric.csv"), gold / "territories_electric.parquet")
    summary = {
        "quarter": quarter,
        "pudl_objects": [layer.layer for layer in source.layers],
        "sales": sale_counts,
        "systems": len(systems),
        "active_retail": int(systems["status"].eq("active").sum()),
        "system_state_rows": len(system_states),
        "organizations": len(organizations),
        "assertions": len(assertions),
        "review_queue": int(queue["assertion_id"].nunique()) if not queue.empty else 0,
        "territories_electric": territory_rows,
        "boundaries": boundary_report,
        "boundary_rejects": {
            "path": "silver/" + quarter + "/electric_boundary_rejects.parquet",
            "by_reason": {str(reason): int(count) for reason, count in boundary_rejects["reason"].value_counts().sort_index().items()},
        },
        "coverage": {key: value for key, value in coverage.items() if key != "land_ratios"},
        "land_ratios": coverage["land_ratios"],
        "county_agreement": agreement,
        "verified_truth_rows": truth["verified_rows"],
        "profiles": profiles,
        "sec10k_note": "out_sec10k__parents_and_subsidiaries is experimental and is not a complete parent map.",
        "thresholds_calibrated": ELECTRIC_THRESHOLDS_CALIBRATED,
        "best_area_land_limit": ELECTRIC_BEST_AREA_LAND_RATIO,
        "direct_service": {
            "mwh_per_customer_limit": ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER,
            "report_years": ELECTRIC_DIRECT_SERVICE_YEARS,
            "calibrated": ELECTRIC_THRESHOLDS_CALIBRATED,
            "systems": [
                {
                    "system_id": electric_system_id(record.utility_id_eia),
                    "name": names.get(int(record.utility_id_eia)),
                    "years_measured": int(record.years_measured),
                    "min_mwh_per_customer": round(float(record.min_mwh_per_customer), 1),
                }
                for record in direct_service.itertuples(index=False)
            ],
        },
    }
    (gold / "electric_report.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    _publish(home, repository_root, quarter, release, summary, truth)
    return summary


BOUNDARY_CACHE = 3
BOUNDARY_INPUT_LAYERS = (TERRITORY_LAYER, "tiger_county")


def _is_boundary_input(layer) -> bool:
    return (layer.sector == "electric" and layer.grain == "service_area") or layer.layer in BOUNDARY_INPUT_LAYERS


def boundary_signature(home: Path, sources: list[Source], quarter: str) -> list[list[object]]:
    """Return what the saved boundary extract depends on: declarations and the content of their files."""
    manifest = pd.read_parquet(home / "snapshots" / quarter / "manifest.parquet", columns=["source_id", "relative_path", "sha256"])
    signature: list[list[object]] = []
    for source in sources:
        layers = [layer for layer in source.layers if _is_boundary_input(layer)]
        if not source.reviewed or not layers:
            continue
        if source.storage == "collection":
            rows = manifest.loc[manifest["source_id"].eq(source.source_id)].sort_values("relative_path")
            content = [[str(path), str(digest)] for path, digest in zip(rows["relative_path"], rows["sha256"], strict=True)]
        else:
            stored = home / source.paths[0]
            content = [[layer.layer, _file_sha256(stored if stored.is_file() else stored / layer.layer)] for layer in layers]
        signature.append([
            source.source_id,
            source.licence,
            list(source.paths),
            [layer.model_dump(mode="json", exclude={"notes"}) for layer in layers],
            content,
        ])
    return json.loads(json.dumps(sorted(signature, key=lambda item: item[0])))


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _cached_boundaries(home, sources, quarter, territory, names, silver: Path):
    """Reuse a saved boundary extract when the declarations and their input files are unchanged."""
    signature = boundary_signature(home, sources, quarter)
    meta_path = silver / "electric_boundary_cache.json"
    assertion_path = silver / "electric_boundary_assertion.parquet"
    boundary_reject_path = silver / "electric_boundary_rejects.parquet"
    reject_path = silver / "electric_county_rejects.parquet"
    county_path = silver / "electric_county_geometry.parquet"
    reported_path = silver / "electric_reported_counties.parquet"
    saved = (meta_path, assertion_path, boundary_reject_path, reject_path, county_path, reported_path)
    if all(path.is_file() for path in saved):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("revision") == BOUNDARY_CACHE and meta.get("signature") == signature:
            print("reusing electric boundaries", flush=True)
            assertions = gpd.read_parquet(assertion_path)
            counties = gpd.read_parquet(county_path)
            reported_frame = pd.read_parquet(reported_path)
            reported: dict[int, set[str]] = {}
            for utility_id, geoid in zip(reported_frame["utility_id_eia"], reported_frame["county_geoid"], strict=True):
                reported.setdefault(int(utility_id), set()).add(str(geoid))
            return (
                assertions,
                pd.read_parquet(boundary_reject_path),
                pd.read_parquet(reject_path),
                meta["report"],
                list(counties.geometry),
                counties["county_geoid"].astype(str).tolist(),
                reported,
            )
    print("building electric boundaries", flush=True)
    assertions, boundary_rejects, county_rejects, report, geometries, index, reported = build_boundary_assertions(
        home, sources, quarter=quarter, territory=territory, names=names
    )
    assertions = _coerce_assertions(assertions)
    assertions.to_parquet(assertion_path, index=False)
    boundary_rejects.to_parquet(boundary_reject_path, index=False)
    county_rejects.to_parquet(reject_path, index=False)
    gpd.GeoDataFrame({"county_geoid": index}, geometry=geometries, crs="EPSG:4326").to_parquet(county_path, index=False)
    reported_rows = [
        {"utility_id_eia": utility_id, "county_geoid": geoid}
        for utility_id, counties in reported.items()
        for geoid in sorted(counties)
    ]
    pd.DataFrame(reported_rows, columns=["utility_id_eia", "county_geoid"]).to_parquet(reported_path, index=False)
    meta_path.write_text(
        json.dumps({"revision": BOUNDARY_CACHE, "signature": signature, "report": report}, default=str) + "\n",
        encoding="utf-8",
    )
    return assertions, boundary_rejects, county_rejects, report, geometries, index, reported


def _attach_rus_identifiers(
    home: Path,
    rus_source: Source,
    systems: pd.DataFrame,
    identifiers: pd.DataFrame,
) -> pd.DataFrame:
    frame = _read(home, rus_source, RUS_LAYER, ("borrower_id_rus", "column_name", "record_value", "is_candidate"))
    eia_rows = frame.loc[
        frame["column_name"].astype(str).eq("utility_id_eia")
        & frame["is_candidate"].fillna(False).astype(bool)
        & frame["borrower_id_rus"].notna()
        & frame["record_value"].notna()
    ]
    known_systems = set(systems["system_id"].astype(str))
    extra = []
    seen: set[tuple[str, str]] = set()
    for row in eia_rows.itertuples(index=False):
        uid = parse_eia_id(row.record_value)
        if uid is None:
            continue
        sys_id = electric_system_id(uid)
        borrower = str(row.borrower_id_rus).strip()
        if sys_id not in known_systems or not borrower or (sys_id, borrower) in seen:
            continue
        seen.add((sys_id, borrower))
        extra.append({
            "system_id": sys_id,
            "scheme": "rus_borrower",
            "value": borrower,
            "source_id": rus_source.source_id,
        })
    if not extra:
        return identifiers
    return pd.concat([identifiers, pd.DataFrame(extra)], ignore_index=True)


def _coerce_assertions(assertions: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Give vintage and EIA id columns one type before they are written."""
    assertions = assertions.copy()
    assertions["source_vintage_date"] = pd.to_datetime(assertions["source_vintage_date"].map(_vintage_text), errors="coerce")
    assertions["eia_utility_id"] = pd.to_numeric(assertions["eia_utility_id"], errors="coerce").astype("Int64")
    return assertions


def _vintage_text(value: object) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return str(value.isoformat())[:10]
    return str(value)[:10]


def ensure_pudl_files(home: Path, source: Source) -> None:
    """Download any missing PUDL objects with a path-style anonymous S3 secret."""
    directory = (home / source.paths[0]).resolve()
    if not directory.is_relative_to(home.resolve()):
        raise ValueError("PUDL path escapes the data root")
    directory.mkdir(parents=True, exist_ok=True)
    missing = [layer.layer for layer in source.layers if not (directory / layer.layer).is_file()]
    if not missing:
        return
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute(
            """
            CREATE OR REPLACE SECRET pudl (
              TYPE s3,
              KEY_ID '',
              SECRET '',
              REGION 'us-west-2',
              ENDPOINT 's3.us-west-2.amazonaws.com',
              URL_STYLE 'path',
              SCOPE 's3://pudl.catalyst.coop'
            )
            """
        )
        for name in missing:
            target = directory / name
            connection.execute(
                "COPY (SELECT * FROM read_parquet(?)) TO ? (FORMAT parquet)",
                [f"s3://pudl.catalyst.coop/v2026.10.0/{name}", str(target)],
            )
    finally:
        connection.close()


def _source_with_layer(sources: list[Source], layer_name: str) -> Source:
    found = [source for source in sources if any(layer.layer == layer_name for layer in source.layers) and source.reviewed]
    if len(found) != 1:
        raise ValueError(f"Expected one reviewed source for {layer_name}")
    return found[0]


def _require_declared_columns(home: Path, source: Source) -> None:
    for layer in source.layers:
        path = home / source.paths[0] / layer.layer
        names = set(pq.read_schema(path).names)
        declared = set(layer.attribute_fields.values()) | set(layer.id_fields.values())
        missing = sorted(declared - names)
        if missing:
            raise ValueError(f"{layer.layer} is missing columns: {', '.join(missing)}")


def _read(home: Path, source: Source, layer_name: str, columns: tuple[str, ...]) -> pd.DataFrame:
    path = home / source.paths[0] / layer_name
    names = set(pq.read_schema(path).names)
    missing = [name for name in columns if name not in names]
    if missing:
        raise ValueError(f"{layer_name} is missing columns: {', '.join(missing)}")
    return pd.read_parquet(path, columns=list(columns))


def _read_all(home: Path, source: Source, layer_name: str) -> pd.DataFrame:
    path = home / source.paths[0] / layer_name
    frame = pd.read_parquet(path)
    require_columns(frame, RELIABILITY_COLUMNS, layer_name)
    return frame


def _link(
    assertions: gpd.GeoDataFrame,
    systems: pd.DataFrame,
    identifiers: pd.DataFrame,
    system_states: pd.DataFrame,
    reported: dict[int, set[str]],
    county_geometries: list[object],
    county_index: list[str],
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    system_by_utility = {
        int(value): system_id
        for system_id, value in zip(
            identifiers.loc[identifiers["scheme"].eq("eia_utility"), "system_id"],
            identifiers.loc[identifiers["scheme"].eq("eia_utility"), "value"],
            strict=True,
        )
    }
    names = systems.assign(utility_id=systems["system_id"].map(_utility_id)).set_index("utility_id")["name"].to_dict()
    state_map: dict[int, set[str]] = {}
    for record in system_states.itertuples(index=False):
        state_map.setdefault(_utility_id(record.system_id), set()).add(str(record.state))
    eia_ids = assertions["eia_utility_id"].map(parse_eia_id)
    direct = eia_ids.notna() & eia_ids.isin(system_by_utility)
    decisions = []
    for record, utility_id in zip(assertions.loc[direct].itertuples(index=False), eia_ids.loc[direct], strict=True):
        method = "reported_counties" if record.authority == "admin_proxy" else "eia_id"
        decisions.append({
            "assertion_id": record.assertion_id,
            "system_id": system_by_utility[int(utility_id)],
            "method": method,
            "score": 100.0,
            "evidence": f"utility_id_eia={int(utility_id)}",
            "decided_by": RULE,
            "release": release,
        })
    zones = assertions.loc[~direct, ["assertion_id", "source_id", "raw_name", "geom_state"]].copy()
    geometries = pd.Series(list(assertions.geometry), index=assertions["assertion_id"].astype(str))
    zone_geometries = geometries.reindex(zones["assertion_id"].astype(str))
    hifld_by_utility = _hifld_by_utility(assertions.loc[direct & assertions["authority"].eq("federal_modeled")])
    utilities_by_county: dict[str, set[int]] = {}
    for utility_id, counties in reported.items():
        if utility_id not in system_by_utility:
            continue
        for geoid in counties:
            utilities_by_county.setdefault(geoid, set()).add(utility_id)
    matched, queue = match_zones(
        zones,
        zone_geometries,
        county_geometries=county_geometries,
        county_index=county_index,
        counties_by_utility=reported,
        utilities_by_county=utilities_by_county,
        names={utility_id: str(name) for utility_id, name in names.items() if pd.notna(name)},
        states=state_map,
        hifld_by_utility=hifld_by_utility,
        system_by_utility=system_by_utility,
        release=release,
    )
    all_decisions = pd.concat([pd.DataFrame(decisions, columns=list(DECISION_COLUMNS)), matched], ignore_index=True)
    if len(all_decisions) != len(assertions) or bool(all_decisions["assertion_id"].duplicated().any()):
        raise ValueError("Electric match decisions do not cover every assertion exactly once")
    return all_decisions, queue


def _service_areas(
    assertions: gpd.GeoDataFrame,
    decisions: pd.DataFrame,
    reported: dict[int, set[str]],
    county_geometries: list[object],
    county_index: list[str],
    direct_service_systems: set[str],
) -> gpd.GeoDataFrame:
    """Assemble areas and mark best ones. Direct-service and wholesale suppliers never get a best area."""
    linked = assertions.merge(decisions.loc[:, ["assertion_id", "system_id"]], on="assertion_id", how="left")
    parts = linked.loc[linked["system_id"].notna(), [
        "system_id", "sector", "zone_role", "source_id", "authority", "grain",
        "source_vintage_date", "licence", "boundary_representation", "geometry",
    ]].copy()
    if parts.empty:
        raise ValueError("No electric assertion was linked to a system")
    parts["source_vintage_date"] = pd.to_datetime(parts["source_vintage_date"], errors="coerce")
    parts["footprint_verified"] = parts["authority"].map(lambda value: False if value in {"admin_proxy", "federal_modeled"} else pd.NA)
    areas = assemble_service_areas(parts)
    covered = _covered_counties(areas, county_geometries, county_index)
    eligible = []
    for index, record in areas.iterrows():
        if record.system_id in direct_service_systems:
            continue
        utility_id = _utility_id(record.system_id)
        if area_is_eligible(covered.get(record.service_area_id, set()), reported.get(utility_id, set())):
            eligible.append(index)
    areas["is_best"] = False
    if eligible:
        marked = mark_best(areas.loc[eligible].copy())
        areas.loc[marked.index, "is_best"] = marked["is_best"].to_numpy()
    return areas


def _gold_areas(areas: gpd.GeoDataFrame, systems: pd.DataFrame) -> gpd.GeoDataFrame:
    selected = areas.loc[areas["is_best"], ["service_area_id", "geometry"]].copy()
    attributes = areas.loc[areas["is_best"]].drop(columns=["geometry"])
    best = attributes.merge(
        systems.loc[:, ["system_id", "name", "status", "primary_state", "in_federal_registry", "population_served"]],
        on="system_id",
        how="left",
    )
    best = best.merge(selected, on="service_area_id", how="left")
    best = best.loc[best["status"].eq("active") & best["zone_role"].isin(BEST_ROLES)].copy()
    if best.empty:
        raise ValueError("No active electric best area was selected")
    if best["licence"].isna().any():
        raise ValueError("An electric best area is missing a licence")
    return gpd.GeoDataFrame(best, geometry="geometry", crs="EPSG:4326")


def _hifld_by_utility(frame: gpd.GeoDataFrame) -> dict[int, object]:
    territories: dict[int, object] = {}
    if frame.empty:
        return territories
    for utility_id, group in frame.groupby(frame["eia_utility_id"].map(parse_eia_id)):
        if utility_id is None or (isinstance(utility_id, float) and pd.isna(utility_id)):
            continue
        territories[int(utility_id)] = union_geometries(list(group.geometry))
    return territories


def _covered_counties(areas: gpd.GeoDataFrame, county_geometries: list[object], county_index: list[str]) -> dict[str, set[str]]:
    points = shapely.point_on_surface(np.asarray(county_geometries, dtype=object))
    tree = shapely.STRtree(np.asarray(areas.geometry.values, dtype=object))
    hits = tree.query(points, predicate="covered_by")
    covered: dict[str, set[str]] = {}
    if len(hits):
        area_ids = areas["service_area_id"].astype(str).to_numpy()
        for point_index, area_index in zip(hits[0], hits[1], strict=True):
            covered.setdefault(area_ids[int(area_index)], set()).add(county_index[int(point_index)])
    return covered


def _county_agreement(
    areas: gpd.GeoDataFrame,
    reported: dict[int, set[str]],
    county_geometries: list[object],
    county_index: list[str],
) -> dict[str, object]:
    covered = _covered_counties(areas, county_geometries, county_index)
    compared = 0
    equal = 0
    jaccard_total = 0.0
    for record in areas.itertuples(index=False):
        utility_id = _utility_id(record.system_id)
        filing = reported.get(utility_id, set())
        if not filing:
            continue
        implied = covered.get(str(record.service_area_id), set())
        compared += 1
        union = filing | implied
        score = len(filing & implied) / len(union) if union else 0.0
        jaccard_total += score
        if implied == filing:
            equal += 1
    return {
        "utilities_compared": compared,
        "utilities_equal": equal,
        "mean_jaccard": None if compared == 0 else jaccard_total / compared,
        "verified_rows": 0,
    }


def _reliability(frame: pd.DataFrame, valid_ids: set[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = []
    system_ids = []
    for utility_id in frame["utility_id_eia"]:
        if pd.isna(utility_id):
            reasons.append("missing_utility_id")
            system_ids.append(pd.NA)
            continue
        identifier = int(utility_id)
        if identifier in EIA_NONUTILITY_IDS:
            reasons.append("nonutility_respondent")
            system_ids.append(pd.NA)
            continue
        if identifier not in valid_ids:
            reasons.append("unknown_utility")
            system_ids.append(pd.NA)
            continue
        reasons.append(None)
        system_ids.append(electric_system_id(identifier))
    kept = frame.copy()
    kept["system_id"] = system_ids
    kept["reject_reason"] = reasons
    rejects = kept.loc[kept["reject_reason"].notna(), ["utility_id_eia", "state", "reject_reason"]]
    rejects = rejects.rename(columns={"reject_reason": "reason"})
    rejects["table_name"] = RELIABILITY_LAYER
    rejects["raw_name"] = None
    kept = kept.loc[kept["reject_reason"].isna()].drop(columns=["reject_reason"])
    if len(kept) + len(rejects) != len(frame):
        raise ValueError("Reliability rows do not reconcile")
    return kept, rejects


def _profile(path: Path) -> dict[str, object]:
    connection = duckdb.connect()
    try:
        columns = {row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(path)}')").fetchall()}
        date_sql = "min(report_date), max(report_date)" if "report_date" in columns else "NULL, NULL"
        row = connection.execute(
            f"SELECT count(*), {date_sql} FROM read_parquet('{_sql_path(path)}')"
        ).fetchone()
    finally:
        connection.close()
    return {
        "rows": int(row[0]) if row else 0,
        "min_report_date": None if row is None or row[1] is None else str(row[1]),
        "max_report_date": None if row is None or row[2] is None else str(row[2]),
    }


def _publish(home: Path, repository_root: Path, quarter: str, release: Path, summary: dict[str, object], truth: dict[str, object]) -> None:
    gold = home / "gold" / quarter
    attribute_tables = (
        "electric_system_block_coverage.parquet",
        "electric_system_county_coverage.parquet",
        "electric_system_place_coverage.parquet",
        "electric_system_tract_coverage.parquet",
        "electric_reliability.parquet",
    )
    for name in attribute_tables:
        _split_attribute(gold / name, release)
    _split_geographic(gold / "territories_electric.parquet", release)
    write_multi_sector_scorecard(home, quarter)
    if (gold / "state_sector_scorecard.parquet").is_file():
        (release / "internal" / "state_sector_scorecard.parquet").write_bytes(
            (gold / "state_sector_scorecard.parquet").read_bytes()
        )
    _append_dictionary(release / "data_dictionary.md")
    _append_accuracy(release / "accuracy_report.md", summary, truth)
    _append_change(release / "change_report.md", summary)
    _append_views(release / "open_release.sql")
    write_manifest(release, home, quarter, gold, repository_root)
    reject_absolute_paths(release)


def _append_dictionary(path: Path) -> None:
    marker = "## Electric tables"
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    section = """
## Electric tables

Electric sales, service territory, reliability, plants, generators, ownership, and the SEC 10-K subsidiary extract are from the Public Utility Data Liberation (PUDL) project, release v2026.10.0, published by Catalyst Cooperative under CC-BY-4.0.

`out_sec10k__parents_and_subsidiaries` is experimental. Its coverage ends in 2023. It is not a complete map of parents and subsidiaries.

`territories_electric` and the `electric_system_*_coverage` tables use the best active retail area. Coverage assigns a census block when that area covers the block internal point. HIFLD retail territories are a frozen modeled compilation. EIA-861 county unions are an administrative proxy.

Unknown licences stay in `internal/`. PUDL tables use CC-BY-4.0 and can be shared with attribution.
"""
    path.write_text(text.rstrip() + "\n" + section, encoding="utf-8")


def _append_accuracy(path: Path, summary: dict[str, object], truth: dict[str, object]) -> None:
    agreement = summary["county_agreement"]
    lines = [
        "",
        "## Electric county agreement",
        "",
        "Counties implied by the best electric polygon are the counties whose internal point the polygon covers.",
        "They are compared with the utility's latest EIA-861 county list.",
        f"Utilities compared: {agreement['utilities_compared']}.",
        f"Utilities whose county sets are equal: {agreement['utilities_equal']}.",
        f"Mean Jaccard: {agreement['mean_jaccard']}.",
        "",
        "## Electric verified truth rows",
        "",
        f"Verified truth rows: {truth['verified_rows']}.",
        f"Point tests passed: {truth['passed']}. Point tests failed: {truth['failed']}.",
        "",
        "The truth file is registry/truth/electric.csv. No rows were added.",
        "",
    ]
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def _append_change(path: Path, summary: dict[str, object]) -> None:
    if "## Electric" in path.read_text(encoding="utf-8"):
        return
    drafts = ", ".join(summary["boundaries"]["drafts_not_read"]) or "none"
    lines = [
        "",
        "## Electric",
        "",
        "PUDL v2026.10.0 objects used: " + ", ".join(summary["pudl_objects"]) + ".",
        "Electric name and HIFLD-overlap thresholds are starting values and were not calibrated.",
        "The SEC 10-K subsidiary table is experimental and was not treated as complete.",
        "Draft electric sources were not read: " + drafts + ".",
        "Gas PHMSA and RUS tables in this PUDL release were not downloaded and are left for a later sector.",
        "",
    ]
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def _append_views(path: Path) -> None:
    names = (
        "territories_electric",
        "electric_system_block_coverage",
        "electric_system_county_coverage",
        "electric_system_place_coverage",
        "electric_system_tract_coverage",
        "electric_reliability",
    )
    text = path.read_text(encoding="utf-8")
    extra = []
    for name in names:
        if f"VIEW {name} " in text:
            continue
        extra.extend([
            f"CREATE OR REPLACE VIEW {name} AS",
            f"SELECT * FROM read_parquet('internal/{name}.parquet')",
            "UNION ALL BY NAME",
            f"SELECT * FROM read_parquet('shareable/{name}.parquet');",
            "",
        ])
    if extra:
        path.write_text(text.rstrip() + "\n\n" + "\n".join(extra) + "\n", encoding="utf-8")


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _utility_id(system_id: object) -> int:
    text = str(system_id)
    prefix = "SYS_EIA_"
    if not text.startswith(prefix) or not text.removeprefix(prefix).isdigit():
        raise ValueError(f"Electric system id is not an EIA id: {system_id}")
    return int(text.removeprefix(prefix))


def _sql_path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
