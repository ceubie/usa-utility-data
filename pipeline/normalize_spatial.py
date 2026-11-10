"""Normalize Service Boundaries (GIS & State/National Vector Archives) and Infrastructure Assets into Silver GeoParquet."""
import gzip
import hashlib
import json
import zipfile
from pathlib import Path
import numpy as np
import orjson
import pandas as pd
import pyogrio
from pyproj import CRS, Transformer
import shapely
from pipeline.config import (
    RAW_DATA_ROOT,
    SILVER_DIR,
    deterministic_id,
    infer_state_from_source_id,
    normalize_county_name,
    normalize_entity_name,
    normalize_pwsid,
    normalize_state_code,
)
from pipeline.normalize_registries import read_ogr_table, wkb_sha256

# Priority order of attribute names for extracting provider / system name from GIS layers
NAME_ATTR_CANDIDATES = [
    "PWS_Name", "PWS_NAME", "PWSName", "pws_name", "WATER_SYSTEM_NAME", "PublicSystemName",
    "SYS_NAME", "SYSTNAME", "SystemName", "WS_Name", "CWS_NAME", "DWNAME", "WSA_NAME",
    "UtilityName", "UTILITY_NAME", "Utility_Name", "UTILITY_NA", "Utility_Na", "UTILITY",
    "Utility", "utilityname", "UTIL_NAME", "UTIL_LAB", "Util_Name", "WASUP_Utility_Name",
    "UTILITY_COMPANY", "COMPANY_NA", "COMPANYNAM", "COMPANY1", "COMPANY", "CompanyName",
    "COMPNAME", "comp_full", "elec_comp", "voice_company", "DBA", "DBA_NAME",
    "ServiceProvider", "PROVIDER", "Provider", "SERVED_BY", "Owner", "OWNER", "OWNER_NAME",
    "Opername", "Operator", "WWUTILITY", "SEWER_NAME", "WATER_NAME", "WATERCO",
    "DRAINAGEDISTRICTS_NAME", "FACILITY_NAME", "FACNAME", "Plant_Name", "PLANT_NAME",
    "PlantName", "TRTMTPLANT", "TreatPlant", "WWTP", "MC_PLANT", "ASSET_NAME", "assetname",
    "NAME", "Name", "name", "LABEL", "LABELTEXT", "OverlapName", "AreaName", "AREA_NAME",
    "District", "DISTRICT", "COOP_AREA", "SERVICE", "WP_Type", "SP_Type", "MUSA_CODE",
]

ID_ATTR_CANDIDATES = [
    "PWSID", "pwsid", "PWS_ID", "pws_id", "PWSId", "SABL_PWSID", "PWID", "PWSSID",
    "Water_System_ID", "WATER_SYSTEM_NUMBER", "DWSYSNUM", "WUDS_ID", "ADEQ_ID", "KDHE_ID",
    "CWNS_ID", "NPDES_ID", "NJPDES", "PERMIT_ID", "PERMIT_NO", "Plant_Code", "PLANT_CODE",
    "Utility_ID", "HIFLD_ID", "EL_CompanyID", "PSC_ID", "Util_ID", "COMPID", "comp_id",
    "CCN_NO", "CPCN", "CPCN_", "SVCTERID", "NIDID", "NID_ID", "PNum", "ID", "Id", "id",
    "OBJECTID", "ObjectId", "objectid", "FID", "fid",
]

# Default provider name when a layer represents a single municipal/regional utility without a provider name column
SINGLE_PROVIDER_DEFAULTS = {
    "florida_lee_water_service_area": "Lee County Utilities",
    "florida_collier_water_service_area": "Collier County Public Utilities",
    "florida_collier_wastewater_service_area": "Collier County Public Utilities",
    "maryland_hagerstown_electric_service_area": "City of Hagerstown Light Department",
    "north_carolina_greensboro_water_sewer_service_area": "City of Greensboro Water Resources",
    "tennessee_gallatin_gas_service_area": "Gallatin Department of Electricity / Public Utilities (Gas)",
    "tennessee_gallatin_sewer_service_area": "Gallatin Public Utilities (Sewer)",
    "tennessee_gallatin_water_service_areas": "Gallatin Public Utilities (Water)",
    "tennessee_gallatin_cumberland_electric_area": "Cumberland Electric Membership Corporation",
    "tennessee_gallatin_nes_electric_area": "Nashville Electric Service",
    "oregon_clean_water_services_district_border": "Clean Water Services",
    "oregon_clean_water_services_pump_station_boundaries": "Clean Water Services",
    "oregon_clean_water_services_treatment_plant_basins": "Clean Water Services",
    "wisconsin_caledonia_water_service_area": "Caledonia Utility District",
    "wisconsin_caledonia_sewer_service_area": "Caledonia Utility District",
    "wisconsin_caledonia_not_serviced_water_district": "Caledonia Utility District (Not Serviced)",
    "wisconsin_caledonia_not_serviced_sewer_district": "Caledonia Utility District (Not Serviced)",
    "wyoming_laramie_gas_certificated_areas": "Cheyenne Light, Fuel and Power (Black Hills Energy)",
    "alabama_power_territory_2023": "Alabama Power Company",
    "alabama_power_divisions_2023": "Alabama Power Company",
    "alabama_power_operating_centers_2023": "Alabama Power Company",
    "dc_water_pressure_zones": "DC Water",
    "hawaii_maui_west_water_service_areas": "County of Maui Department of Water Supply",
    "hawaii_maui_recycled_water_customers": "County of Maui Department of Environmental Management",
    "virginia_state_sewer_area_vdh_deq_2019": "Virginia VDH/DEQ Sewer Service Area",
    "virginia_fairfax_sewer_service_areas": "Fairfax County Wastewater Management",
    "new_york_tioga_water_service_areas": "Tioga County Municipal Water District",
    "new_york_tioga_sewer_service_areas": "Tioga County Municipal Sewer District",
}


def build_esri_coded_domain_map(meta: dict) -> dict[str, dict]:
    """Return {field_name: {code: label}} for all coded-value domains in an Esri layer."""
    domains = {}
    for f in meta.get("fields") or []:
        fname = f.get("name")
        dom = f.get("domain")
        if fname and dom and dom.get("codedValues"):
            cmap = {}
            for cv in dom["codedValues"]:
                code = cv.get("code")
                label = cv.get("name")
                if code is not None and label is not None:
                    cmap[code] = str(label)
                    cmap[str(code)] = str(label)
            domains[fname] = cmap
    return domains


def get_esri_crs(meta: dict) -> CRS:
    """Resolve pyproj CRS from ArcGIS layer_metadata.json."""
    sr = (meta.get("extent") or {}).get("spatialReference") or meta.get("spatialReference") or {}
    wkid = sr.get("latestWkid") or sr.get("wkid")
    if wkid:
        if wkid in (102100, 102113, 3857):
            return CRS.from_epsg(3857)
        try:
            return CRS.from_epsg(int(wkid))
        except Exception:
            try:
                return CRS.from_user_input(f"ESRI:{int(wkid)}")
            except Exception:
                pass
    wkt = sr.get("wkt")
    if wkt:
        try:
            return CRS.from_wkt(wkt)
        except Exception:
            pass
    return CRS.from_epsg(4326)


def parse_esri_geometry(g: dict | None, gtype: str | None) -> shapely.Geometry | None:
    """Convert an Esri JSON geometry object into a 2D Shapely geometry."""
    if not g:
        return None
    try:
        if gtype == "esriGeometryPolygon" or "rings" in g:
            rings = g.get("rings")
            if not rings:
                return None
            valid_rings = [np.asarray(r, dtype=np.float64)[:, :2] for r in rings if len(r) >= 3]
            if not valid_rings:
                return None
            if len(valid_rings) == 1:
                return shapely.polygons(valid_rings[0])
            # Collect polygons without expensive per-feature make_valid
            return shapely.multipolygons([shapely.polygons(r) for r in valid_rings])
        elif gtype == "esriGeometryPolyline" or "paths" in g:
            paths = g.get("paths")
            if not paths:
                return None
            valid_paths = [np.asarray(p, dtype=np.float64)[:, :2] for p in paths if len(p) >= 2]
            if not valid_paths:
                return None
            if len(valid_paths) == 1:
                return shapely.linestrings(valid_paths[0])
            return shapely.multilinestrings([shapely.linestrings(p) for p in valid_paths])
        elif gtype == "esriGeometryPoint" or ("x" in g and "y" in g):
            x, y = g.get("x"), g.get("y")
            if x is None or y is None or not np.isfinite(x) or not np.isfinite(y):
                return None
            return shapely.points(float(x), float(y))
        elif gtype == "esriGeometryMultipoint" or "points" in g:
            pts = g.get("points")
            if not pts:
                return None
            arr = np.asarray(pts, dtype=np.float64)[:, :2]
            return shapely.multipoints(arr)
    except Exception:
        return None
    return None


def reproject_geoms(geoms: np.ndarray, src_crs: CRS, dst_crs: CRS) -> np.ndarray:
    """Vectorized coordinate transformation on an array of Shapely geometries."""
    if src_crs.equals(dst_crs):
        return geoms
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)

    def _tx(coords: np.ndarray) -> np.ndarray:
        if len(coords) == 0:
            return coords
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack((x, y))

    return shapely.transform(geoms, _tx)


def pick_attr(attrs: dict, candidates: list[str], domain_map: dict[str, dict] | None = None) -> str | None:
    """Pick the first non-empty attribute value from candidates, decoding Esri coded domains."""
    for col in candidates:
        if col in attrs:
            val = attrs[col]
            if val is not None:
                if domain_map and col in domain_map and val in domain_map[col]:
                    val = domain_map[col][val]
                s = str(val).strip()
                if s and s.upper() not in {"NONE", "NULL", "NAN", "<NULL>", ""}:
                    return s
    # Case-insensitive fallback
    lower_map = {k.lower(): k for k in attrs}
    for col in candidates:
        actual = lower_map.get(col.lower())
        if actual is not None:
            val = attrs[actual]
            if val is not None:
                if domain_map and actual in domain_map and val in domain_map[actual]:
                    val = domain_map[actual][val]
                s = str(val).strip()
                if s and s.upper() not in {"NONE", "NULL", "NAN", "<NULL>", ""}:
                    return s
    return None


def extract_pwsid_from_attrs(attrs: dict, fallback_state: str | None) -> str | None:
    for col in ["PWSID", "pwsid", "PWS_ID", "pws_id", "PWSId", "SABL_PWSID", "PWID", "PWSSID", "Water_System_ID", "WATER_SYSTEM_NUMBER", "pws_id"]:
        if col in attrs and attrs[col] is not None:
            norm = normalize_pwsid(attrs[col], fallback_state=fallback_state)
            if norm:
                return norm
    return None


def normalize_service_boundaries() -> pd.DataFrame:
    """Extract, reproject, dissolve multi-part/parcel features, and hash all service boundary polygons."""
    catalog_df = pd.read_parquet(SILVER_DIR / "source_inventory.parquet")
    crs_4326 = CRS.from_epsg(4326)
    crs_5070 = CRS.from_epsg(5070)

    boundary_rows = []

    # -------------------------------------------------------------------------
    # A. Process all non-pruned ArcGIS Service Boundary Polygon Layers
    # -------------------------------------------------------------------------
    gis_boundary_layers = catalog_df[
        (catalog_df["source_type"] == "arcgis_layer")
        & (catalog_df["entity_category"] == "service_boundary")
        & (~catalog_df["is_pruned_duplicate"])
        & (catalog_df["geometry_type"] == "esriGeometryPolygon")
        & (catalog_df["source_id"] != "california_broadband_territories_cpuc_2023")
    ]

    for src in gis_boundary_layers.itertuples(index=False):
        name = src.source_id
        folder = RAW_DATA_ROOT / "gis" / name
        meta = json.loads((folder / "layer_metadata.json").read_text(encoding="utf-8", errors="replace"))
        domain_map = build_esri_coded_domain_map(meta)
        src_crs = get_esri_crs(meta)
        fallback_state = src.state if src.state != "US" else None

        raw_recs = []
        raw_geoms = []
        for page_path in sorted(folder.glob("page_*.json.gz")):
            obj = orjson.loads(gzip.decompress(page_path.read_bytes()))
            for feat in obj.get("features") or []:
                g = parse_esri_geometry(feat.get("geometry"), "esriGeometryPolygon")
                if g is None or shapely.is_empty(g):
                    continue
                attrs = feat.get("attributes") or {}
                pname = pick_attr(attrs, NAME_ATTR_CANDIDATES, domain_map) or SINGLE_PROVIDER_DEFAULTS.get(name) or name
                pid = pick_attr(attrs, ID_ATTR_CANDIDATES, domain_map)
                pwsid = extract_pwsid_from_attrs(attrs, fallback_state) if src.sector in ("water", "multi_utility") else None
                st = normalize_state_code(attrs.get("STATE") or attrs.get("State") or attrs.get("PRIMACY_AGENCY_CODE")) or fallback_state or "US"

                # Resolve sub-sector for multi-utility layers
                sec = src.sector
                if name == "oregon_electric_gas_areas_odoe":
                    ng_el = str(attrs.get("NG_or_Electric") or "").upper()
                    sec = "natural_gas" if "GAS" in ng_el or "NG" in ng_el else "electric"
                elif name == "georgia_fulton_water_sewer_service_areas":
                    stype = str(attrs.get("ServiceType") or "").upper()
                    sec = "wastewater" if "SEWER" in stype else "water"

                # Resolve zone_role refinement (e.g., Frederick County W-1/S-1 vs planned)
                zrole = src.zone_role
                if "frederick" in name:
                    code_val = str(attrs.get("WP_Type") or attrs.get("SP_Type") or "").upper()
                    zrole = "active_retail_service" if code_val in ("W-1", "S-1") else "planned_or_future_service"
                elif name == "virginia_fairfax_sewer_service_areas":
                    sval = str(attrs.get("SERVICE") or "").upper()
                    if "OUTSIDE" in sval:
                        zrole = "not_serviced_or_excluded"

                raw_recs.append((pname, pid, pwsid, st, sec, zrole))
                raw_geoms.append(g)

        if not raw_geoms:
            continue

        geoms_arr = np.array(raw_geoms, dtype=object)
        geoms_4326 = reproject_geoms(geoms_arr, src_crs, crs_4326)
        # Only run make_valid on geometries that are actually invalid
        invalid_mask = ~shapely.is_valid(geoms_4326)
        if np.any(invalid_mask):
            geoms_4326[invalid_mask] = shapely.make_valid(geoms_4326[invalid_mask])

        # Group and dissolve multi-polygon / parcel-level fragments within the same layer
        # by (provider_name, pwsid, sector, state, zone_role)
        df_layer = pd.DataFrame(
            raw_recs,
            columns=["provider_name", "native_id", "pwsid", "state_code", "sector", "zone_role"],
        )
        df_layer["geom"] = geoms_4326

        grouped = df_layer.groupby(["provider_name", "state_code", "sector", "zone_role"], dropna=False)
        dissolved_rows = []
        dissolved_geoms = []
        for (pname, st, sec, zrole), grp in grouped:
            g_arr = grp["geom"].values
            if len(g_arr) == 1:
                u_geom = g_arr[0]
            elif len(g_arr) > 400:
                # Parcel-level layers (Summerville, Frederick County): simplify slightly and union in chunks
                simp = shapely.simplify(g_arr, tolerance=0.0001, preserve_topology=True)
                chunks = [shapely.union_all(simp[k : k + 500]) for k in range(0, len(simp), 500)]
                u_geom = shapely.union_all(chunks)
            else:
                try:
                    u_geom = shapely.union_all(g_arr)
                except Exception:
                    u_geom = shapely.union_all(shapely.make_valid(g_arr))
            if not shapely.is_valid(u_geom):
                u_geom = shapely.make_valid(u_geom)
            if shapely.is_empty(u_geom):
                continue
            first_pwsid = grp["pwsid"].dropna().iloc[0] if grp["pwsid"].notna().any() else None
            first_nid = grp["native_id"].dropna().iloc[0] if grp["native_id"].notna().any() else None
            dissolved_rows.append((pname, first_nid, first_pwsid, st, sec, zrole, len(grp)))
            dissolved_geoms.append(u_geom)

        if not dissolved_geoms:
            continue

        dgeoms_4326 = np.array(dissolved_geoms, dtype=object)
        dgeoms_5070 = reproject_geoms(dgeoms_4326, crs_4326, crs_5070)
        areas_sqkm = shapely.area(dgeoms_5070) / 1e6
        pts = shapely.point_on_surface(dgeoms_4326)
        lons = shapely.get_x(pts)
        lats = shapely.get_y(pts)
        wkbs = shapely.to_wkb(dgeoms_4326)

        for idx, (pname, nid, pwsid, st, sec, zrole, poly_cnt) in enumerate(dissolved_rows):
            ghash = wkb_sha256(dgeoms_4326[idx])
            boundary_rows.append({
                "boundary_id": deterministic_id("BND", name, sec, st, pname, nid or idx),
                "source_id": name,
                "sector": sec,
                "state_code": st,
                "provider_name": str(pname),
                "provider_name_norm": normalize_entity_name(pname),
                "provider_name_core": normalize_entity_name(pname, strip_utility_terms=True),
                "native_id": str(nid) if nid else None,
                "pwsid": pwsid,
                "cwns_id": None,
                "eia_utility_id": str(nid) if name == "electric_retail_territories_hifld" and nid and str(nid).isdigit() else None,
                "zone_role": zrole,
                "authority_tier": int(src.authority_tier),
                "verification_mode": "modeled_or_generalized" if src.authority_tier >= 4 else "published_gis",
                "license_tier": src.license_tier,
                "source_polygon_count": int(poly_cnt),
                "area_sqkm": float(areas_sqkm[idx]) if np.isfinite(areas_sqkm[idx]) else 0.0,
                "repr_lon": float(lons[idx]) if np.isfinite(lons[idx]) else None,
                "repr_lat": float(lats[idx]) if np.isfinite(lats[idx]) else None,
                "geometry_hash": ghash,
                "geometry_wkb": wkbs[idx],
            })
        print(f"Normalized GIS boundary layer {name}: {len(raw_geoms)} raw -> {len(dissolved_rows)} dissolved zones", flush=True)

    # -------------------------------------------------------------------------
    # B. Process State & Federal Vector Archives (GPKG, GDB, Shapefile, GeoJSON)
    # -------------------------------------------------------------------------
    vector_specs = [
        {
            "source_id": "state_mn_electric_service_areas",
            "vsi": (RAW_DATA_ROOT / "states/mn/electric_service_areas.gpkg").as_posix(),
            "layer": "service_areas",
            "sector": "electric",
            "state": "MN",
            "name_col": "elec_comp",
            "id_col": "eusa_v5_id",
            "zone_role": "certified_franchise_territory",
            "authority_tier": 2,
        },
        {
            "source_id": "state_ny_electric_territories",
            "vsi": (RAW_DATA_ROOT / "states/ny/electric_territories.geojson").as_posix(),
            "layer": None,
            "sector": "electric",
            "state": "NY",
            "name_col": "comp_full",
            "id_col": "comp_id",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
        },
        {
            "source_id": "state_ny_gas_territories",
            "vsi": (RAW_DATA_ROOT / "states/ny/gas_territories.geojson").as_posix(),
            "layer": None,
            "sector": "natural_gas",
            "state": "NY",
            "name_col": "comp_full",
            "id_col": "comp_id",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
        },
        {
            "source_id": "state_tx_puct_water_ccn",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'states/tx/puct_water_ccn_tsms.zip').as_posix()}/PUCT_CCN_WATER_TSMS_for_GIS/PUCT_CCN_WATER_TSMS.shp",
            "layer": None,
            "sector": "water",
            "state": "TX",
            "name_col": "UTILITY",
            "id_col": "CCN_NO",
            "zone_role": "certified_franchise_territory",
            "authority_tier": 2,
        },
        {
            "source_id": "state_tx_puct_sewer_ccn",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'states/tx/puct_sewer_ccn_tsms.zip').as_posix()}/PUCT_CCN_SEWER_TSMS_for_GIS/PUCT_CCN_SEWER_TSMS.shp",
            "layer": None,
            "sector": "wastewater",
            "state": "TX",
            "name_col": "UTILITY",
            "id_col": "CCN_NO",
            "zone_role": "certified_franchise_territory",
            "authority_tier": 2,
        },
        {
            "source_id": "state_wi_psc_electric_territories",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'states/wi/psc_electric_territories.zip').as_posix()}/EL_PSCW_ServTerr/Investor-Owned.shp",
            "layer": None,
            "sector": "electric",
            "state": "WI",
            "name_col": "UTIL_LAB",
            "id_col": "PSC_ID",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
        },
        {
            "source_id": "state_wi_psc_electric_territories",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'states/wi/psc_electric_territories.zip').as_posix()}/EL_PSCW_ServTerr/Cooperative.shp",
            "layer": None,
            "sector": "electric",
            "state": "WI",
            "name_col": "UTIL_LAB",
            "id_col": "PSC_ID",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
        },
        {
            "source_id": "state_wi_psc_electric_territories",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'states/wi/psc_electric_territories.zip').as_posix()}/EL_PSCW_ServTerr/Municipal.shp",
            "layer": None,
            "sector": "electric",
            "state": "WI",
            "name_col": "UTIL_LAB",
            "id_col": "PSC_ID",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
        },
        {
            "source_id": "state_wi_psc_natural_gas_territories",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'states/wi/psc_natural_gas_territories.zip').as_posix()}",
            "layer": "NG_PSCW_ServTerr",
            "sector": "natural_gas",
            "state": "WI",
            "name_col": "Util_Name",
            "id_col": "Util_ID",
            "zone_role": "active_retail_service",
            "authority_tier": 2,
        },
        {
            "source_id": "federal_epa_pws_boundaries_v3",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'water/epa_pws_boundaries_latest.zip').as_posix()}/3_0/Service_Areas_V_3_0.gpkg",
            "layer": "CWS",
            "sector": "water",
            "state": None,
            "name_col": "PWS_Name",
            "id_col": "PWSID",
            "zone_role": "active_retail_service",
            "authority_tier": 3,
        },
        {
            "source_id": "federal_epa_sewersheds_v1_3",
            "vsi": f"/vsizip/{(RAW_DATA_ROOT / 'wastewater/epa_sewersheds_v1_3.zip').as_posix()}/Version_1_3.gdb",
            "layer": "Sewersheds",
            "sector": "wastewater",
            "state": None,
            "name_col": "FACILITY_NAME",
            "id_col": "CWNS_ID",
            "zone_role": "active_retail_service",
            "authority_tier": 4,
        },
    ]

    for spec in vector_specs:
        meta, vdf, raw_geoms = read_ogr_table(spec["vsi"], layer=spec["layer"])
        src_crs = CRS.from_user_input(meta["crs"]) if meta.get("crs") else crs_4326
        geoms_4326 = reproject_geoms(raw_geoms, src_crs, crs_4326)
        inv = ~shapely.is_valid(geoms_4326)
        if np.any(inv):
            geoms_4326[inv] = shapely.make_valid(geoms_4326[inv])
        geoms_5070 = reproject_geoms(geoms_4326, crs_4326, crs_5070)
        areas_sqkm = shapely.area(geoms_5070) / 1e6
        pts = shapely.point_on_surface(geoms_4326)
        lons = shapely.get_x(pts)
        lats = shapely.get_y(pts)
        wkbs = shapely.to_wkb(geoms_4326)

        sid = spec["source_id"]
        for i in range(len(vdf)):
            if shapely.is_empty(geoms_4326[i]):
                continue
            row = vdf.iloc[i]
            pname = str(row.get(spec["name_col"]) or sid).strip()
            nid = str(row.get(spec["id_col"]) or i).strip()
            st = spec["state"]
            if not st:
                st = normalize_state_code(row.get("STATE_CODE") or row.get("Primacy_Agency")) or (nid[:2] if len(nid) >= 2 and nid[:2].isalpha() else "US")

            # Distinguish sourced vs modeled polygons in EPA v3 water and EPA v1.3 sewersheds
            atier = spec["authority_tier"]
            vmode = "published_gis"
            if sid == "federal_epa_pws_boundaries_v3":
                mm = str(row.get("Model_Method") or row.get("Symbology_Field") or "").upper()
                if "MODEL" in mm or "WELL" in mm or "BUFFER" in mm:
                    atier = 4
                    vmode = "modeled_or_generalized"
                else:
                    atier = 3
                    vmode = "state_or_utility_submitted_to_epa"
            elif sid == "federal_epa_sewersheds_v1_3":
                mm = str(row.get("Method") or "").upper()
                if "SOURCE" in mm or "STATE" in mm or "UTILITY" in mm:
                    atier = 3
                    vmode = "state_or_utility_submitted_to_epa"
                else:
                    atier = 4
                    vmode = "modeled_or_generalized"

            pwsid = normalize_pwsid(nid, fallback_state=st) if spec["sector"] == "water" and sid == "federal_epa_pws_boundaries_v3" else None
            cwns_id = str(int(float(nid))) if sid == "federal_epa_sewersheds_v1_3" and nid.replace(".", "").isdigit() else None

            boundary_rows.append({
                "boundary_id": deterministic_id("BND", sid, spec["layer"] or "0", st, pname, nid, i),
                "source_id": sid,
                "sector": spec["sector"],
                "state_code": st,
                "provider_name": pname,
                "provider_name_norm": normalize_entity_name(pname),
                "provider_name_core": normalize_entity_name(pname, strip_utility_terms=True),
                "native_id": nid,
                "pwsid": pwsid,
                "cwns_id": cwns_id,
                "eia_utility_id": None,
                "zone_role": spec["zone_role"],
                "authority_tier": atier,
                "verification_mode": vmode,
                "license_tier": "public_unrestricted",
                "source_polygon_count": 1,
                "area_sqkm": float(areas_sqkm[i]) if np.isfinite(areas_sqkm[i]) else 0.0,
                "repr_lon": float(lons[i]) if np.isfinite(lons[i]) else None,
                "repr_lat": float(lats[i]) if np.isfinite(lats[i]) else None,
                "geometry_hash": wkb_sha256(geoms_4326[i]),
                "geometry_wkb": wkbs[i],
            })
        print(f"Normalized vector archive {sid} ({spec['layer']}): {len(vdf)} features", flush=True)

    boundaries_df = pd.DataFrame(boundary_rows)
    # Remove any exact intra-source geometry+provider duplicates
    before_dedup = len(boundaries_df)
    boundaries_df = boundaries_df.drop_duplicates(
        subset=["source_id", "sector", "provider_name_norm", "zone_role", "geometry_hash"]
    ).reset_index(drop=True)
    print(f"Total normalized service boundary zones: {len(boundaries_df)} (removed {before_dedup - len(boundaries_df)} exact intra-source geometry duplicates).")

    boundaries_df.to_parquet(SILVER_DIR / "service_boundaries_normalized.parquet", index=False)
    return boundaries_df


def normalize_facilities_and_networks() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract and harmonize major utility facilities (plants, substations, treatment plants, dams) and linear networks."""
    catalog_df = pd.read_parquet(SILVER_DIR / "source_inventory.parquet")
    crs_4326 = CRS.from_epsg(4326)
    facility_rows = []

    # 1. EIA-860 (2025 Power Plants with capacity aggregated from Operable Generators)
    with zipfile.ZipFile(RAW_DATA_ROOT / "electric/eia860_2025.zip") as zf:
        with zf.open("2___Plant_Y2025.xlsx") as f:
            plant_df = pd.read_excel(f, sheet_name="Plant", skiprows=1)
        with zf.open("3_1_Generator_Y2025.xlsx") as f:
            gen_df = pd.read_excel(f, sheet_name="Operable", skiprows=1)

    cap_by_plant = {}
    tech_by_plant = {}
    for row in gen_df.itertuples(index=False):
        pcode = pd.to_numeric(row[2], errors="coerce")
        cap = pd.to_numeric(row[15], errors="coerce")
        tech = str(row[7]).strip() if pd.notna(row[7]) else None
        if pd.notna(pcode):
            pc = int(pcode)
            if pd.notna(cap):
                cap_by_plant[pc] = cap_by_plant.get(pc, 0.0) + float(cap)
            if tech and pc not in tech_by_plant:
                tech_by_plant[pc] = tech

    for row in plant_df.itertuples(index=False):
        pcode_num = pd.to_numeric(row[2], errors="coerce")
        if pd.isna(pcode_num):
            continue
        pcode = int(pcode_num)
        uid_num = pd.to_numeric(row[0], errors="coerce")
        uid = str(int(uid_num)) if pd.notna(uid_num) else None
        uname = str(row[1]).strip() if pd.notna(row[1]) else None
        pname = str(row[3]).strip() if pd.notna(row[3]) else f"Plant {pcode}"
        st = normalize_state_code(row[6])
        cnty = str(row[8]).strip() if pd.notna(row[8]) else None
        lat = pd.to_numeric(row[9], errors="coerce")
        lon = pd.to_numeric(row[10], errors="coerce")
        facility_rows.append({
            "facility_id": f"FAC_EIA860_{pcode}",
            "source_id": "federal_eia860_2025",
            "sector": "electric",
            "facility_subtype": tech_by_plant.get(pcode, "power_plant"),
            "facility_name": pname,
            "facility_name_norm": normalize_entity_name(pname),
            "operator_name": uname,
            "operator_name_norm": normalize_entity_name(uname),
            "state_code": st,
            "county_name": cnty,
            "eia_plant_code": str(pcode),
            "eia_utility_id": uid,
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "nid_id": None,
            "ferc_project_num": None,
            "capacity_mw": cap_by_plant.get(pcode),
            "design_flow_mgd": None,
            "operational_status": "Operational",
            "lon": float(lon) if pd.notna(lon) else None,
            "lat": float(lat) if pd.notna(lat) else None,
            "authority_tier": 3,
        })

    # 2. USGS Large-Scale Solar PV Database (USPVDB v4.0, April 2026)
    pv_df = pd.read_csv(RAW_DATA_ROOT / "electric/usgs_uspvdb_v4_20260414.csv", low_memory=False, encoding_errors="replace")
    for row in pv_df.itertuples(index=False):
        cid = str(row.case_id)
        eia_id = pd.to_numeric(getattr(row, "eia_id", None), errors="coerce")
        pname = str(getattr(row, "p_name", "") or f"Solar {cid}").strip()
        st = normalize_state_code(getattr(row, "p_state", None))
        cap = pd.to_numeric(getattr(row, "p_cap_ac", getattr(row, "p_cap_dc", None)), errors="coerce")
        lat = pd.to_numeric(getattr(row, "ylat", None), errors="coerce")
        lon = pd.to_numeric(getattr(row, "xlong", None), errors="coerce")
        facility_rows.append({
            "facility_id": f"FAC_USPVDB_{cid}",
            "source_id": "federal_usgs_uspvdb_v4_0",
            "sector": "electric",
            "facility_subtype": "solar_photovoltaic",
            "facility_name": pname,
            "facility_name_norm": normalize_entity_name(pname),
            "operator_name": None,
            "operator_name_norm": "",
            "state_code": st,
            "county_name": str(getattr(row, "p_county", "")).strip() if pd.notna(getattr(row, "p_county", None)) else None,
            "eia_plant_code": str(int(eia_id)) if pd.notna(eia_id) and int(eia_id) > 0 else None,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "nid_id": None,
            "ferc_project_num": None,
            "capacity_mw": float(cap) if pd.notna(cap) else None,
            "design_flow_mgd": None,
            "operational_status": "Operational",
            "lon": float(lon) if pd.notna(lon) else None,
            "lat": float(lat) if pd.notna(lat) else None,
            "authority_tier": 3,
        })

    # 3. USGS Wind Turbine Database (USWTDB v9.1, Sept 2026 - aggregated to wind farm project level)
    with zipfile.ZipFile(RAW_DATA_ROOT / "electric/usgs_uswtdb_latest_csv.zip") as zf:
        with zf.open("uswtdb_V9_1_20260928.csv") as f:
            wt_df = pd.read_csv(
                f,
                usecols=["usgs_pr_id", "eia_id", "t_state", "t_county", "p_name", "p_tnum", "p_cap", "xlong", "ylat"],
                low_memory=False,
                encoding_errors="replace",
            )
    wt_proj = wt_df.groupby(["p_name", "t_state"], dropna=False).agg(
        eia_id=("eia_id", "first"),
        county=("t_county", "first"),
        cap_mw=("p_cap", "max"),
        turbine_count=("xlong", "count"),
        lon=("xlong", "mean"),
        lat=("ylat", "mean"),
    ).reset_index()
    for idx, row in enumerate(wt_proj.itertuples(index=False)):
        eia_id = pd.to_numeric(row.eia_id, errors="coerce")
        pname = str(row.p_name or f"Wind Project {idx}").strip()
        st = normalize_state_code(row.t_state)
        facility_rows.append({
            "facility_id": deterministic_id("FAC_USWTDB", st, pname, idx),
            "source_id": "federal_usgs_uswtdb_v9_1",
            "sector": "electric",
            "facility_subtype": "wind_power_project",
            "facility_name": pname,
            "facility_name_norm": normalize_entity_name(pname),
            "operator_name": None,
            "operator_name_norm": "",
            "state_code": st,
            "county_name": str(row.county).strip() if pd.notna(row.county) else None,
            "eia_plant_code": str(int(eia_id)) if pd.notna(eia_id) and int(eia_id) > 0 else None,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "nid_id": None,
            "ferc_project_num": None,
            "capacity_mw": float(row.cap_mw) if pd.notna(row.cap_mw) else None,
            "design_flow_mgd": None,
            "operational_status": "Operational",
            "lon": float(row.lon) if pd.notna(row.lon) else None,
            "lat": float(row.lat) if pd.notna(row.lat) else None,
            "authority_tier": 3,
        })

    # 4. EPA CWNS 2022 Physical Locations (Wastewater & Stormwater Treatment Facilities)
    with zipfile.ZipFile(RAW_DATA_ROOT / "wastewater/epa_cwns_2022_national_sept2026.zip") as zf:
        with zf.open("2022CWNS_NATIONAL_Sept2026/FACILITIES.csv") as f:
            cwns_fac = pd.read_csv(f, usecols=["CWNS_ID", "FACILITY_NAME", "STATE_CODE", "INFRASTRUCTURE_TYPE", "OWNER_TYPE"], low_memory=False)
        with zf.open("2022CWNS_NATIONAL_Sept2026/PHYSICAL_LOCATION.csv") as f:
            cwns_loc = pd.read_csv(f, usecols=["CWNS_ID", "LATITUDE", "LONGITUDE", "COUNTY_NAME"], low_memory=False)
        with zf.open("2022CWNS_NATIONAL_Sept2026/FACILITY_PERMIT.csv") as f:
            cwns_perm = pd.read_csv(f, usecols=["CWNS_ID", "PERMIT_NUMBER", "PERMIT_SOURCE"], low_memory=False)
        with zf.open("2022CWNS_NATIONAL_Sept2026/FLOW.csv") as f:
            cwns_flow = pd.read_csv(f, low_memory=False)

    cwns_merged = cwns_fac.merge(cwns_loc.drop_duplicates("CWNS_ID"), on="CWNS_ID", how="left")
    npdes_map = dict(
        cwns_perm[cwns_perm["PERMIT_SOURCE"] == "NPDES"]
        .drop_duplicates("CWNS_ID")[["CWNS_ID", "PERMIT_NUMBER"]]
        .values
    )
    flow_col = next((c for c in cwns_flow.columns if "DESIGN" in c.upper() or "EXISTING" in c.upper()), None)
    flow_map = {}
    if flow_col:
        for r in cwns_flow.itertuples(index=False):
            fv = pd.to_numeric(getattr(r, flow_col, None), errors="coerce")
            if pd.notna(fv):
                flow_map[r.CWNS_ID] = float(fv)

    for row in cwns_merged.itertuples(index=False):
        cid = str(row.CWNS_ID)
        fname = str(row.FACILITY_NAME or cid).strip()
        st = normalize_state_code(row.STATE_CODE)
        itype = str(row.INFRASTRUCTURE_TYPE or "Wastewater").strip()
        sec = "stormwater" if "STORM" in itype.upper() else "wastewater"
        facility_rows.append({
            "facility_id": f"FAC_CWNS_{cid}",
            "source_id": "federal_epa_cwns_2022",
            "sector": sec,
            "facility_subtype": itype.lower().replace(" ", "_"),
            "facility_name": fname,
            "facility_name_norm": normalize_entity_name(fname),
            "operator_name": fname,
            "operator_name_norm": normalize_entity_name(fname),
            "state_code": st,
            "county_name": str(row.COUNTY_NAME).strip() if pd.notna(row.COUNTY_NAME) else None,
            "eia_plant_code": None,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": str(npdes_map[row.CWNS_ID]).strip() if row.CWNS_ID in npdes_map and pd.notna(npdes_map[row.CWNS_ID]) else None,
            "cwns_id": cid,
            "nid_id": None,
            "ferc_project_num": None,
            "capacity_mw": None,
            "design_flow_mgd": flow_map.get(row.CWNS_ID),
            "operational_status": "Operational",
            "lon": float(row.LONGITUDE) if pd.notna(row.LONGITUDE) else None,
            "lat": float(row.LATITUDE) if pd.notna(row.LATITUDE) else None,
            "authority_tier": 3,
        })

    # 5. ArcGIS Facility Point Layers (EIA Power Plants, FERC Hydro, USBR Facilities, Substations, State Plants/WWTPs)
    gis_fac_layers = catalog_df[
        (catalog_df["source_type"] == "arcgis_layer")
        & (catalog_df["entity_category"] == "facility_point")
        & (~catalog_df["is_pruned_duplicate"])
        & (catalog_df["source_id"] != "national_usace_inventory_of_dams")
    ]
    for src in gis_fac_layers.itertuples(index=False):
        name = src.source_id
        folder = RAW_DATA_ROOT / "gis" / name
        meta = json.loads((folder / "layer_metadata.json").read_text(encoding="utf-8", errors="replace"))
        domain_map = build_esri_coded_domain_map(meta)
        src_crs = get_esri_crs(meta)
        fallback_state = src.state if src.state != "US" else None

        recs = []
        geoms = []
        for page_path in sorted(folder.glob("page_*.json.gz")):
            obj = orjson.loads(gzip.decompress(page_path.read_bytes()))
            for feat in obj.get("features") or []:
                g = parse_esri_geometry(feat.get("geometry"), src.geometry_type)
                if g is None or shapely.is_empty(g):
                    continue
                attrs = feat.get("attributes") or {}
                fname = pick_attr(attrs, ["Plant_Name", "PLANT_NAME", "Facility_Name", "FACILITYNAME", "Name", "NAME", "assetname", "Dam_Name", "p_name", "SITE_NAME"], domain_map) or name
                opname = pick_attr(attrs, ["Utility_Na", "UTILITY_NAME", "operatingentity1", "Licensees", "OWNER", "Owner_Names", "Operator", "PERMITTEE", "COMPANY1", "p_entity"], domain_map)
                pcode = pick_attr(attrs, ["Plant_Code", "PLANT_CODE"], domain_map)
                uid = pick_attr(attrs, ["Utility_ID"], domain_map)
                nid = pick_attr(attrs, ["NID_ID", "NIDID"], domain_map)
                pnum = pick_attr(attrs, ["PNum"], domain_map)
                npdes = pick_attr(attrs, ["NJPDES_NO", "PERMITID", "PERMIT"], domain_map)
                cap = pd.to_numeric(attrs.get("Total_MW") or attrs.get("Install_MW") or attrs.get("Capacity") or attrs.get("p_cap") or attrs.get("Megawatts__mW_") or attrs.get("capacityfacility"), errors="coerce")
                st = normalize_state_code(attrs.get("State") or attrs.get("STATE") or attrs.get("States") or attrs.get("STATENAME")) or fallback_state or "US"
                recs.append((fname, opname, pcode, uid, nid, pnum, npdes, cap, st))
                geoms.append(g)

        if not geoms:
            continue
        geoms_4326 = shapely.make_valid(reproject_geoms(np.array(geoms, dtype=object), src_crs, crs_4326))
        pts = shapely.point_on_surface(geoms_4326)
        lons = shapely.get_x(pts)
        lats = shapely.get_y(pts)

        for idx, (fname, opname, pcode, uid, nid, pnum, npdes, cap, st) in enumerate(recs):
            # Convert kW to MW for FERC hydro layers
            cap_mw = float(cap) / 1000.0 if ("ferc_hydropower" in name and pd.notna(cap)) else (float(cap) if pd.notna(cap) else None)
            facility_rows.append({
                "facility_id": deterministic_id("FAC_GIS", name, st, fname, pcode or pnum or idx),
                "source_id": name,
                "sector": src.sector,
                "facility_subtype": name,
                "facility_name": str(fname),
                "facility_name_norm": normalize_entity_name(fname),
                "operator_name": str(opname) if opname else None,
                "operator_name_norm": normalize_entity_name(opname) if opname else "",
                "state_code": st,
                "county_name": None,
                "eia_plant_code": str(int(float(pcode))) if pcode and str(pcode).replace(".", "").isdigit() else None,
                "eia_utility_id": str(int(float(uid))) if uid and str(uid).replace(".", "").isdigit() else None,
                "pwsid": None,
                "npdes_id": npdes,
                "cwns_id": None,
                "nid_id": nid,
                "ferc_project_num": f"P-{pnum}" if pnum and not str(pnum).startswith("P-") else pnum,
                "capacity_mw": cap_mw,
                "design_flow_mgd": None,
                "operational_status": "Under Construction" if "under_construction" in name else "Operational",
                "lon": float(lons[idx]) if np.isfinite(lons[idx]) else None,
                "lat": float(lats[idx]) if np.isfinite(lats[idx]) else None,
                "authority_tier": int(src.authority_tier),
            })

    facilities_df = pd.DataFrame(facility_rows)
    facilities_df.to_parquet(SILVER_DIR / "facilities_normalized.parquet", index=False)

    # 6. Summarize Linear Infrastructure Networks & Node Inventories by Layer/Operator/State
    network_summary_rows = []
    net_layers = catalog_df[
        (catalog_df["source_type"] == "arcgis_layer")
        & (catalog_df["entity_category"].isin(["network_line", "network_node"]))
        & (~catalog_df["is_pruned_duplicate"])
    ]
    for src in net_layers.itertuples(index=False):
        name = src.source_id
        folder = RAW_DATA_ROOT / "gis" / name
        meta = json.loads((folder / "layer_metadata.json").read_text(encoding="utf-8", errors="replace"))
        domain_map = build_esri_coded_domain_map(meta)
        fallback_state = src.state if src.state != "US" else "US"

        op_counts = {}
        for page_path in sorted(folder.glob("page_*.json.gz")):
            obj = orjson.loads(gzip.decompress(page_path.read_bytes()))
            for feat in obj.get("features") or []:
                attrs = feat.get("attributes") or {}
                op = pick_attr(
                    attrs,
                    ["OWNER", "Owner", "OWNRSHIP", "OWNEDBY", "Operator", "Opername", "OpShortNm", "Utility", "operatingentity1", "PWS_ID", "PWSID"],
                    domain_map,
                ) or SINGLE_PROVIDER_DEFAULTS.get(name) or name
                volt_or_mat = pick_attr(attrs, ["VOLT_CLASS", "VOLTAGE", "kv", "MATERIAL", "Material", "PIPE_MATERIAL", "TYPE", "TYPEPIPE", "assettype"], domain_map) or "unspecified"
                key = (str(op), str(volt_or_mat))
                op_counts[key] = op_counts.get(key, 0) + 1

        for (op, vmat), cnt in op_counts.items():
            network_summary_rows.append({
                "network_group_id": deterministic_id("NET", name, fallback_state, op, vmat),
                "source_id": name,
                "sector": src.sector,
                "state_code": fallback_state,
                "asset_category": src.entity_category,
                "geometry_type": src.geometry_type,
                "owner_or_operator": op,
                "owner_name_norm": normalize_entity_name(op),
                "material_or_voltage_class": vmat,
                "feature_count": int(cnt),
                "authority_tier": int(src.authority_tier),
                "license_tier": src.license_tier,
            })

    networks_df = pd.DataFrame(network_summary_rows)
    networks_df.to_parquet(SILVER_DIR / "linear_and_node_networks_summary.parquet", index=False)

    print(f"Normalized facilities: {len(facilities_df)} rows; network summaries: {len(networks_df)} groups.")
    return facilities_df, networks_df


if __name__ == "__main__":
    normalize_service_boundaries()
    normalize_facilities_and_networks()
