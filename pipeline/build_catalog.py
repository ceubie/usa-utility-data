"""Build declarative source catalog and provenance inventory from collection/data."""
import json
from pathlib import Path
import pandas as pd
import yaml
from pipeline.config import (
    CATALOG_DIR,
    RAW_DATA_ROOT,
    SILVER_DIR,
    infer_state_from_source_id,
)

# Source-specific pruning and licence decisions live in the hand-edited registry.
def registry_policy():
    rules = {}
    licences = {}
    registry_dir = Path(__file__).resolve().parents[1] / "registry" / "sources"
    for registry_file in sorted(registry_dir.glob("*.yaml")):
        doc = yaml.safe_load(registry_file.read_text(encoding="utf-8"))
        for source in doc["sources"]:
            source_id = source["source_id"]
            if source.get("superseded_by") and source.get("pruned_reason"):
                rules[source_id] = {"is_pruned_duplicate": True, "superseded_by": source["superseded_by"], "pruned_reason": source["pruned_reason"]}
            if source.get("licence") not in (None, "unknown"):
                licences[source_id] = source["licence"]
    return rules, licences


PRUNE_RULES, LICENSE_OVERRIDES = registry_policy()

def classify_gis_layer(name: str, geom_type: str | None, fields: list[str]) -> dict:
    """Classify an ArcGIS layer by sector, entity category, zone role, and authority tier."""
    low = name.lower()
    state = infer_state_from_source_id(name)

    # 1. Sector classification
    if any(k in low for k in ["broadband", "voice", "telephone"]):
        sector = "telecommunications"
    elif any(k in low for k in ["crude_oil", "petroleum", "refinery", "hydrocarbon_gas_liquids"]):
        sector = "petroleum_liquids"
    elif "electric_gas" in low or "water_sewer" in low or "utility_providers" in low or "conway_utility_service_area" in low:
        sector = "multi_utility"
    elif any(k in low for k in ["storm_", "stormwater", "drainage", "inlet", "pond_connector"]):
        sector = "stormwater"
    elif any(k in low for k in [
        "sewer", "wastewater", "waste_lines", "waste_points", "waste_system",
        "waste_basin", "cso", "combined_sewer", "musa", "laterals", "lateral_cleanouts",
    ]):
        sector = "wastewater"
    elif any(k in low for k in [
        "natural_gas", "_gas_", "gas_service", "gas_territories", "gas_certificated",
        "gas_providers", "gas_transmission", "gas_storage", "gas_distribution",
    ]):
        sector = "natural_gas"
    elif any(k in low for k in [
        "electric", "power_plant", "power_lines", "power_generation", "substation",
        "wind_turbine", "solar", "hydropower", "rggi", "gmp_", "vec_", "wec_",
        "alabama_power", "wapa_",
    ]):
        sector = "electric"
    elif any(k in low for k in ["water", "culinary", "usbr_", "inventory_of_dams"]):
        sector = "water"
    else:
        sector = "multi_utility"

    # 2. Entity category & Zone role
    zone_role = "not_applicable"
    if geom_type == "esriGeometryPolygon":
        if any(k in low for k in ["reservoirs", "power_plant_parcels", "vaults_ponds", "substations"]):
            entity_category = "facility_point"
        elif any(k in low for k in ["survey_township", "electric_providers_massgis", "gas_providers_massgis", "distributed_solar"]):
            entity_category = "county_or_community_association"
            zone_role = "administrative_unit_proxy"
        else:
            entity_category = "service_boundary"
            if any(k in low for k in ["not_serviced"]):
                zone_role = "not_serviced_or_excluded"
            elif any(k in low for k in ["future", "planned", "musa", "long_term", "amendments", "service_plan"]):
                zone_role = "planned_or_future_service"
            elif any(k in low for k in ["watershed", "basin", "pressure_zones", "divisions", "operating_centers"]):
                zone_role = "source_watershed_or_basin"
            elif any(k in low for k in ["certificated", "certified", "exclusive", "cpuc", "rca"]):
                zone_role = "certified_franchise_territory"
            elif any(k in low for k in ["metro_water_recovery", "clean_water_services"]):
                zone_role = "regional_wholesale_or_district"
            else:
                zone_role = "active_retail_service"
    elif geom_type in ("esriGeometryPoint", "esriGeometryMultipoint"):
        if any(k in low for k in ["community_rca", "area_changes"]):
            entity_category = "county_or_community_association"
        elif any(k in low for k in [
            "manholes", "hydrants", "nodes", "inlets", "cleanouts", "poles",
            "underground_structures", "devices", "service_status_points", "waste_points", "diversions",
        ]):
            entity_category = "network_node"
        else:
            entity_category = "facility_point"
    elif geom_type == "esriGeometryPolyline":
        if "boundary_lines" in low:
            entity_category = "service_boundary"
            zone_role = "certified_franchise_territory"
        else:
            entity_category = "network_line"
    else:
        entity_category = "county_or_community_association"

    # 3. Authority tier
    if state is None or low.startswith("national_") or low.endswith("_hifld") or low.endswith("_eia") or low.startswith("usbr_"):
        if "noncommunity_water" in low or "hifld" in low:
            authority_tier = 4
        else:
            authority_tier = 3
    elif any(k in low for k in [
        "maui", "caledonia", "washington_county", "dane_carpc", "sewrpc", "king_county",
        "clean_water_services", "greer", "summerville", "portland", "eugene", "fairfax",
        "conway", "greensboro", "tioga", "metro_water_recovery", "hagerstown",
        "alabama_power", "horry", "gallatin", "laramie", "orange_county", "dc_water",
        "fulton", "broward", "baton_rouge", "collier", "lee_", "pima_", "metc_", "frederick_",
    ]):
        authority_tier = 1
    elif any(k in low for k in ["2004", "1999", "survey_township", "massgis"]):
        authority_tier = 5
    else:
        authority_tier = 2

    prune_info = PRUNE_RULES.get(name, {
        "is_pruned_duplicate": False,
        "superseded_by": None,
        "pruned_reason": None,
    })

    return {
        "source_id": name,
        "source_type": "arcgis_layer",
        "relative_path": f"collection/data/gis/{name}",
        "state": state or "US",
        "sector": sector,
        "entity_category": entity_category,
        "zone_role": zone_role,
        "authority_tier": authority_tier,
        "license_tier": LICENSE_OVERRIDES.get(name, "public_unrestricted"),
        **prune_info,
    }


def build_catalog() -> pd.DataFrame:
    """Scan collection/data and build the complete catalog of GIS, archive, and registry sources."""
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    entries = []

    # 1. All 270 ArcGIS feature layers in collection/data/gis/
    gis_root = RAW_DATA_ROOT / "gis"
    for folder in sorted(gis_root.iterdir()):
        if not folder.is_dir():
            continue
        snap_path = folder / "snapshot.json"
        meta_path = folder / "layer_metadata.json"
        if not snap_path.exists() or not meta_path.exists():
            continue
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        gtype = meta.get("geometryType")
        fields = [f.get("name", "") for f in (meta.get("fields") or [])]
        sr = (meta.get("extent") or {}).get("spatialReference") or meta.get("spatialReference") or {}
        wkid = sr.get("latestWkid") or sr.get("wkid")
        edit_ts = (meta.get("editingInfo") or {}).get("lastEditDate")

        info = classify_gis_layer(folder.name, gtype, fields)
        info.update({
            "source_url": snap.get("source_layer"),
            "retrieved_utc": snap.get("retrieved_utc"),
            "feature_count": snap.get("downloaded_count", 0),
            "geometry_type": gtype or "Table",
            "native_wkid": int(wkid) if isinstance(wkid, int) else None,
            "source_last_edit_epoch_ms": edit_ts,
            "field_count": len(fields),
        })
        entries.append(info)

    # 2. Federal & State Structured Archives and Registries
    structured_sources = [
        {
            "source_id": "federal_eia861_2025",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/electric/eia861_2025.zip",
            "state": "US",
            "sector": "electric",
            "entity_category": "entity_registry",
            "zone_role": "administrative_unit_proxy",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular/County",
        },
        {
            "source_id": "federal_eia860_2025",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/electric/eia860_2025.zip",
            "state": "US",
            "sector": "electric",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point/Tabular",
        },
        {
            "source_id": "federal_eia860m_sept2026",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/electric/eia860m_september_2026.xlsx",
            "state": "US",
            "sector": "electric",
            "entity_category": "facility_point",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point/Tabular",
        },
        {
            "source_id": "federal_usgs_uswtdb_v9_1",
            "source_type": "national_facility_archive",
            "relative_path": "collection/data/electric/usgs_uswtdb_latest_csv.zip",
            "state": "US",
            "sector": "electric",
            "entity_category": "facility_point",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point",
        },
        {
            "source_id": "federal_usgs_uspvdb_v4_0",
            "source_type": "national_facility_archive",
            "relative_path": "collection/data/electric/usgs_uspvdb_v4_20260414.csv",
            "state": "US",
            "sector": "electric",
            "entity_category": "facility_point",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point/Polygon",
        },
        {
            "source_id": "federal_ferc_cid_2026",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/ferc/official/ferc_company_identifier_listing_20261101.csv",
            "state": "US",
            "sector": "multi_utility",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular",
        },
        {
            "source_id": "federal_eia176_ng_companies",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/gas/eia176_all_ng_data.zip",
            "state": "US",
            "sector": "natural_gas",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular",
        },
        {
            "source_id": "federal_phmsa_gas_distribution_2025",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/gas/phmsa_zenodo_23296837/phmsagas_gas_distribution_2010_present.zip",
            "state": "US",
            "sector": "natural_gas",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular",
        },
        {
            "source_id": "federal_phmsa_gas_transmission_2025",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/gas/phmsa_zenodo_23296837/phmsagas_gas_transmission_gathering_2010_present.zip",
            "state": "US",
            "sector": "natural_gas",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular",
        },
        {
            "source_id": "federal_epa_sdwa_2026q3",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/water/epa_sdwa_latest.zip",
            "state": "US",
            "sector": "water",
            "entity_category": "entity_registry",
            "zone_role": "administrative_unit_proxy",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular/County",
        },
        {
            "source_id": "federal_epa_pws_boundaries_v3",
            "source_type": "national_vector_archive",
            "relative_path": "collection/data/water/epa_pws_boundaries_latest.zip",
            "state": "US",
            "sector": "water",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "federal_usgs_wsa_2017",
            "source_type": "national_vector_archive",
            "relative_path": "collection/data/water/usgs_wsa_2017.zip",
            "state": "US",
            "sector": "water",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 5,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "federal_epa_npdes_icis",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/wastewater/epa_npdes_national.zip",
            "state": "US",
            "sector": "wastewater",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point/Tabular",
        },
        {
            "source_id": "federal_epa_npdes_outfalls",
            "source_type": "national_facility_archive",
            "relative_path": "collection/data/wastewater/epa_npdes_outfalls.zip",
            "state": "US",
            "sector": "wastewater",
            "entity_category": "facility_point",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point",
        },
        {
            "source_id": "federal_epa_cwns_2022",
            "source_type": "national_registry_archive",
            "relative_path": "collection/data/wastewater/epa_cwns_2022_national_sept2026.zip",
            "state": "US",
            "sector": "wastewater",
            "entity_category": "entity_registry",
            "zone_role": "not_applicable",
            "authority_tier": 3,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point/Tabular",
        },
        {
            "source_id": "federal_epa_sewersheds_v1_3",
            "source_type": "national_vector_archive",
            "relative_path": "collection/data/wastewater/epa_sewersheds_v1_3.zip",
            "state": "US",
            "sector": "wastewater",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 4,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_mn_electric_service_areas",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/mn/electric_service_areas.gpkg",
            "state": "MN",
            "sector": "electric",
            "entity_category": "service_boundary",
            "zone_role": "certified_franchise_territory",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_ny_electric_territories",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/ny/electric_territories.geojson",
            "state": "NY",
            "sector": "electric",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_ny_gas_territories",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/ny/gas_territories.geojson",
            "state": "NY",
            "sector": "natural_gas",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_tx_puct_water_ccn",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/tx/puct_water_ccn_tsms.zip",
            "state": "TX",
            "sector": "water",
            "entity_category": "service_boundary",
            "zone_role": "certified_franchise_territory",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_tx_puct_sewer_ccn",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/tx/puct_sewer_ccn_tsms.zip",
            "state": "TX",
            "sector": "wastewater",
            "entity_category": "service_boundary",
            "zone_role": "certified_franchise_territory",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_wi_psc_electric_territories",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/wi/psc_electric_territories.zip",
            "state": "WI",
            "sector": "electric",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_wi_psc_natural_gas_territories",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/wi/psc_natural_gas_territories.zip",
            "state": "WI",
            "sector": "natural_gas",
            "entity_category": "service_boundary",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_wi_psc_water_utilities_2025",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/wi/psc_water_utilities_2025.zip",
            "state": "WI",
            "sector": "water",
            "entity_category": "facility_point",
            "zone_role": "not_applicable",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point",
        },
        {
            "source_id": "state_co_special_districts_all",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/co/special_districts_all_dola.zip",
            "state": "CO",
            "sector": "multi_utility",
            "entity_category": "service_boundary",
            "zone_role": "regional_wholesale_or_district",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "state_co_special_districts_water_sanitation",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/co/special_districts_water_sanitation_dola.zip",
            "state": "CO",
            "sector": "water",
            "entity_category": "service_boundary",
            "zone_role": "regional_wholesale_or_district",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
            "is_pruned_duplicate": True,
            "superseded_by": "state_co_special_districts_all",
            "pruned_reason": "Filtered subset of state_co_special_districts_all (same DOLA lgid values).",
        },
        {
            "source_id": "state_co_special_districts_metro",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/co/special_districts_metro_dola.zip",
            "state": "CO",
            "sector": "multi_utility",
            "entity_category": "service_boundary",
            "zone_role": "regional_wholesale_or_district",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
            "is_pruned_duplicate": True,
            "superseded_by": "state_co_special_districts_all",
            "pruned_reason": "Filtered subset of state_co_special_districts_all (same DOLA lgid values).",
        },
        {
            "source_id": "state_hi_wastewater_treatment_plants",
            "source_type": "state_vector_archive",
            "relative_path": "collection/data/states/hi/wastewater_treatment_plants.zip",
            "state": "HI",
            "sector": "wastewater",
            "entity_category": "facility_point",
            "zone_role": "not_applicable",
            "authority_tier": 2,
            "license_tier": "public_unrestricted",
            "geometry_type": "Point",
        },
        {
            "source_id": "state_fl_psc_county_lookup",
            "source_type": "state_tabular_lookup",
            "relative_path": "collection/data/states/fl/psc_county_lookup/manifest.json",
            "state": "FL",
            "sector": "multi_utility",
            "entity_category": "county_or_community_association",
            "zone_role": "administrative_unit_proxy",
            "authority_tier": 5,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular/County",
        },
        {
            "source_id": "state_mo_psc_utility_lookup",
            "source_type": "state_tabular_lookup",
            "relative_path": "collection/data/states/mo/missouri_utility_lookup_historical.csv",
            "state": "MO",
            "sector": "multi_utility",
            "entity_category": "county_or_community_association",
            "zone_role": "administrative_unit_proxy",
            "authority_tier": 5,
            "license_tier": "public_unrestricted",
            "geometry_type": "Tabular/Community",
        },
        {
            "source_id": "reference_census_2025_counties",
            "source_type": "reference_geography",
            "relative_path": "collection/data/reference/cb_2025_us_county_500k.zip",
            "state": "US",
            "sector": "reference",
            "entity_category": "reference_geography",
            "zone_role": "not_applicable",
            "authority_tier": 1,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
        {
            "source_id": "reference_census_2025_states",
            "source_type": "reference_geography",
            "relative_path": "collection/data/reference/cb_2025_us_state_500k.zip",
            "state": "US",
            "sector": "reference",
            "entity_category": "reference_geography",
            "zone_role": "not_applicable",
            "authority_tier": 1,
            "license_tier": "public_unrestricted",
            "geometry_type": "MultiPolygon",
        },
    ]

    for s in structured_sources:
        s.setdefault("is_pruned_duplicate", False)
        s.setdefault("superseded_by", None)
        s.setdefault("pruned_reason", None)
        s.setdefault("source_url", None)
        s.setdefault("retrieved_utc", "2026-11-09T00:00:00+00:00")
        s.setdefault("feature_count", None)
        s.setdefault("native_wkid", 4326)
        s.setdefault("source_last_edit_epoch_ms", None)
        s.setdefault("field_count", None)
        entries.append(s)

    df = pd.DataFrame(entries)
    catalog_yaml_path = CATALOG_DIR / "sources_catalog.yaml"
    with catalog_yaml_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"version": "2026-Q4", "sources": entries}, f, sort_keys=False)

    df.to_parquet(SILVER_DIR / "source_inventory.parquet", index=False)
    print(f"Catalog built: {len(df)} sources ({df['is_pruned_duplicate'].sum()} pruned duplicates flagged).")
    return df


if __name__ == "__main__":
    build_catalog()
