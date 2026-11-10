"""Entity Resolution, Crosswalk Construction, and Physical Facility Deduplication Engine."""
from collections import defaultdict
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from pipeline.config import (
    SILVER_DIR,
    deterministic_id,
    normalize_entity_name,
)


def resolve_entities_and_deduplicate() -> dict[str, pd.DataFrame]:
    """Resolve all spatial boundaries, county associations, and facilities to canonical UtilityOrg & UtilitySystem nodes."""
    orgs_df = pd.read_parquet(SILVER_DIR / "federal_organizations_spine.parquet")
    sys_df = pd.read_parquet(SILVER_DIR / "federal_systems_spine.parquet")
    cnty_assoc_df = pd.read_parquet(SILVER_DIR / "county_utility_associations.parquet")
    boundaries_df = pd.read_parquet(SILVER_DIR / "service_boundaries_normalized.parquet")
    facilities_df = pd.read_parquet(SILVER_DIR / "facilities_normalized.parquet")

    # -------------------------------------------------------------------------
    # 1. Build Fast Deterministic & Fuzzy Indexes over the Federal Spine
    # -------------------------------------------------------------------------
    pws_to_sys = {}
    eia_to_sys = {}
    cwns_to_sys = {}
    npdes_to_sys = {}
    phmsa_to_sys = {}

    # Blocking index: (sector, state_code) -> list of (system_id, org_id, name_norm, name_core, system_name)
    block_by_sec_state: dict[tuple[str, str], list[tuple[str, str, str, str, str]]] = defaultdict(list)
    exact_name_index: dict[tuple[str, str, str], tuple[str, str]] = {}
    core_name_index: dict[tuple[str, str, str], tuple[str, str]] = {}

    for row in sys_df.itertuples(index=False):
        sid = row.system_id
        oid = row.org_id
        sec = row.sector
        st = row.state_code or "US"
        nnorm = row.name_norm or ""
        ncore = row.name_core or ""
        sname = row.system_name

        if row.pwsid:
            pws_to_sys[str(row.pwsid)] = (sid, oid, sname)
        if row.eia_utility_id:
            eia_to_sys[(str(row.eia_utility_id), st)] = (sid, oid, sname)
            eia_to_sys.setdefault((str(row.eia_utility_id), "US"), (sid, oid, sname))
        if row.cwns_id:
            cwns_to_sys[str(row.cwns_id)] = (sid, oid, sname)
        if row.npdes_id:
            npdes_to_sys[str(row.npdes_id)] = (sid, oid, sname)
        if row.phmsa_operator_id:
            phmsa_to_sys[(str(row.phmsa_operator_id), st)] = (sid, oid, sname)
            phmsa_to_sys.setdefault((str(row.phmsa_operator_id), "US"), (sid, oid, sname))

        if nnorm:
            exact_name_index.setdefault((sec, st, nnorm), (sid, oid))
            exact_name_index.setdefault((sec, "US", nnorm), (sid, oid))
            block_by_sec_state[(sec, st)].append((sid, oid, nnorm, ncore, sname))
        if ncore:
            core_name_index.setdefault((sec, st, ncore), (sid, oid))

    # Cache for fuzzy name matches so each unique (sector, state, name_norm) is evaluated once
    fuzzy_match_cache: dict[tuple[str, str, str], tuple[str, str, str, float]] = {}
    new_orgs = []
    new_systems = []
    seen_new_sys = set()

    def match_or_mint_system(
        sector: str,
        state_code: str,
        raw_name: str,
        name_norm: str,
        name_core: str,
        pwsid: str | None = None,
        eia_id: str | None = None,
        cwns_id: str | None = None,
        npdes_id: str | None = None,
        phmsa_id: str | None = None,
        source_id: str = "state_gis",
    ) -> tuple[str, str, str, float]:
        """Return (system_id, org_id, match_method, match_confidence)."""
        st = state_code or "US"

        # Tier 1: Authoritative Federal ID Match
        if pwsid and str(pwsid) in pws_to_sys:
            sid, oid, _ = pws_to_sys[str(pwsid)]
            return sid, oid, "exact_pwsid", 1.0
        if eia_id:
            hit = eia_to_sys.get((str(eia_id), st)) or eia_to_sys.get((str(eia_id), "US"))
            if hit:
                return hit[0], hit[1], "exact_eia_utility_id", 1.0
        if cwns_id and str(cwns_id) in cwns_to_sys:
            sid, oid, _ = cwns_to_sys[str(cwns_id)]
            return sid, oid, "exact_cwns_id", 1.0
        if npdes_id and str(npdes_id) in npdes_to_sys:
            sid, oid, _ = npdes_to_sys[str(npdes_id)]
            return sid, oid, "exact_npdes_id", 1.0
        if phmsa_id:
            hit = phmsa_to_sys.get((str(phmsa_id), st)) or phmsa_to_sys.get((str(phmsa_id), "US"))
            if hit:
                return hit[0], hit[1], "exact_phmsa_operator_id", 1.0

        # Tier 2: Exact Normalized Name Match within (sector, state) or (sector, US)
        if name_norm:
            hit = exact_name_index.get((sector, st, name_norm)) or exact_name_index.get((sector, "US", name_norm))
            if hit:
                return hit[0], hit[1], "exact_normalized_name", 0.96

        # Tier 3: Exact Core Name Match within (sector, state) (for names >= 4 chars)
        if name_core and len(name_core) >= 4:
            hit = core_name_index.get((sector, st, name_core))
            if hit:
                return hit[0], hit[1], "exact_core_name_state", 0.91

        # Tier 4: RapidFuzz Token-Set / WRatio Blocking within (sector, state)
        cache_key = (sector, st, name_norm or raw_name)
        if cache_key in fuzzy_match_cache:
            return fuzzy_match_cache[cache_key]

        candidates = block_by_sec_state.get((sector, st), [])
        if name_norm and len(name_norm) >= 4 and candidates and len(candidates) <= 2500:
            cand_names = [c[2] for c in candidates]
            best = process.extractOne(name_norm, cand_names, scorer=fuzz.token_sort_ratio, score_cutoff=88.0)
            if best:
                _, score, idx = best
                sid, oid, _, _, _ = candidates[idx]
                res = (sid, oid, "fuzzy_token_sort_state", round(float(score) / 100.0, 3))
                fuzzy_match_cache[cache_key] = res
                return res

        # Tier 5: Mint a canonical State/Local System & Organization node
        clean_key = name_norm or normalize_entity_name(raw_name) or "UNNAMED"
        if pwsid:
            sid = f"SYS_PWS_{pwsid}"
            oid = f"ORG_PWS_{pwsid}"
            method, conf = "minted_from_state_pwsid", 0.95
        elif cwns_id:
            sid = f"SYS_CWNS_{cwns_id}"
            oid = f"ORG_CWNS_{cwns_id}"
            method, conf = "minted_from_cwns_id", 0.95
        else:
            sid = deterministic_id("SYS_LOC", sector, st, clean_key)
            oid = deterministic_id("ORG_LOC", st, clean_key)
            method, conf = "minted_state_local_entity", 0.85

        if sid not in seen_new_sys:
            seen_new_sys.add(sid)
            new_orgs.append({
                "org_id": oid,
                "canonical_name": raw_name,
                "name_norm": clean_key,
                "name_core": name_core,
                "primary_sector": sector,
                "ownership_type": "State/Local Reported",
                "state_code": st,
                "eia_utility_id": eia_id,
                "pwsid": pwsid,
                "npdes_id": npdes_id,
                "cwns_id": cwns_id,
                "phmsa_operator_id": phmsa_id,
                "ferc_cid": None,
                "source_id": source_id,
            })
            new_systems.append({
                "system_id": sid,
                "org_id": oid,
                "system_name": raw_name,
                "name_norm": clean_key,
                "name_core": name_core,
                "sector": sector,
                "state_code": st,
                "ownership_type": "State/Local Reported",
                "activity_status": "Active",
                "population_served": None,
                "service_connections": None,
                "sales_mwh": None,
                "eia_utility_id": eia_id,
                "pwsid": pwsid,
                "npdes_id": npdes_id,
                "cwns_id": cwns_id,
                "phmsa_operator_id": phmsa_id,
                "source_id": source_id,
            })

        res = (sid, oid, method, conf)
        fuzzy_match_cache[cache_key] = res
        return res

    # -------------------------------------------------------------------------
    # 2. Resolve All Normalized Service Boundary Polygons to Canonical Systems
    # -------------------------------------------------------------------------
    bnd_sys_ids = []
    bnd_org_ids = []
    bnd_methods = []
    bnd_confs = []

    for row in boundaries_df.itertuples(index=False):
        sid, oid, m, c = match_or_mint_system(
            sector=row.sector,
            state_code=row.state_code,
            raw_name=row.provider_name,
            name_norm=row.provider_name_norm,
            name_core=row.provider_name_core,
            pwsid=row.pwsid,
            eia_id=row.eia_utility_id,
            cwns_id=row.cwns_id,
            source_id=row.source_id,
        )
        bnd_sys_ids.append(sid)
        bnd_org_ids.append(oid)
        bnd_methods.append(m)
        bnd_confs.append(c)

    boundaries_df["system_id"] = bnd_sys_ids
    boundaries_df["org_id"] = bnd_org_ids
    boundaries_df["entity_match_method"] = bnd_methods
    boundaries_df["entity_match_confidence"] = bnd_confs

    # -------------------------------------------------------------------------
    # 3. Resolve Unlinked County/Community Associations (FL PSC, MO PSC)
    # -------------------------------------------------------------------------
    ca_sys_ids = list(cnty_assoc_df["system_id"])
    ca_org_ids = list(cnty_assoc_df["org_id"])
    for idx, row in enumerate(cnty_assoc_df.itertuples(index=False)):
        if ca_sys_ids[idx] is not None and pd.notna(ca_sys_ids[idx]):
            continue
        ncore = normalize_entity_name(row.raw_provider_name, strip_utility_terms=True)
        sid, oid, _, _ = match_or_mint_system(
            sector=row.sector,
            state_code=row.state_code,
            raw_name=row.raw_provider_name,
            name_norm=row.provider_name_norm,
            name_core=ncore,
            source_id=row.source_id,
        )
        ca_sys_ids[idx] = sid
        ca_org_ids[idx] = oid

    cnty_assoc_df["system_id"] = ca_sys_ids
    cnty_assoc_df["org_id"] = ca_org_ids

    # Combine Federal + Newly Minted State/Local Organizations & Systems
    all_orgs_df = pd.concat([orgs_df, pd.DataFrame(new_orgs)], ignore_index=True).drop_duplicates(subset=["org_id"]).reset_index(drop=True)
    all_sys_df = pd.concat([sys_df, pd.DataFrame(new_systems)], ignore_index=True).drop_duplicates(subset=["system_id"]).reset_index(drop=True)

    # -------------------------------------------------------------------------
    # 4. De-Duplicate Competing Service Boundaries into Best-Available Gold Set
    # -------------------------------------------------------------------------
    # Rank by: authority_tier ASC (1=local GIS, 2=state GIS, 3=federal sourced, 4=federal modeled),
    # then entity_match_confidence DESC, then area_sqkm DESC
    boundaries_sorted = boundaries_df.sort_values(
        by=["authority_tier", "entity_match_confidence", "area_sqkm"],
        ascending=[True, False, False],
    ).reset_index(drop=True)

    best_boundaries_df = boundaries_sorted.drop_duplicates(
        subset=["system_id", "sector", "state_code", "zone_role"],
        keep="first",
    ).copy().reset_index(drop=True)

    # Mark winning vs superseded assertions on the full Silver table
    winning_ids = set(best_boundaries_df["boundary_id"])
    boundaries_df["is_best_available"] = boundaries_df["boundary_id"].isin(winning_ids)

    # -------------------------------------------------------------------------
    # 5. De-Duplicate Physical Facilities Across Federal, USGS, and State Layers
    # -------------------------------------------------------------------------
    # Key priority:
    #   1) eia_plant_code (links EIA-860, EIA Power Plants GIS, USGS USPVDB, USGS USWTDB, MI MPSC, NJ DEP)
    #   2) cwns_id or npdes_id (links CWNS, NPDES, state WWTPs)
    #   3) ferc_project_num (links FERC CSV & GIS layers)
    #   4) nid_id (links USACE NID & MI Hydro Dams)
    #   5) (sector, state_code, facility_name_norm, ~1km rounded coordinate grid)
    npdes_to_cwns_canon = {}
    for row in facilities_df.dropna(subset=["cwns_id", "npdes_id"]).itertuples(index=False):
        npdes_to_cwns_canon[str(row.npdes_id)] = f"CANFAC_CWNS_{row.cwns_id}"

    canon_fac_ids = []
    for row in facilities_df.itertuples(index=False):
        if pd.notna(row.eia_plant_code) and str(row.eia_plant_code).strip():
            cid = f"CANFAC_EIA_{str(row.eia_plant_code).strip()}"
        elif pd.notna(row.cwns_id) and str(row.cwns_id).strip():
            cid = f"CANFAC_CWNS_{str(row.cwns_id).strip()}"
        elif pd.notna(row.npdes_id) and str(row.npdes_id).strip() in npdes_to_cwns_canon:
            cid = npdes_to_cwns_canon[str(row.npdes_id).strip()]
        elif pd.notna(row.npdes_id) and str(row.npdes_id).strip():
            cid = f"CANFAC_NPDES_{str(row.npdes_id).strip()}"
        elif pd.notna(row.ferc_project_num) and str(row.ferc_project_num).strip():
            cid = f"CANFAC_FERC_{str(row.ferc_project_num).strip()}"
        elif pd.notna(row.nid_id) and str(row.nid_id).strip():
            cid = f"CANFAC_NID_{str(row.nid_id).strip()}"
        else:
            lat_grid = f"{round(float(row.lat), 2):.2f}" if pd.notna(row.lat) else "NA"
            lon_grid = f"{round(float(row.lon), 2):.2f}" if pd.notna(row.lon) else "NA"
            cid = deterministic_id("CANFAC_LOC", row.sector, row.state_code, row.facility_name_norm or row.facility_name, lat_grid, lon_grid)
        canon_fac_ids.append(cid)

    facilities_df["canonical_facility_id"] = canon_fac_ids
    # Sort so authoritative / richest records win when deduplicating
    facilities_sorted = facilities_df.sort_values(
        by=["authority_tier", "capacity_mw", "design_flow_mgd"],
        ascending=[True, False, False],
        na_position="last",
    ).reset_index(drop=True)

    source_counts = facilities_sorted.groupby("canonical_facility_id")["source_id"].agg(
        source_assertion_count="count",
        asserted_by_sources=lambda s: "|".join(sorted(set(s))),
    ).reset_index()

    dedup_facilities_df = (
        facilities_sorted.drop_duplicates(subset=["canonical_facility_id"], keep="first")
        .merge(source_counts, on="canonical_facility_id", how="left")
        .reset_index(drop=True)
    )

    # Save updated Silver & resolved tables
    all_orgs_df.to_parquet(SILVER_DIR / "canonical_organizations.parquet", index=False)
    all_sys_df.to_parquet(SILVER_DIR / "canonical_systems.parquet", index=False)
    cnty_assoc_df.to_parquet(SILVER_DIR / "county_utility_associations.parquet", index=False)
    boundaries_df.to_parquet(SILVER_DIR / "service_boundaries_normalized.parquet", index=False)
    best_boundaries_df.to_parquet(SILVER_DIR / "service_boundaries_best_available.parquet", index=False)
    facilities_df.to_parquet(SILVER_DIR / "facilities_normalized.parquet", index=False)
    dedup_facilities_df.to_parquet(SILVER_DIR / "facilities_deduplicated.parquet", index=False)

    print(
        f"Entity Resolution & De-duplication complete:\n"
        f"  - Canonical Organizations: {len(all_orgs_df)}\n"
        f"  - Canonical Systems: {len(all_sys_df)}\n"
        f"  - Service Boundaries: {len(boundaries_df)} total assertions -> {len(best_boundaries_df)} best-available deduplicated zones\n"
        f"  - Facilities: {len(facilities_df)} source records -> {len(dedup_facilities_df)} unique physical facilities"
    )
    return {
        "orgs": all_orgs_df,
        "systems": all_sys_df,
        "boundaries": boundaries_df,
        "best_boundaries": best_boundaries_df,
        "facilities": dedup_facilities_df,
        "county_assoc": cnty_assoc_df,
    }


if __name__ == "__main__":
    resolve_entities_and_deduplicate()
