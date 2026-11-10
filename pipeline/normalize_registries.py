"""Normalize US Census 2025 Counties & States, Federal Utility Registries, and County/Community Lookups into Silver."""
import hashlib
import json
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pipeline.config import (
    ABBR_TO_STATE_NAME,
    RAW_DATA_ROOT,
    SILVER_DIR,
    deterministic_id,
    normalize_county_name,
    normalize_entity_name,
    normalize_pwsid,
    normalize_state_code,
)


def wkb_sha256(g: shapely.Geometry | None) -> str | None:
    if g is None or shapely.is_empty(g):
        return None
    snapped = shapely.set_precision(g, grid_size=1e-6)
    return hashlib.sha256(shapely.to_wkb(snapped)).hexdigest()


def read_ogr_table(vsi_path: str, layer: str | None = None) -> tuple[dict, pd.DataFrame, np.ndarray]:
    """Read an OGR vector source via pyogrio.raw.read_arrow without requiring geopandas."""
    meta, table = pyogrio.raw.read_arrow(vsi_path, layer=layer)
    geom_col = meta.get("geometry_name") or "wkb_geometry"
    wkb_list = table[geom_col].to_pylist()
    geoms = shapely.from_wkb(wkb_list)
    df = table.drop([geom_col]).to_pandas()
    return meta, df, geoms


def build_reference_geographies() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract and normalize US Census 2025 States and Counties to Silver GeoParquet."""
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    # 1. States
    state_zip = RAW_DATA_ROOT / "reference/cb_2025_us_state_500k.zip"
    _, sdf, raw_sgeoms = read_ogr_table(f"/vsizip/{state_zip.as_posix()}")
    geoms = shapely.make_valid(raw_sgeoms)
    pts = shapely.point_on_surface(geoms)
    states_df = pd.DataFrame({
        "state_fips": sdf["STATEFP"].astype(str).str.zfill(2),
        "state_code": sdf["STUSPS"].astype(str).str.upper(),
        "state_name": sdf["NAME"].astype(str),
        "aland_sqm": pd.to_numeric(sdf["ALAND"], errors="coerce"),
        "awater_sqm": pd.to_numeric(sdf["AWATER"], errors="coerce"),
        "repr_lon": shapely.get_x(pts),
        "repr_lat": shapely.get_y(pts),
        "geometry_wkb": shapely.to_wkb(geoms),
    }).sort_values("state_code").reset_index(drop=True)
    states_df.to_parquet(SILVER_DIR / "reference_states.parquet", index=False)

    # 2. Counties
    county_zip = RAW_DATA_ROOT / "reference/cb_2025_us_county_500k.zip"
    _, cdf, raw_cgeoms = read_ogr_table(f"/vsizip/{county_zip.as_posix()}")
    cgeoms = shapely.make_valid(raw_cgeoms)
    cpts = shapely.point_on_surface(cgeoms)
    counties_df = pd.DataFrame({
        "county_fips": cdf["GEOID"].astype(str).str.zfill(5),
        "state_fips": cdf["STATEFP"].astype(str).str.zfill(2),
        "state_code": cdf["STUSPS"].astype(str).str.upper(),
        "state_name": cdf["STATE_NAME"].astype(str),
        "county_name": cdf["NAME"].astype(str),
        "county_namelsad": cdf["NAMELSAD"].astype(str),
        "county_name_norm": [normalize_county_name(n) for n in cdf["NAME"]],
        "aland_sqm": pd.to_numeric(cdf["ALAND"], errors="coerce"),
        "awater_sqm": pd.to_numeric(cdf["AWATER"], errors="coerce"),
        "repr_lon": shapely.get_x(cpts),
        "repr_lat": shapely.get_y(cpts),
        "geometry_wkb": shapely.to_wkb(cgeoms),
    }).sort_values("county_fips").reset_index(drop=True)
    counties_df.to_parquet(SILVER_DIR / "reference_counties.parquet", index=False)

    print(f"Reference geographies built: {len(states_df)} states/territories, {len(counties_df)} counties.")
    return states_df, counties_df


def build_federal_registries(counties_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Extract and deduplicate canonical federal utility registries and county-level associations."""
    # Build (state_code, county_name_norm) -> county_fips lookup
    county_lookup = {}
    for row in counties_df.itertuples(index=False):
        county_lookup[(row.state_code, row.county_name_norm)] = (row.county_fips, row.county_name)
        county_lookup[(row.state_code, normalize_county_name(row.county_namelsad))] = (row.county_fips, row.county_name)

    def resolve_county_fips(state_code: str | None, raw_county: object) -> tuple[str | None, str | None]:
        if not state_code or raw_county is None:
            return None, None
        cnorm = normalize_county_name(raw_county)
        if not cnorm:
            return None, None
        hit = county_lookup.get((state_code, cnorm))
        if hit:
            return hit
        # Try stripping spaces or common variants (e.g. DE KALB -> DEKALB, LA SALLE -> LASALLE)
        nospace = cnorm.replace(" ", "")
        for (st, k), val in county_lookup.items():
            if st == state_code and k.replace(" ", "") == nospace:
                return val
        return None, str(raw_county).strip()

    org_rows = []
    sys_rows = []
    county_assoc_rows = []

    # -------------------------------------------------------------------------
    # 1. EIA-861 (2025 Electric Utilities, Sales/Customers, and County Service Territory)
    # -------------------------------------------------------------------------
    with zipfile.ZipFile(RAW_DATA_ROOT / "electric/eia861_2025.zip") as zf:
        with zf.open("Frame_2025.xlsx") as f:
            frame_df = pd.read_excel(f, sheet_name="Frame")
        with zf.open("Sales_Ult_Cust_2025.xlsx") as f:
            sales_xl = pd.ExcelFile(f)
            sales_parts = []
            for sname in sales_xl.sheet_names:
                sdf = sales_xl.parse(sname, skiprows=2)
                sales_parts.append(sdf)
            sales_df = pd.concat(sales_parts, ignore_index=True)
        with zf.open("Service_Territory_2025.xlsx") as f:
            st_xl = pd.ExcelFile(f)
            terr_df = pd.concat([st_xl.parse(s) for s in st_xl.sheet_names], ignore_index=True)

    # Aggregate sales & customers by (Utility Number, State)
    sales_df["Utility Number"] = pd.to_numeric(sales_df.get("Utility Number"), errors="coerce")
    # Identify total customers & MWh columns in Sales_Ult_Cust_2025
    cust_col = next((c for c in sales_df.columns if "Customers.4" in str(c) or str(c).strip() == "Customers.4"), None)
    sales_col = next((c for c in sales_df.columns if "Sales.4" in str(c) or str(c).strip() == "Sales.4"), None)
    rev_col = next((c for c in sales_df.columns if "Revenues.4" in str(c) or str(c).strip() == "Revenues.4"), None)

    sales_by_util = {}
    if cust_col:
        for row in sales_df.dropna(subset=["Utility Number"]).itertuples(index=False):
            uid = int(getattr(row, "_1", row[1])) if hasattr(row, "_1") else int(row[1])
            st = normalize_state_code(row[3])
            cval = pd.to_numeric(getattr(row, cust_col, None), errors="coerce")
            sval = pd.to_numeric(getattr(row, sales_col, None), errors="coerce") if sales_col else np.nan
            if uid not in sales_by_util:
                sales_by_util[uid] = {"state": st, "customers": 0.0, "sales_mwh": 0.0}
            if pd.notna(cval):
                sales_by_util[uid]["customers"] += float(cval)
            if pd.notna(sval):
                sales_by_util[uid]["sales_mwh"] += float(sval)
            if st and not sales_by_util[uid]["state"]:
                sales_by_util[uid]["state"] = st

    # Primary state from Service_Territory_2025
    terr_state_by_util = {}
    for row in terr_df.itertuples(index=False):
        uid = pd.to_numeric(getattr(row, "_1", None), errors="coerce")
        st = normalize_state_code(getattr(row, "State", None))
        if pd.notna(uid) and st:
            terr_state_by_util.setdefault(int(uid), st)

    seen_eia_utils = set()
    for row in frame_df.itertuples(index=False):
        uid_num = pd.to_numeric(row[1], errors="coerce")
        if pd.isna(uid_num):
            continue
        uid = int(uid_num)
        seen_eia_utils.add(uid)
        uname = str(row[2]).strip()
        ownership = str(row[5]).strip() if pd.notna(row[5]) else "Unknown"
        # Extract state from name suffix like "- (SC)" or territory lookup
        st = None
        if "(" in uname and uname.endswith(")"):
            cand = uname.rsplit("(", 1)[-1].rstrip(")").strip()
            st = normalize_state_code(cand)
        if not st:
            st = sales_by_util.get(uid, {}).get("state") or terr_state_by_util.get(uid)

        sinfo = sales_by_util.get(uid, {})
        org_id = f"ORG_EIA_{uid}"
        sys_id = f"SYS_EIA_{uid}_{st or 'US'}"
        org_rows.append({
            "org_id": org_id,
            "canonical_name": uname,
            "name_norm": normalize_entity_name(uname),
            "name_core": normalize_entity_name(uname, strip_utility_terms=True),
            "primary_sector": "electric",
            "ownership_type": ownership,
            "state_code": st,
            "eia_utility_id": str(uid),
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "phmsa_operator_id": None,
            "ferc_cid": None,
            "source_id": "federal_eia861_2025",
        })
        sys_rows.append({
            "system_id": sys_id,
            "org_id": org_id,
            "system_name": uname,
            "name_norm": normalize_entity_name(uname),
            "name_core": normalize_entity_name(uname, strip_utility_terms=True),
            "sector": "electric",
            "state_code": st,
            "ownership_type": ownership,
            "activity_status": "Active",
            "population_served": None,
            "service_connections": int(sinfo["customers"]) if sinfo.get("customers") else None,
            "sales_mwh": sinfo.get("sales_mwh") or None,
            "eia_utility_id": str(uid),
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "phmsa_operator_id": None,
            "source_id": "federal_eia861_2025",
        })

    # Add EIA-861 County Service Territory records
    for row in terr_df.itertuples(index=False):
        uid_num = pd.to_numeric(row[1], errors="coerce")
        if pd.isna(uid_num):
            continue
        uid = int(uid_num)
        uname = str(row[2]).strip()
        st = normalize_state_code(row[4])
        raw_cnty = row[5]
        cfips, cname = resolve_county_fips(st, raw_cnty)
        county_assoc_rows.append({
            "assoc_id": deterministic_id("CA_EIA861", uid, st, cfips or raw_cnty),
            "source_id": "federal_eia861_2025",
            "sector": "electric",
            "state_code": st,
            "county_fips": cfips,
            "county_name": cname or str(raw_cnty).strip(),
            "community_name": None,
            "raw_provider_name": uname,
            "provider_name_norm": normalize_entity_name(uname),
            "org_id": f"ORG_EIA_{uid}",
            "system_id": f"SYS_EIA_{uid}_{st or 'US'}",
            "eia_utility_id": str(uid),
            "pwsid": None,
            "cwns_id": None,
            "authority_tier": 5,
            "association_method": "eia861_reported_county_presence",
        })

    # -------------------------------------------------------------------------
    # 2. EIA-860 (2025 Generator/Plant Operators not already in EIA-861 Frame)
    # -------------------------------------------------------------------------
    with zipfile.ZipFile(RAW_DATA_ROOT / "electric/eia860_2025.zip") as zf:
        with zf.open("1___Utility_Y2025.xlsx") as f:
            u860_df = pd.read_excel(f, sheet_name="Utility", skiprows=1)
    for row in u860_df.itertuples(index=False):
        uid_num = pd.to_numeric(row[0], errors="coerce")
        if pd.isna(uid_num):
            continue
        uid = int(uid_num)
        if uid in seen_eia_utils:
            continue
        seen_eia_utils.add(uid)
        uname = str(row[1]).strip()
        st = normalize_state_code(row[4])
        etype = str(row[10]).strip() if len(row) > 10 and pd.notna(row[10]) else "Generator Operator"
        org_id = f"ORG_EIA_{uid}"
        org_rows.append({
            "org_id": org_id,
            "canonical_name": uname,
            "name_norm": normalize_entity_name(uname),
            "name_core": normalize_entity_name(uname, strip_utility_terms=True),
            "primary_sector": "electric",
            "ownership_type": etype,
            "state_code": st,
            "eia_utility_id": str(uid),
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "phmsa_operator_id": None,
            "ferc_cid": None,
            "source_id": "federal_eia860_2025",
        })

    # -------------------------------------------------------------------------
    # 3. EPA SDWIS Public Water Systems & Geographic Areas (2026Q3)
    # -------------------------------------------------------------------------
    with zipfile.ZipFile(RAW_DATA_ROOT / "water/epa_sdwa_latest.zip") as zf:
        with zf.open("SDWA_PUB_WATER_SYSTEMS.csv") as f:
            pws_df = pd.read_csv(
                f,
                usecols=[
                    "PWSID", "PWS_NAME", "PRIMACY_AGENCY_CODE", "STATE_CODE",
                    "PWS_ACTIVITY_CODE", "PWS_TYPE_CODE", "OWNER_TYPE_CODE",
                    "POPULATION_SERVED_COUNT", "SERVICE_CONNECTIONS_COUNT",
                    "ORG_NAME", "CITY_NAME",
                ],
                low_memory=False,
                encoding_errors="replace",
            )
        with zf.open("SDWA_GEOGRAPHIC_AREAS.csv") as f:
            geo_df = pd.read_csv(
                f,
                usecols=["PWSID", "AREA_TYPE_CODE", "STATE_SERVED", "COUNTY_SERVED", "CITY_SERVED"],
                low_memory=False,
                encoding_errors="replace",
            )

    owner_map = {
        "L": "Local Government",
        "P": "Private",
        "M": "Public/Private",
        "F": "Federal Government",
        "S": "State Government",
        "N": "Native American",
    }
    pws_name_lookup = {}
    pws_state_lookup = {}
    for row in pws_df.itertuples(index=False):
        pwsid = normalize_pwsid(row.PWSID)
        if not pwsid:
            continue
        pname = str(row.PWS_NAME).strip() if pd.notna(row.PWS_NAME) else pwsid
        st = normalize_state_code(row.STATE_CODE) or normalize_state_code(row.PRIMACY_AGENCY_CODE) or pwsid[:2]
        act = "Active" if str(row.PWS_ACTIVITY_CODE).strip() == "A" else "Inactive"
        otype = owner_map.get(str(row.OWNER_TYPE_CODE).strip(), "Unknown")
        pop = pd.to_numeric(row.POPULATION_SERVED_COUNT, errors="coerce")
        conn = pd.to_numeric(row.SERVICE_CONNECTIONS_COUNT, errors="coerce")
        pws_name_lookup[pwsid] = pname
        pws_state_lookup[pwsid] = st
        org_id = f"ORG_PWS_{pwsid}"
        sys_id = f"SYS_PWS_{pwsid}"
        # Keep active systems or community systems in the canonical spine
        if act == "Active" or str(row.PWS_TYPE_CODE).strip() == "CWS":
            org_rows.append({
                "org_id": org_id,
                "canonical_name": pname,
                "name_norm": normalize_entity_name(pname),
                "name_core": normalize_entity_name(pname, strip_utility_terms=True),
                "primary_sector": "water",
                "ownership_type": otype,
                "state_code": st,
                "eia_utility_id": None,
                "pwsid": pwsid,
                "npdes_id": None,
                "cwns_id": None,
                "phmsa_operator_id": None,
                "ferc_cid": None,
                "source_id": "federal_epa_sdwa_2026q3",
            })
            sys_rows.append({
                "system_id": sys_id,
                "org_id": org_id,
                "system_name": pname,
                "name_norm": normalize_entity_name(pname),
                "name_core": normalize_entity_name(pname, strip_utility_terms=True),
                "sector": "water",
                "state_code": st,
                "ownership_type": otype,
                "activity_status": act,
                "population_served": int(pop) if pd.notna(pop) else None,
                "service_connections": int(conn) if pd.notna(conn) else None,
                "sales_mwh": None,
                "eia_utility_id": None,
                "pwsid": pwsid,
                "npdes_id": None,
                "cwns_id": None,
                "phmsa_operator_id": None,
                "source_id": "federal_epa_sdwa_2026q3",
            })

    # SDWA County Served associations
    cn_geo = geo_df[geo_df["COUNTY_SERVED"].notna()].drop_duplicates(subset=["PWSID", "COUNTY_SERVED"])
    for row in cn_geo.itertuples(index=False):
        pwsid = normalize_pwsid(row.PWSID)
        if not pwsid or pwsid not in pws_name_lookup:
            continue
        st = normalize_state_code(row.STATE_SERVED) or pws_state_lookup.get(pwsid)
        cfips, cname = resolve_county_fips(st, row.COUNTY_SERVED)
        pname = pws_name_lookup[pwsid]
        county_assoc_rows.append({
            "assoc_id": deterministic_id("CA_SDWA", pwsid, cfips or row.COUNTY_SERVED),
            "source_id": "federal_epa_sdwa_2026q3",
            "sector": "water",
            "state_code": st,
            "county_fips": cfips,
            "county_name": cname or str(row.COUNTY_SERVED).strip(),
            "community_name": str(row.CITY_SERVED).strip() if pd.notna(row.CITY_SERVED) else None,
            "raw_provider_name": pname,
            "provider_name_norm": normalize_entity_name(pname),
            "org_id": f"ORG_PWS_{pwsid}",
            "system_id": f"SYS_PWS_{pwsid}",
            "eia_utility_id": None,
            "pwsid": pwsid,
            "cwns_id": None,
            "authority_tier": 5,
            "association_method": "epa_sdwa_reported_county_served",
        })

    # -------------------------------------------------------------------------
    # 4. EPA CWNS 2022 & NPDES Wastewater Systems
    # -------------------------------------------------------------------------
    with zipfile.ZipFile(RAW_DATA_ROOT / "wastewater/epa_cwns_2022_national_sept2026.zip") as zf:
        with zf.open("2022CWNS_NATIONAL_Sept2026/FACILITIES.csv") as f:
            cwns_fac = pd.read_csv(f, low_memory=False, encoding_errors="replace")
        with zf.open("2022CWNS_NATIONAL_Sept2026/FACILITY_PERMIT.csv") as f:
            cwns_perm = pd.read_csv(f, low_memory=False, encoding_errors="replace")
        with zf.open("2022CWNS_NATIONAL_Sept2026/POPULATION_WASTEWATER.csv") as f:
            cwns_pop = pd.read_csv(f, low_memory=False, encoding_errors="replace")
        with zf.open("2022CWNS_NATIONAL_Sept2026/AREAS_COUNTY.csv") as f:
            cwns_cnty = pd.read_csv(f, low_memory=False, encoding_errors="replace")

    npdes_by_cwns = {}
    for row in cwns_perm.itertuples(index=False):
        if str(row.PERMIT_SOURCE).upper() == "NPDES" and pd.notna(row.PERMIT_NUMBER):
            npdes_by_cwns.setdefault(str(row.CWNS_ID), str(row.PERMIT_NUMBER).strip().upper())

    pop_by_cwns = {}
    pop_col = next((c for c in cwns_pop.columns if "RES" in c.upper() or "POP" in c.upper() and c != "CWNS_ID" and c != "FACILITY_ID"), None)
    if pop_col:
        for row in cwns_pop.itertuples(index=False):
            pval = pd.to_numeric(getattr(row, pop_col, None), errors="coerce")
            if pd.notna(pval):
                pop_by_cwns[str(row.CWNS_ID)] = int(pval)

    cwns_name_lookup = {}
    for row in cwns_fac.itertuples(index=False):
        cid = str(row.CWNS_ID).strip()
        fname = str(row.FACILITY_NAME).strip() if pd.notna(row.FACILITY_NAME) else cid
        st = normalize_state_code(row.STATE_CODE)
        itype = str(row.INFRASTRUCTURE_TYPE).strip() if pd.notna(row.INFRASTRUCTURE_TYPE) else "Wastewater"
        sec = "stormwater" if "STORM" in itype.upper() else "wastewater"
        npdes = npdes_by_cwns.get(cid)
        cwns_name_lookup[cid] = (fname, st, sec, npdes)
        org_id = f"ORG_CWNS_{cid}"
        sys_id = f"SYS_CWNS_{cid}"
        org_rows.append({
            "org_id": org_id,
            "canonical_name": fname,
            "name_norm": normalize_entity_name(fname),
            "name_core": normalize_entity_name(fname, strip_utility_terms=True),
            "primary_sector": sec,
            "ownership_type": str(row.OWNER_TYPE).strip() if pd.notna(row.OWNER_TYPE) else "Public",
            "state_code": st,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": npdes,
            "cwns_id": cid,
            "phmsa_operator_id": None,
            "ferc_cid": None,
            "source_id": "federal_epa_cwns_2022",
        })
        sys_rows.append({
            "system_id": sys_id,
            "org_id": org_id,
            "system_name": fname,
            "name_norm": normalize_entity_name(fname),
            "name_core": normalize_entity_name(fname, strip_utility_terms=True),
            "sector": sec,
            "state_code": st,
            "ownership_type": str(row.OWNER_TYPE).strip() if pd.notna(row.OWNER_TYPE) else "Public",
            "activity_status": "Active",
            "population_served": pop_by_cwns.get(cid),
            "service_connections": None,
            "sales_mwh": None,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": npdes,
            "cwns_id": cid,
            "phmsa_operator_id": None,
            "source_id": "federal_epa_cwns_2022",
        })

    for row in cwns_cnty.drop_duplicates(subset=["CWNS_ID", "COUNTY_FIPS"]).itertuples(index=False):
        cid = str(row.CWNS_ID).strip()
        if cid not in cwns_name_lookup:
            continue
        fname, st, sec, _ = cwns_name_lookup[cid]
        cfips = str(int(row.COUNTY_FIPS)).zfill(5) if pd.notna(row.COUNTY_FIPS) else None
        cname = str(row.COUNTY_NAME).strip() if pd.notna(row.COUNTY_NAME) else None
        county_assoc_rows.append({
            "assoc_id": deterministic_id("CA_CWNS", cid, cfips or cname),
            "source_id": "federal_epa_cwns_2022",
            "sector": sec,
            "state_code": st,
            "county_fips": cfips,
            "county_name": cname,
            "community_name": None,
            "raw_provider_name": fname,
            "provider_name_norm": normalize_entity_name(fname),
            "org_id": f"ORG_CWNS_{cid}",
            "system_id": f"SYS_CWNS_{cid}",
            "eia_utility_id": None,
            "pwsid": None,
            "cwns_id": cid,
            "authority_tier": 5,
            "association_method": "epa_cwns_reported_county",
        })

    # -------------------------------------------------------------------------
    # 5. PHMSA Natural Gas Distribution & Transmission Operators (2025) + EIA-176
    # -------------------------------------------------------------------------
    seen_phmsa = set()
    with zipfile.ZipFile(RAW_DATA_ROOT / "gas/phmsa_zenodo_23296837/phmsagas_gas_distribution_2010_present.zip") as zf:
        with zf.open("GD AR 2025.csv") as f:
            gd_df = pd.read_csv(
                f,
                usecols=[
                    "OPERATOR_ID", "OPERATOR_NAME", "OFFICE_ADDRESS_STATE",
                    "HQ_ADDRESS_STATE", "OPERATOR_TYPE", "MMILES_TOTAL", "NUM_SRVCS_TOTAL",
                ],
                low_memory=False,
                encoding_errors="replace",
            )
    for row in gd_df.drop_duplicates(subset=["OPERATOR_ID", "OFFICE_ADDRESS_STATE"]).itertuples(index=False):
        op_num = pd.to_numeric(row.OPERATOR_ID, errors="coerce")
        if pd.isna(op_num):
            continue
        op_id = str(int(op_num))
        oname = str(row.OPERATOR_NAME).strip()
        st = normalize_state_code(row.OFFICE_ADDRESS_STATE) or normalize_state_code(row.HQ_ADDRESS_STATE)
        otype = str(row.OPERATOR_TYPE).strip() if pd.notna(row.OPERATOR_TYPE) else "Gas Distribution"
        srvcs = pd.to_numeric(row.NUM_SRVCS_TOTAL, errors="coerce")
        org_id = f"ORG_PHMSA_{op_id}"
        if op_id not in seen_phmsa:
            seen_phmsa.add(op_id)
            org_rows.append({
                "org_id": org_id,
                "canonical_name": oname,
                "name_norm": normalize_entity_name(oname),
                "name_core": normalize_entity_name(oname, strip_utility_terms=True),
                "primary_sector": "natural_gas",
                "ownership_type": otype,
                "state_code": st,
                "eia_utility_id": None,
                "pwsid": None,
                "npdes_id": None,
                "cwns_id": None,
                "phmsa_operator_id": op_id,
                "ferc_cid": None,
                "source_id": "federal_phmsa_gas_distribution_2025",
            })
        sys_rows.append({
            "system_id": f"SYS_PHMSA_GD_{op_id}_{st or 'US'}",
            "org_id": org_id,
            "system_name": oname,
            "name_norm": normalize_entity_name(oname),
            "name_core": normalize_entity_name(oname, strip_utility_terms=True),
            "sector": "natural_gas",
            "state_code": st,
            "ownership_type": otype,
            "activity_status": "Active",
            "population_served": None,
            "service_connections": int(srvcs) if pd.notna(srvcs) else None,
            "sales_mwh": None,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "phmsa_operator_id": op_id,
            "source_id": "federal_phmsa_gas_distribution_2025",
        })

    with zipfile.ZipFile(RAW_DATA_ROOT / "gas/phmsa_zenodo_23296837/phmsagas_gas_transmission_gathering_2010_present.zip") as zf:
        with zf.open("GT AR 2025 Part A to D.csv") as f:
            gt_df = pd.read_csv(
                f,
                usecols=["OPERATOR_ID", "PARTA2NAMEOFCOMP", "PARTA4STATE", "PARTA5COMMODITY"],
                low_memory=False,
                encoding_errors="replace",
            )
    for row in gt_df.drop_duplicates(subset=["OPERATOR_ID"]).itertuples(index=False):
        op_num = pd.to_numeric(row.OPERATOR_ID, errors="coerce")
        if pd.isna(op_num):
            continue
        op_id = str(int(op_num))
        if op_id in seen_phmsa:
            continue
        seen_phmsa.add(op_id)
        oname = str(row.PARTA2NAMEOFCOMP).strip()
        st = normalize_state_code(row.PARTA4STATE)
        org_rows.append({
            "org_id": f"ORG_PHMSA_{op_id}",
            "canonical_name": oname,
            "name_norm": normalize_entity_name(oname),
            "name_core": normalize_entity_name(oname, strip_utility_terms=True),
            "primary_sector": "natural_gas",
            "ownership_type": "Pipeline Operator",
            "state_code": st,
            "eia_utility_id": None,
            "pwsid": None,
            "npdes_id": None,
            "cwns_id": None,
            "phmsa_operator_id": op_id,
            "ferc_cid": None,
            "source_id": "federal_phmsa_gas_transmission_2025",
        })

    # -------------------------------------------------------------------------
    # 6. Florida PSC 67-County Lookup JSONs & Missouri PSC Community Lookup CSV
    # -------------------------------------------------------------------------
    fl_dir = RAW_DATA_ROOT / "states/fl/psc_county_lookup"
    fl_manifest = json.loads((fl_dir / "manifest.json").read_text(encoding="utf-8"))
    ind_map = {1: "electric", 2: "natural_gas", 3: "water"}
    for resp in fl_manifest.get("responses", []):
        if resp.get("status") != "downloaded" or resp.get("result_was_null"):
            continue
        cnty = resp["county"]
        sec = ind_map.get(int(resp["industry_code"]), "multi_utility")
        cfips, cname = resolve_county_fips("FL", cnty)
        jdata = json.loads((RAW_DATA_ROOT.parent / resp["path"]).read_text(encoding="utf-8"))
        for rec in jdata.get("result") or []:
            uname = str(rec.get("utilityName") or rec.get("utilityLongname") or "").strip()
            ucode = str(rec.get("utilityCode") or "").strip()
            if not uname:
                continue
            county_assoc_rows.append({
                "assoc_id": deterministic_id("CA_FLPSC", cfips or cnty, sec, ucode or uname),
                "source_id": "state_fl_psc_county_lookup",
                "sector": sec,
                "state_code": "FL",
                "county_fips": cfips,
                "county_name": cname or cnty,
                "community_name": None,
                "raw_provider_name": uname,
                "provider_name_norm": normalize_entity_name(uname),
                "org_id": None,
                "system_id": None,
                "eia_utility_id": None,
                "pwsid": None,
                "cwns_id": None,
                "authority_tier": 5,
                "association_method": "fl_psc_county_lookup",
            })

    mo_path = RAW_DATA_ROOT / "states/mo/missouri_utility_lookup_historical.csv"
    if mo_path.exists():
        mo_df = pd.read_csv(mo_path, low_memory=False)
        for row in mo_df.itertuples(index=False):
            cfips, cname = resolve_county_fips("MO", getattr(row, "county", None))
            city = str(getattr(row, "city", "")).strip() if pd.notna(getattr(row, "city", None)) else None
            for col, sec in [("electric", "electric"), ("gas", "natural_gas"), ("water", "water")]:
                val = getattr(row, col, None)
                if pd.notna(val) and str(val).strip():
                    uname = str(val).strip()
                    county_assoc_rows.append({
                        "assoc_id": deterministic_id("CA_MOPSC", cfips or cname, city, sec, uname),
                        "source_id": "state_mo_psc_utility_lookup",
                        "sector": sec,
                        "state_code": "MO",
                        "county_fips": cfips,
                        "county_name": cname,
                        "community_name": city,
                        "raw_provider_name": uname,
                        "provider_name_norm": normalize_entity_name(uname),
                        "org_id": None,
                        "system_id": None,
                        "eia_utility_id": None,
                        "pwsid": None,
                        "cwns_id": None,
                        "authority_tier": 5,
                        "association_method": "mo_psc_community_lookup",
                    })

    orgs_df = pd.DataFrame(org_rows).drop_duplicates(subset=["org_id"]).reset_index(drop=True)
    systems_df = pd.DataFrame(sys_rows).drop_duplicates(subset=["system_id"]).reset_index(drop=True)
    county_assoc_df = pd.DataFrame(county_assoc_rows).drop_duplicates(subset=["assoc_id"]).reset_index(drop=True)

    orgs_df.to_parquet(SILVER_DIR / "federal_organizations_spine.parquet", index=False)
    systems_df.to_parquet(SILVER_DIR / "federal_systems_spine.parquet", index=False)
    county_assoc_df.to_parquet(SILVER_DIR / "county_utility_associations.parquet", index=False)

    print(
        f"Federal spine & county associations built: "
        f"{len(orgs_df)} organizations, {len(systems_df)} systems, "
        f"{len(county_assoc_df)} county/community service associations."
    )
    return orgs_df, systems_df, county_assoc_df


if __name__ == "__main__":
    _, counties = build_reference_geographies()
    build_federal_registries(counties)
