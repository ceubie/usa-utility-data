"""Generate Gold Derived Data Products by Category, Geography, and Materialized Knowledge Graph."""
import json
from pathlib import Path
import duckdb
import h3
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree
from pipeline.config import (
    GOLD_DIR,
    SILVER_DIR,
    deterministic_id,
)


def build_gold_products() -> dict:
    """Materialize Gold derived products by category, geography, and Knowledge Graph."""
    by_cat_dir = GOLD_DIR / "by_category"
    by_geo_dir = GOLD_DIR / "by_geography"
    kg_dir = GOLD_DIR / "knowledge_graph"
    for d in (by_cat_dir, by_geo_dir, kg_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Load Silver tables
    catalog_df = pd.read_parquet(SILVER_DIR / "source_inventory.parquet")
    states_df = pd.read_parquet(SILVER_DIR / "reference_states.parquet")
    counties_df = pd.read_parquet(SILVER_DIR / "reference_counties.parquet")
    orgs_df = pd.read_parquet(SILVER_DIR / "canonical_organizations.parquet")
    systems_df = pd.read_parquet(SILVER_DIR / "canonical_systems.parquet")
    all_bnd_df = pd.read_parquet(SILVER_DIR / "service_boundaries_normalized.parquet")
    best_bnd_df = pd.read_parquet(SILVER_DIR / "service_boundaries_best_available.parquet")
    dedup_fac_df = pd.read_parquet(SILVER_DIR / "facilities_deduplicated.parquet")
    networks_df = pd.read_parquet(SILVER_DIR / "linear_and_node_networks_summary.parquet")
    cnty_assoc_df = pd.read_parquet(SILVER_DIR / "county_utility_associations.parquet")

    # =========================================================================
    # 1. DERIVED PRODUCTS BY CATEGORY (gold/by_category/)
    # =========================================================================
    sector_groups = {
        "electric": ["electric"],
        "natural_gas": ["natural_gas"],
        "water": ["water"],
        "wastewater": ["wastewater"],
        "stormwater_and_multi": ["stormwater", "multi_utility", "telecommunications", "petroleum_liquids"],
    }
    for label, secs in sector_groups.items():
        sub = best_bnd_df[best_bnd_df["sector"].isin(secs)].reset_index(drop=True)
        sub.to_parquet(by_cat_dir / f"{label}_service_territories_best.parquet", index=False)

    # Facility products by category
    elec_fac = dedup_fac_df[dedup_fac_df["sector"] == "electric"].reset_index(drop=True)
    elec_fac.to_parquet(by_cat_dir / "electric_generation_and_substations_dedup.parquet", index=False)

    water_ww_fac = dedup_fac_df[dedup_fac_df["sector"].isin(["water", "wastewater", "stormwater"])].reset_index(drop=True)
    water_ww_fac.to_parquet(by_cat_dir / "water_and_wastewater_facilities_dedup.parquet", index=False)

    networks_df.to_parquet(by_cat_dir / "linear_and_node_infrastructure_inventory.parquet", index=False)
    print(f"Category derived products written to {by_cat_dir}", flush=True)

    # =========================================================================
    # 2. DERIVED PRODUCTS BY GEOGRAPHY (gold/by_geography/)
    # =========================================================================
    # 2A. Spatial Join of Best-Available Service Boundaries against 3,235 US Census Counties
    cgeoms = shapely.from_wkb(counties_df["geometry_wkb"].values)
    bgeoms = shapely.from_wkb(best_bnd_df["geometry_wkb"].values)
    tree = STRtree(cgeoms)
    pairs = tree.query(bgeoms, predicate="intersects")  #pairs[0]=bnd_idx, pairs[1]=county_idx

    bnd_idx_arr = pairs[0]
    cnty_idx_arr = pairs[1]

    spatial_cnty_rows = []
    bnd_records = best_bnd_df[
        ["boundary_id", "source_id", "sector", "system_id", "org_id", "provider_name", "zone_role", "authority_tier", "area_sqkm"]
    ].to_dict("records")
    cnty_records = counties_df[["county_fips", "state_code", "county_name"]].to_dict("records")

    for b_i, c_i in zip(bnd_idx_arr, cnty_idx_arr):
        b = bnd_records[b_i]
        c = cnty_records[c_i]
        spatial_cnty_rows.append({
            "county_fips": c["county_fips"],
            "state_code": c["state_code"],
            "county_name": c["county_name"],
            "sector": b["sector"],
            "system_id": b["system_id"],
            "org_id": b["org_id"],
            "provider_name": b["provider_name"],
            "zone_role": b["zone_role"],
            "authority_tier": int(b["authority_tier"]),
            "evidence_type": "spatial_polygon_intersection",
            "source_id": b["source_id"],
            "boundary_id": b["boundary_id"],
        })

    # Combine spatial polygon intersections with tabular county lookups (EIA-861, SDWA, CWNS, FL PSC, MO PSC)
    tabular_cnty_rows = []
    for row in cnty_assoc_df.dropna(subset=["county_fips"]).itertuples(index=False):
        tabular_cnty_rows.append({
            "county_fips": str(row.county_fips).zfill(5),
            "state_code": row.state_code,
            "county_name": row.county_name,
            "sector": row.sector,
            "system_id": row.system_id,
            "org_id": row.org_id,
            "provider_name": row.raw_provider_name,
            "zone_role": "administrative_unit_proxy",
            "authority_tier": int(row.authority_tier),
            "evidence_type": row.association_method,
            "source_id": row.source_id,
            "boundary_id": None,
        })

    combined_cnty_df = pd.concat(
        [pd.DataFrame(spatial_cnty_rows), pd.DataFrame(tabular_cnty_rows)],
        ignore_index=True,
    )
    # Sort so highest authority tier (lowest number) wins per (county_fips, sector, system_id)
    combined_cnty_df = (
        combined_cnty_df.sort_values("authority_tier", ascending=True)
        .drop_duplicates(subset=["county_fips", "sector", "system_id"], keep="first")
        .reset_index(drop=True)
    )
    combined_cnty_df.to_parquet(by_geo_dir / "county_utility_service_matrix.parquet", index=False)

    # 2B. County Summary Rollup across all 3,235 US Counties
    cnty_pivot = (
        combined_cnty_df.groupby(["county_fips", "sector"])
        .agg(
            provider_count=("system_id", "nunique"),
            best_authority_tier=("authority_tier", "min"),
            has_gis_polygon=("boundary_id", lambda s: int(s.notna().any())),
        )
        .unstack(fill_value=0)
    )
    cnty_pivot.columns = [f"{sec}_{metric}" for metric, sec in cnty_pivot.columns]
    county_summary_df = (
        counties_df.drop(columns=["geometry_wkb", "county_name_norm"])
        .merge(cnty_pivot.reset_index(), on="county_fips", how="left")
    )
    for col in cnty_pivot.columns:
        if col.endswith("_has_gis_polygon"):
            county_summary_df[col] = county_summary_df[col].fillna(0).astype(bool)
        else:
            county_summary_df[col] = county_summary_df[col].fillna(0).astype(int)
    county_summary_df.to_parquet(by_geo_dir / "county_multi_utility_summary.parquet", index=False)

    # 2C. State x Sector Coverage & Freshness Scorecard
    bnd_state_stats = (
        best_bnd_df.groupby(["state_code", "sector"])
        .agg(
            deduplicated_zones=("boundary_id", "count"),
            unique_systems_with_polygons=("system_id", "nunique"),
            best_polygon_authority_tier=("authority_tier", "min"),
            total_zone_area_sqkm=("area_sqkm", "sum"),
        )
        .reset_index()
    )
    fac_state_stats = (
        dedup_fac_df.groupby(["state_code", "sector"])
        .agg(unique_facilities=("canonical_facility_id", "nunique"))
        .reset_index()
    )
    cnty_state_stats = (
        combined_cnty_df.groupby(["state_code", "sector"])
        .agg(
            counties_covered=("county_fips", "nunique"),
            unique_systems_total=("system_id", "nunique"),
            best_overall_authority_tier=("authority_tier", "min"),
        )
        .reset_index()
    )
    total_counties_per_state = counties_df.groupby("state_code")["county_fips"].nunique().rename("total_state_counties").reset_index()

    scorecard_df = (
        cnty_state_stats.merge(bnd_state_stats, on=["state_code", "sector"], how="outer")
        .merge(fac_state_stats, on=["state_code", "sector"], how="outer")
        .merge(total_counties_per_state, on="state_code", how="left")
    )
    scorecard_df["deduplicated_zones"] = scorecard_df["deduplicated_zones"].fillna(0).astype(int)
    scorecard_df["unique_systems_with_polygons"] = scorecard_df["unique_systems_with_polygons"].fillna(0).astype(int)
    scorecard_df["unique_facilities"] = scorecard_df["unique_facilities"].fillna(0).astype(int)
    scorecard_df["counties_covered"] = scorecard_df["counties_covered"].fillna(0).astype(int)
    scorecard_df["county_coverage_pct"] = np.where(
        scorecard_df["total_state_counties"] > 0,
        (scorecard_df["counties_covered"] / scorecard_df["total_state_counties"] * 100.0).round(1),
        0.0,
    )
    scorecard_df = scorecard_df.sort_values(["state_code", "sector"]).reset_index(drop=True)
    scorecard_df.to_parquet(by_geo_dir / "state_sector_coverage_scorecard.parquet", index=False)

    # 2D. H3 Spatial Index (Resolution 6 ~36 sqkm and Resolution 7 ~5.16 sqkm)
    h3_rows = []
    # Index all Best-Available Service Boundaries by representative point + vertex sample
    for row in best_bnd_df.itertuples(index=False):
        if pd.notna(row.repr_lat) and pd.notna(row.repr_lon):
            lat, lon = float(row.repr_lat), float(row.repr_lon)
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                h3_rows.append({
                    "h3_r6": h3.latlng_to_cell(lat, lon, 6),
                    "h3_r7": h3.latlng_to_cell(lat, lon, 7),
                    "entity_type": "service_zone",
                    "entity_id": row.boundary_id,
                    "system_id": row.system_id,
                    "org_id": row.org_id,
                    "sector": row.sector,
                    "state_code": row.state_code,
                    "name": row.provider_name,
                    "authority_tier": int(row.authority_tier),
                    "source_id": row.source_id,
                })

    # Index all Deduplicated Physical Facilities
    for row in dedup_fac_df.itertuples(index=False):
        if pd.notna(row.lat) and pd.notna(row.lon):
            lat, lon = float(row.lat), float(row.lon)
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                h3_rows.append({
                    "h3_r6": h3.latlng_to_cell(lat, lon, 6),
                    "h3_r7": h3.latlng_to_cell(lat, lon, 7),
                    "entity_type": "facility",
                    "entity_id": row.canonical_facility_id,
                    "system_id": None,
                    "org_id": None,
                    "sector": row.sector,
                    "state_code": row.state_code,
                    "name": row.facility_name,
                    "authority_tier": int(row.authority_tier),
                    "source_id": row.source_id,
                })

    h3_index_df = pd.DataFrame(h3_rows)
    h3_index_df.to_parquet(by_geo_dir / "h3_spatial_index.parquet", index=False)
    print(f"Geographic derived products written to {by_geo_dir}", flush=True)

    # =========================================================================
    # 3. MATERIALIZED KNOWLEDGE GRAPH (gold/knowledge_graph/)
    # =========================================================================
    # Build unified Nodes table & specialized node tables
    nodes_orgs = pd.DataFrame({
        "node_id": orgs_df["org_id"],
        "node_label": "UtilityOrganization",
        "name": orgs_df["canonical_name"],
        "sector": orgs_df["primary_sector"],
        "state_code": orgs_df["state_code"],
        "subtype_or_role": orgs_df["ownership_type"],
        "authority_tier": 3,
        "external_id": orgs_df["eia_utility_id"].fillna(orgs_df["pwsid"]).fillna(orgs_df["cwns_id"]).fillna(orgs_df["phmsa_operator_id"]),
        "lon": np.nan,
        "lat": np.nan,
        "source_id": orgs_df["source_id"],
    })

    nodes_systems = pd.DataFrame({
        "node_id": systems_df["system_id"],
        "node_label": "UtilitySystem",
        "name": systems_df["system_name"],
        "sector": systems_df["sector"],
        "state_code": systems_df["state_code"],
        "subtype_or_role": systems_df["ownership_type"],
        "authority_tier": 3,
        "external_id": systems_df["pwsid"].fillna(systems_df["eia_utility_id"]).fillna(systems_df["cwns_id"]).fillna(systems_df["phmsa_operator_id"]),
        "lon": np.nan,
        "lat": np.nan,
        "source_id": systems_df["source_id"],
    })

    nodes_zones = pd.DataFrame({
        "node_id": best_bnd_df["boundary_id"],
        "node_label": "ServiceZone",
        "name": best_bnd_df["provider_name"],
        "sector": best_bnd_df["sector"],
        "state_code": best_bnd_df["state_code"],
        "subtype_or_role": best_bnd_df["zone_role"],
        "authority_tier": best_bnd_df["authority_tier"],
        "external_id": best_bnd_df["pwsid"].fillna(best_bnd_df["eia_utility_id"]).fillna(best_bnd_df["cwns_id"]).fillna(best_bnd_df["native_id"]),
        "lon": best_bnd_df["repr_lon"],
        "lat": best_bnd_df["repr_lat"],
        "source_id": best_bnd_df["source_id"],
    })

    nodes_facilities = pd.DataFrame({
        "node_id": dedup_fac_df["canonical_facility_id"],
        "node_label": "InfrastructureAsset",
        "name": dedup_fac_df["facility_name"],
        "sector": dedup_fac_df["sector"],
        "state_code": dedup_fac_df["state_code"],
        "subtype_or_role": dedup_fac_df["facility_subtype"],
        "authority_tier": dedup_fac_df["authority_tier"],
        "external_id": dedup_fac_df["eia_plant_code"].fillna(dedup_fac_df["cwns_id"]).fillna(dedup_fac_df["npdes_id"]).fillna(dedup_fac_df["ferc_project_num"]),
        "lon": dedup_fac_df["lon"],
        "lat": dedup_fac_df["lat"],
        "source_id": dedup_fac_df["source_id"],
    })

    nodes_counties = pd.DataFrame({
        "node_id": "GEO_COUNTY_" + counties_df["county_fips"],
        "node_label": "GeoUnit_County",
        "name": counties_df["county_namelsad"] + ", " + counties_df["state_code"],
        "sector": "reference",
        "state_code": counties_df["state_code"],
        "subtype_or_role": "US_Census_County_2025",
        "authority_tier": 1,
        "external_id": counties_df["county_fips"],
        "lon": counties_df["repr_lon"],
        "lat": counties_df["repr_lat"],
        "source_id": "reference_census_2025_counties",
    })

    nodes_states = pd.DataFrame({
        "node_id": "GEO_STATE_" + states_df["state_code"],
        "node_label": "GeoUnit_State",
        "name": states_df["state_name"],
        "sector": "reference",
        "state_code": states_df["state_code"],
        "subtype_or_role": "US_Census_State_2025",
        "authority_tier": 1,
        "external_id": states_df["state_fips"],
        "lon": states_df["repr_lon"],
        "lat": states_df["repr_lat"],
        "source_id": "reference_census_2025_states",
    })

    kg_nodes_df = pd.concat(
        [nodes_orgs, nodes_systems, nodes_zones, nodes_facilities, nodes_counties, nodes_states],
        ignore_index=True,
    ).drop_duplicates(subset=["node_id"]).reset_index(drop=True)

    # Build Knowledge Graph Edges
    # Edge 1: UtilityOrganization --[OPERATES_SYSTEM]--> UtilitySystem
    edges_org_sys = pd.DataFrame({
        "edge_id": "E_OPS_" + systems_df["system_id"],
        "src_node_id": systems_df["org_id"],
        "dst_node_id": systems_df["system_id"],
        "edge_type": "OPERATES_SYSTEM",
        "sector": systems_df["sector"],
        "authority_tier": 3,
        "confidence": 1.0,
        "evidence_source": systems_df["source_id"],
    })

    # Edge 2: UtilitySystem --[HAS_SERVICE_ZONE]--> ServiceZone (Best-Available)
    edges_sys_zone = pd.DataFrame({
        "edge_id": "E_ZONE_" + best_bnd_df["boundary_id"],
        "src_node_id": best_bnd_df["system_id"],
        "dst_node_id": best_bnd_df["boundary_id"],
        "edge_type": "HAS_SERVICE_ZONE",
        "sector": best_bnd_df["sector"],
        "authority_tier": best_bnd_df["authority_tier"],
        "confidence": best_bnd_df["entity_match_confidence"],
        "evidence_source": best_bnd_df["source_id"],
    })

    # Edge 3: UtilitySystem --[SERVES_COUNTY]--> GeoUnit_County
    edges_sys_cnty = pd.DataFrame({
        "edge_id": [
            deterministic_id("E_CNTY", r.system_id, r.county_fips, r.sector)
            for r in combined_cnty_df.itertuples(index=False)
        ],
        "src_node_id": combined_cnty_df["system_id"],
        "dst_node_id": "GEO_COUNTY_" + combined_cnty_df["county_fips"],
        "edge_type": "SERVES_COUNTY",
        "sector": combined_cnty_df["sector"],
        "authority_tier": combined_cnty_df["authority_tier"],
        "confidence": np.where(combined_cnty_df["evidence_type"] == "spatial_polygon_intersection", 0.95, 0.80),
        "evidence_source": combined_cnty_df["source_id"],
    })

    # Edge 4: GeoUnit_County --[IN_STATE]--> GeoUnit_State
    edges_cnty_state = pd.DataFrame({
        "edge_id": "E_IN_STATE_" + counties_df["county_fips"],
        "src_node_id": "GEO_COUNTY_" + counties_df["county_fips"],
        "dst_node_id": "GEO_STATE_" + counties_df["state_code"],
        "edge_type": "IN_STATE",
        "sector": "reference",
        "authority_tier": 1,
        "confidence": 1.0,
        "evidence_source": "reference_census_2025_counties",
    })

    # Edge 5: UtilityOrganization / UtilitySystem --[OWNS_OR_OPERATES_ASSET]--> InfrastructureAsset
    fac_linked = dedup_fac_df[dedup_fac_df["eia_utility_id"].notna() | dedup_fac_df["cwns_id"].notna()].copy()
    fac_src_nodes = np.where(
        fac_linked["eia_utility_id"].notna(),
        "ORG_EIA_" + fac_linked["eia_utility_id"].astype(str),
        "SYS_CWNS_" + fac_linked["cwns_id"].astype(str),
    )
    edges_fac = pd.DataFrame({
        "edge_id": "E_ASSET_" + fac_linked["canonical_facility_id"],
        "src_node_id": fac_src_nodes,
        "dst_node_id": fac_linked["canonical_facility_id"],
        "edge_type": "OWNS_OR_OPERATES_ASSET",
        "sector": fac_linked["sector"],
        "authority_tier": fac_linked["authority_tier"],
        "confidence": 1.0,
        "evidence_source": fac_linked["source_id"],
    })

    kg_edges_df = pd.concat(
        [edges_org_sys, edges_sys_zone, edges_sys_cnty, edges_cnty_state, edges_fac],
        ignore_index=True,
    ).drop_duplicates(subset=["edge_id"]).reset_index(drop=True)

    kg_nodes_df.to_parquet(kg_dir / "kg_nodes.parquet", index=False)
    kg_edges_df.to_parquet(kg_dir / "kg_edges.parquet", index=False)

    # Also build an embedded DuckDB database at gold/knowledge_graph/utility_knowledge_graph.duckdb
    db_path = kg_dir / "utility_knowledge_graph.duckdb"
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute(f"CREATE VIEW kg_nodes AS SELECT * FROM read_parquet('{(kg_dir / 'kg_nodes.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW kg_edges AS SELECT * FROM read_parquet('{(kg_dir / 'kg_edges.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW county_utility_service_matrix AS SELECT * FROM read_parquet('{(by_geo_dir / 'county_utility_service_matrix.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW county_multi_utility_summary AS SELECT * FROM read_parquet('{(by_geo_dir / 'county_multi_utility_summary.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW state_sector_coverage_scorecard AS SELECT * FROM read_parquet('{(by_geo_dir / 'state_sector_coverage_scorecard.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW h3_spatial_index AS SELECT * FROM read_parquet('{(by_geo_dir / 'h3_spatial_index.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW canonical_organizations AS SELECT * FROM read_parquet('{(SILVER_DIR / 'canonical_organizations.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW canonical_systems AS SELECT * FROM read_parquet('{(SILVER_DIR / 'canonical_systems.parquet').as_posix()}');")
    con.execute(f"CREATE VIEW facilities_deduplicated AS SELECT * FROM read_parquet('{(SILVER_DIR / 'facilities_deduplicated.parquet').as_posix()}');")
    con.close()

    summary = {
        "catalog_sources_total": int(len(catalog_df)),
        "catalog_pruned_duplicate_sources": int(catalog_df["is_pruned_duplicate"].sum()),
        "canonical_organizations": int(len(orgs_df)),
        "canonical_systems": int(len(systems_df)),
        "service_boundaries_normalized_total": int(len(all_bnd_df)),
        "service_boundaries_best_available": int(len(best_bnd_df)),
        "facilities_deduplicated": int(len(dedup_fac_df)),
        "network_groups": int(len(networks_df)),
        "county_utility_service_links": int(len(combined_cnty_df)),
        "h3_indexed_locations": int(len(h3_index_df)),
        "kg_nodes_total": int(len(kg_nodes_df)),
        "kg_edges_total": int(len(kg_edges_df)),
        "kg_nodes_by_label": kg_nodes_df["node_label"].value_counts().to_dict(),
        "kg_edges_by_type": kg_edges_df["edge_type"].value_counts().to_dict(),
    }
    (GOLD_DIR / "build_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Gold Materialized Knowledge Graph & Derived Products Complete:", json.dumps(summary, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    build_gold_products()
