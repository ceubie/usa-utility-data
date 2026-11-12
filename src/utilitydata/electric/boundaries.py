"""Electric boundary assertions from reviewed layers and EIA-861 counties.

Draft and empty-geometry sources are not read. County rows that cannot be
joined to the Census county file are rejected and counted.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from utilitydata.core.config import EIA_NONUTILITY_IDS
from utilitydata.core.geometry import union_geometries
from utilitydata.core.text import normalize_name
from utilitydata.registry import Layer, Source
from utilitydata.sectors.areas import read_source_features
from utilitydata.silver.boundaries import (
    BUILDABLE,
    REJECT_COLUMNS,
    _feature_id,
    _known_states,
    _load_state_regions,
    build_layer_rows,
)
from utilitydata.silver.geometry import (
    DESTINATION,
    prepare_geometries,
    read_vector_features,
)

BOUNDARY_AUTHORITIES = frozenset({"utility_direct", "state_regulator", "federal_modeled"})
ASSERTION_COLUMNS = (
    "assertion_id",
    "source_id",
    "source_layer",
    "source_feature_id",
    "sector",
    "zone_role",
    "authority",
    "raw_name",
    "name_norm",
    "declared_state",
    "geom_state",
    "source_vintage_date",
    "licence",
    "area_km2",
    "geometry_hash",
    "grain",
    "boundary_representation",
    "needs_review",
    "review_reason",
    "state_mismatch",
    "eia_utility_id",
    "geometry",
)


def select_electric_layers(sources: list[Source]) -> tuple[list[tuple[Source, Layer]], list[str]]:
    """Return reviewed electric service areas and the draft sources left unread."""
    jobs: list[tuple[Source, Layer]] = []
    drafts: list[str] = []
    for source in sources:
        layers = [layer for layer in source.layers if layer.sector == "electric" and layer.grain == "service_area"]
        if not layers:
            continue
        if not source.reviewed:
            drafts.append(source.source_id)
            continue
        for layer in layers:
            if not isinstance(layer.authority, str) or layer.authority not in BOUNDARY_AUTHORITIES:
                raise ValueError(f"{source.source_id} has an electric service area without a usable authority")
            jobs.append((source, layer))
    return jobs, sorted(drafts)


def parse_eia_id(value: object) -> int | None:
    """Return an integer EIA utility id when the text is all digits."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip()
    text = text.removesuffix(".0")
    if not text.isdigit():
        return None
    return int(text)


def build_boundary_assertions(
    home: Path,
    sources: list[Source],
    *,
    quarter: str,
    territory: pd.DataFrame,
    names: pd.Series,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, dict[str, object], list[object], list[str], dict[int, set[str]]]:
    """Build reviewed polygons and the county-union footprint. Layer rejects are returned with their reasons."""
    jobs, drafts = select_electric_layers(sources)
    snapshot = home / "snapshots" / quarter
    layers = pd.read_parquet(snapshot / "layers.parquet")
    _refuse_unbuildable(jobs, layers)
    known_states = _known_states(home / "silver" / quarter / "ref_state.parquet")
    state_geometries, state_codes = _load_state_regions(home, sources, home / "silver" / quarter / "ref_state.parquet")
    frames: list[pd.DataFrame] = []
    geometries: list[object] = []
    layer_rejects: list[dict] = []
    layer_reports: list[dict[str, object]] = []
    for source, layer in jobs:
        attributes, geoms, crs = read_source_features(home, quarter, source, layer)
        rows = build_layer_rows(
            source_id=source.source_id,
            licence=source.licence,
            layer=layer,
            attributes=attributes,
            geometries=geoms,
            source_crs=crs,
            sdwis_counts={},
            known_states=known_states,
            state_geometries=state_geometries,
            state_codes=state_codes,
            spatial=True,
        )
        if len(rows.assertions) + len(rows.rejects) != len(attributes):
            raise ValueError(f"{source.source_id} feature count does not reconcile")
        layer_rejects.extend(rows.rejects)
        eia_field = layer.id_fields.get("eia_utility_id")
        eia_by_feature = {
            _feature_id(record, layer, index): parse_eia_id(record.get(eia_field) if eia_field else None)
            for index, record in enumerate(attributes)
        }
        built = pd.DataFrame(rows.assertions)
        if not built.empty:
            built["eia_utility_id"] = built["source_feature_id"].map(eia_by_feature)
            frames.append(built)
            geometries.extend(rows.geometries)
        layer_reports.append({
            "source_id": source.source_id,
            "authority": layer.authority,
            "features": len(attributes),
            "assertions": len(rows.assertions),
            "rejects": len(rows.rejects),
        })
    county_geometries, county_index, state_by_county = load_counties(home, sources)
    county_frame, county_geoms, county_rejects, county_report, reported = county_unions(
        territory,
        names,
        county_geometries,
        county_index,
        state_by_county,
        sources,
        known_states,
        home / "silver" / quarter / "ref_county_alias.parquet",
        home / "silver" / quarter / "ref_state.parquet",
    )
    if not county_frame.empty:
        frames.append(county_frame)
        geometries.extend(county_geoms)
    if not frames:
        raise ValueError("Electric boundary build produced no assertions")
    assertions = pd.concat(frames, ignore_index=True)
    if len(assertions) != len(geometries):
        raise ValueError("Electric assertions and geometries diverged")
    assertions["geometry"] = geometries
    geo = gpd.GeoDataFrame(assertions, geometry="geometry", crs="EPSG:4326")
    report = {"layers": layer_reports, "drafts_not_read": drafts, "counties": county_report}
    boundary_rejects = pd.DataFrame(layer_rejects, columns=REJECT_COLUMNS)
    return geo, boundary_rejects, county_rejects, report, county_geometries, county_index, reported


def load_counties(home: Path, sources: list[Source]) -> tuple[list[object], list[str], dict[str, str]]:
    """Load Census county polygons in the Silver geometry CRS."""
    matches = [home / source.paths[0] for source in sources if source.storage == "home" for layer in source.layers if layer.layer == "tiger_county"]
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError("The Census county file is not available in the data root")
    frame, geometries, crs = read_vector_features(f"/vsizip/{matches[0].resolve().as_posix()}", None, feature_id_field=None)
    if "GEOID" not in frame.columns:
        raise ValueError("Census county file is missing GEOID")
    prepared, _hashes, _areas, keep = prepare_geometries(geometries, crs)
    kept = frame.iloc[np.flatnonzero(np.asarray(keep, dtype=bool))].reset_index(drop=True)
    prepared = prepared[np.asarray(keep, dtype=bool)]
    geoids = kept["GEOID"].astype(str).str.zfill(5).tolist()
    if len(geoids) != len(set(geoids)):
        raise ValueError("Census county GEOIDs are not unique")
    states = {geoid: geoid[:2] for geoid in geoids}
    return list(prepared), geoids, states


def county_unions(
    territory: pd.DataFrame,
    names: pd.Series,
    county_geometries: list[object],
    county_index: list[str],
    state_by_county: dict[str, str],
    sources: list[Source],
    known_states: set[str],
    alias_path: Path,
    state_path: Path,
) -> tuple[pd.DataFrame, list[object], pd.DataFrame, dict[str, int], dict[int, set[str]]]:
    """Union each utility's latest EIA-861 counties into one admin-proxy footprint."""
    source = _territory_source(sources)
    latest = territory["report_date"].max()
    current = territory.loc[territory["report_date"] == latest].copy()
    alias = _alias_map(alias_path)
    ambiguous = _ambiguous_aliases(alias_path)
    state_fips = _state_fips(state_path)
    geometry_by_geoid = dict(zip(county_index, county_geometries, strict=True))
    rejects: list[dict[str, object]] = []
    accepted: list[tuple[int, str, object]] = []
    for record in current.itertuples(index=False):
        utility_id = int(record.utility_id_eia) if pd.notna(record.utility_id_eia) else None
        raw_name = None if utility_id is None else names.get(utility_id)
        if utility_id is None:
            rejects.append(_county_reject(utility_id, record.state, "missing_utility_id", raw_name))
            continue
        if utility_id in EIA_NONUTILITY_IDS:
            rejects.append(_county_reject(utility_id, record.state, "nonutility_respondent", raw_name))
            continue
        if utility_id not in set(names.index):
            rejects.append(_county_reject(utility_id, record.state, "unknown_utility", raw_name))
            continue
        fips = parse_eia_id(record.county_id_fips)
        text = None if fips is None else str(fips).zfill(5)
        if text is None:
            text = _fips_text(record.county_id_fips)
        if text is None:
            rejects.append(_county_reject(utility_id, record.state, "missing_county_fips", raw_name))
            continue
        if text in ambiguous:
            rejects.append(_county_reject(utility_id, record.state, "ambiguous_county_crosswalk", raw_name))
            continue
        geoid = text if text in geometry_by_geoid else alias.get(text)
        if geoid is None or geoid not in geometry_by_geoid:
            rejects.append(_county_reject(utility_id, record.state, "county_not_in_reference", raw_name))
            continue
        filing_state = None if pd.isna(record.state) else str(record.state).strip().upper()
        if filing_state not in known_states or state_fips.get(filing_state) != state_by_county[geoid]:
            rejects.append(_county_reject(utility_id, record.state, "county_state_disagrees", raw_name))
            continue
        accepted.append((utility_id, geoid, geometry_by_geoid[geoid]))
    grouped: dict[int, list[object]] = {}
    reported: dict[int, set[str]] = {}
    for utility_id, geoid, geometry in accepted:
        grouped.setdefault(utility_id, []).append(geometry)
        reported.setdefault(utility_id, set()).add(geoid)
    rows: list[dict[str, object]] = []
    output_geometries: list[object] = []
    prepared_input = []
    utility_order = []
    for utility_id, parts in grouped.items():
        prepared_input.append(union_geometries(parts))
        utility_order.append(utility_id)
    if prepared_input:
        prepared, hashes, areas, keep = prepare_geometries(np.array(prepared_input, dtype=object), DESTINATION)
        for utility_id, geometry, digest, area, kept in zip(utility_order, prepared, hashes, areas, keep, strict=True):
            if not bool(kept) or geometry is None:
                raise ValueError(f"County union for EIA utility {utility_id} is empty")
            rows.append({
                "assertion_id": f"{source.source_id}|core_eia861__yearly_service_territory.parquet|{utility_id}",
                "source_id": source.source_id,
                "source_layer": "core_eia861__yearly_service_territory.parquet",
                "source_feature_id": str(utility_id),
                "sector": "electric",
                "zone_role": "active_retail_service",
                "authority": "admin_proxy",
                "raw_name": names.get(utility_id),
                "name_norm": normalize_name(names.get(utility_id)),
                "declared_state": None,
                "geom_state": None,
                "source_vintage_date": pd.Timestamp(latest).date(),
                "licence": source.licence,
                "area_km2": area,
                "geometry_hash": digest,
                "grain": "service_area",
                "boundary_representation": "unknown",
                "needs_review": False,
                "review_reason": None,
                "state_mismatch": False,
                "eia_utility_id": utility_id,
            })
            output_geometries.append(geometry)
    report = {
        "input_rows": len(territory),
        "latest_rows": len(current),
        "accepted_county_rows": len(accepted),
        "reject_rows": len(rejects),
        "utilities": len(rows),
        "report_date": str(pd.Timestamp(latest).date()),
    }
    if report["latest_rows"] != report["accepted_county_rows"] + report["reject_rows"]:
        raise ValueError("EIA-861 county rows do not reconcile")
    frame = pd.DataFrame(rows)
    columns = ["table_name", "utility_id_eia", "state", "reason", "raw_name"]
    reject_frame = pd.DataFrame(rejects, columns=columns)
    return frame, output_geometries, reject_frame, report, reported


def _territory_source(sources: list[Source]) -> Source:
    found = [source for source in sources if any(layer.layer == "core_eia861__yearly_service_territory.parquet" for layer in source.layers)]
    if len(found) != 1 or not found[0].reviewed:
        raise ValueError("The EIA-861 service territory table is not a reviewed source")
    return found[0]


def _refuse_unbuildable(jobs: list[tuple[Source, Layer]], layers: pd.DataFrame) -> None:
    for source, layer in jobs:
        match = layers[(layers["source_id"] == source.source_id) & (layers["layer"] == layer.layer)]
        if len(match) != 1:
            raise ValueError(f"Snapshot layer row missing for {source.source_id} {layer.layer}")
        status = str(match.iloc[0]["status"])
        if status not in BUILDABLE:
            raise ValueError(f"{source.source_id} {layer.layer} has status {status}")


def _alias_map(path: Path) -> dict[str, str]:
    frame = pd.read_parquet(path, columns=["old_county_geoid", "county_geoid"])
    counts = frame.groupby("old_county_geoid")["county_geoid"].nunique()
    unique = frame.loc[frame["old_county_geoid"].map(counts).eq(1)].drop_duplicates("old_county_geoid")
    return {str(old).zfill(5): str(new).zfill(5) for old, new in zip(unique["old_county_geoid"], unique["county_geoid"], strict=True)}


def _ambiguous_aliases(path: Path) -> set[str]:
    frame = pd.read_parquet(path, columns=["old_county_geoid", "county_geoid"])
    counts = frame.groupby("old_county_geoid")["county_geoid"].nunique()
    return {str(value).zfill(5) for value, count in counts.items() if int(count) > 1}


def _state_fips(path: Path) -> dict[str, str]:
    frame = pd.read_parquet(path, columns=["state", "usps"])
    return {str(usps): str(state).zfill(2) for state, usps in zip(frame["state"], frame["usps"], strict=True)}


def _fips_text(value: object) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip()
    text = text.removesuffix(".0")
    if not text.isdigit():
        return None
    return text.zfill(5)


def _county_reject(utility_id: int | None, state: object, reason: str, raw_name: object) -> dict[str, object]:
    return {
        "table_name": "core_eia861__yearly_service_territory",
        "utility_id_eia": utility_id,
        "state": state,
        "reason": reason,
        "raw_name": raw_name,
    }
