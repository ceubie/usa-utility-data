"""Gold table rules that do not need the national build."""

from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely

from utilitydata.gold.coverage import (
    build_coverage,
    is_served,
    require_shares_at_most_one,
)
from utilitydata.gold.display import append_sector_display, write_display
from utilitydata.gold.facilities import build_compliance
from utilitydata.gold.search import build_entity_search, north_st_paul_status
from utilitydata.gold.tabular import classify_sdwa_geography
from utilitydata.gold.text import county_name_key, place_name_key, search_norm

STATES = pd.DataFrame({
    "state": ["17", "48", "09", "22", "35"],
    "usps": ["IL", "TX", "CT", "LA", "NM"],
})
COUNTIES = pd.DataFrame({
    "county_geoid": ["17097", "48453", "22103", "09170", "35013"],
    "state": ["17", "48", "22", "09", "35"],
    "name": ["Lake", "Travis", "St. Tammany", "Lower Connecticut River Valley", "Doña Ana"],
})
PLACES = pd.DataFrame({
    "place_geoid": ["1758000", "1758001", "1758002"],
    "state": ["17", "17", "17"],
    "name": ["St. Paul", "Springfield", "Springfield"],
})
ALIAS = pd.DataFrame({
    "old_county_geoid": ["09001", "09001", "09007"],
    "old_county_name": ["Fairfield County", "Fairfield County", "Middlesex County"],
    "county_geoid": ["09110", "09120", "09170"],
    "county_name": ["Capitol", "Greater Bridgeport", "Lower Connecticut River Valley"],
})


def _systems() -> pd.DataFrame:
    rows = [
        ("SYS_PWS_IL0970500", "IL0970500", "active", "IL"),
        ("SYS_PWS_TX2270001", "TX2270001", "active", "TX"),
        ("SYS_PWS_LA1051001", "LA1051001", "active", "LA"),
        ("SYS_PWS_CT0010001", "CT0010001", "active", "CT"),
        ("SYS_PWS_090070001", "090070001", "active", "CT"),
        ("SYS_PWS_NM0130001", "NM0130001", "active", "NM"),
        ("SYS_PWS_IL0970999", "IL0970999", "inactive", "IL"),
        ("SYS_PWS_IL0970501", "IL0970501", "active", "IL"),
    ]
    return pd.DataFrame(rows, columns=["system_id", "pwsid", "status", "primary_state"]).assign(
        sector="water",
        in_federal_registry=True,
    )


def _geo(rows: list[tuple]) -> pd.DataFrame:
    columns = ["PWSID", "AREA_TYPE_CODE", "ANSI_ENTITY_CODE", "COUNTY_SERVED", "CITY_SERVED", "STATE_SERVED"]
    return pd.DataFrame(rows, columns=columns)


def test_north_st_paul_spellings_share_a_search_key():
    codes = {"mn", "tx"}
    left = search_norm("North St. Paul", state_codes=codes)
    right = search_norm("CITY OF NORTH ST PAUL - (MN)", state_codes=codes)
    assert left == right == "north st paul"
    assert left != search_norm("North Saint Paul", state_codes=codes)


def test_county_and_place_name_keys_drop_only_the_jurisdiction_word():
    assert county_name_key("St. Tammany Parish") == "st tammany"
    assert county_name_key("Doña Ana") == "dona ana"
    assert county_name_key("Matanuska-Susitna Borough") == "matanuska susitna"
    assert county_name_key("Bethel Census Area") == "bethel"
    assert place_name_key("St. Paul") == "st paul"
    assert place_name_key("Lake City") == "lake city"


def test_geography_links_resolve_counties_and_record_every_other_row():
    geographic = _geo([
        ("IL0970500", "CN", "097", "Lake", None, None),
        ("TX2270001", "CN", "453", "Travis", None, None),
        ("LA1051001", "CN", "103", "St. Tammany Parish", None, None),
        ("NM0130001", "CN", "013", "Dona Ana", None, None),
        ("CT0010001", "CN", "001", "Fairfield", None, None),
        ("090070001", "CN", "007", "Middlesex", None, None),
        ("IL0970999", "CN", "097", "Lake", None, None),
        ("IL0970501", "CN", "097", "Cook", None, None),
        ("IL0970500", "CN", "999", "Nowhere", None, None),
        ("IL0970500", "CT", None, None, "ST. PAUL", "IL"),
        ("IL0970500", "CT", None, None, "SPRINGFIELD", "IL"),
        ("IL0970500", "ZC", None, None, None, None),
    ])
    counties, places, unresolved, _counts = classify_sdwa_geography(
        geographic, _systems(), STATES, COUNTIES, PLACES, ALIAS,
    )
    resolved = set(zip(counties["system_id"], counties["county_geoid"], strict=True))
    assert ("SYS_PWS_IL0970500", "17097") in resolved
    assert ("SYS_PWS_TX2270001", "48453") in resolved
    assert ("SYS_PWS_LA1051001", "22103") in resolved
    assert ("SYS_PWS_NM0130001", "35013") in resolved
    assert ("SYS_PWS_090070001", "09170") in resolved
    assert "09001" not in set(counties["county_geoid"])
    assert set(places["place_geoid"]) == {"1758000"}
    assert set(unresolved["reason"]) == {
        "ambiguous_planning_region",
        "not_active",
        "county_name_disagrees",
        "county_not_in_reference",
        "ambiguous_place_name",
        "area_type_not_county_place_or_tract",
    }
    assert len(counties) + len(places) + len(unresolved) == len(geographic)


def test_served_rule_uses_the_configured_thresholds():
    assert is_served(0.01, 0) is True
    assert is_served(0.009, 99) is False
    assert is_served(None, 100) is True
    assert is_served(pd.NA, 0) is False


def test_a_share_above_one_is_rejected():
    frame = pd.DataFrame({"pop_share_of_county": [1.0, 1.01]})
    with pytest.raises(ValueError, match="exceeds 1"):
        require_shares_at_most_one(frame, ("pop_share_of_county",), "county")


def test_block_internal_point_assigns_only_the_active_serving_area(tmp_path: Path):
    root = tmp_path
    active = shapely.box(0, 0, 1, 1)
    inactive = shapely.box(2, 2, 3, 3)
    areas = gpd.GeoDataFrame(
        {
            "service_area_id": ["SA_IN", "SA_OFF"],
            "system_id": ["SYS_PWS_IN", "SYS_PWS_OFF"],
            "sector": ["water", "water"],
            "zone_role": ["active_retail_service", "active_retail_service"],
            "source_id": ["src", "src"],
            "authority": ["state_regulator", "state_regulator"],
            "grain": ["service_area", "service_area"],
            "source_vintage_date": [None, None],
            "is_best": [True, True],
            "part_count": [1, 1],
            "area_km2": [1.0, 1.0],
            "footprint_verified": [True, True],
            "licence": ["unknown", "unknown"],
        },
        geometry=[active, inactive],
        crs="EPSG:4326",
    )
    areas.to_parquet(root / "service_area.parquet", index=False)
    pd.DataFrame({
        "system_id": ["SYS_PWS_IN", "SYS_PWS_OFF"],
        "name": ["Inside", "Outside"],
        "sector": ["water", "water"],
        "status": ["active", "inactive"],
        "primary_state": ["IL", "IL"],
        "in_federal_registry": [True, True],
        "population_served": [40, 50],
    }).to_parquet(root / "system.parquet", index=False)
    pd.DataFrame({
        "block_geoid": ["B_IN", "B_OUT", "B_OFF"],
        "state": ["17", "17", "17"],
        "county_geoid": ["17097", "17097", "17097"],
        "tract_geoid": ["17097000001", "17097000001", "17097000001"],
        "place_geoid": [None, None, None],
        "pop20": [40, 60, 50],
        "housing20": [10, 20, 15],
        "aland20": [10, 20, 15],
        "lat": [0.5, 5.0, 2.5],
        "lon": [0.5, 5.0, 2.5],
    }).to_parquet(root / "ref_block.parquet", index=False)
    pd.DataFrame({"source_id": ["src"], "boundary_representation": ["unknown"]}).to_parquet(root / "assertion.parquet", index=False)
    pd.DataFrame(columns=["PWSID", "AREA_TYPE_CODE", "ANSI_ENTITY_CODE", "COUNTY_SERVED", "CITY_SERVED", "STATE_SERVED"]).to_parquet(root / "geo.parquet", index=False)
    pd.DataFrame({"state": ["17"], "usps": ["IL"], "pop20": [150]}).to_parquet(root / "state.parquet", index=False)
    pd.DataFrame({"county_geoid": ["17097"], "state": ["17"], "name": ["Lake"], "pop20": [150]}).to_parquet(root / "county.parquet", index=False)
    pd.DataFrame({"place_geoid": ["1758000"], "state": ["17"], "name": ["St. Paul"], "pop20": [0]}).to_parquet(root / "place.parquet", index=False)
    pd.DataFrame(columns=["old_county_geoid", "old_county_name", "county_geoid", "county_name"]).to_parquet(root / "alias.parquet", index=False)
    pd.DataFrame({"system_id": ["SYS_PWS_IN", "SYS_PWS_OFF"], "scheme": ["pwsid", "pwsid"], "value": ["IN", "OFF"]}).to_parquet(root / "identifier.parquet", index=False)
    summary = build_coverage(
        service_areas=root / "service_area.parquet",
        systems=root / "system.parquet",
        blocks=root / "ref_block.parquet",
        assertions=root / "assertion.parquet",
        geographic=root / "geo.parquet",
        states=root / "state.parquet",
        counties=root / "county.parquet",
        places=root / "place.parquet",
        alias=root / "alias.parquet",
        identifiers=root / "identifier.parquet",
        output=root / "out",
        work=root / "work",
        sdwa_licence="unknown",
        sdwa_source_id="federal_epa_sdwa",
    )
    hits = pd.read_parquet(root / "out" / "system_block_coverage.parquet")
    assert hits["block_geoid"].tolist() == ["B_IN"]
    assert hits["system_id"].tolist() == ["SYS_PWS_IN"]
    county = pd.read_parquet(root / "out" / "system_county_coverage.parquet")
    assert county["system_id"].tolist() == ["SYS_PWS_IN"]
    assert county["pop_in_area"].tolist() == [40]
    assert county["is_served"].tolist() == [True]
    assert float(county["pop_share_of_county"].iloc[0]) <= 1
    assert summary["travis_county_served_systems"] == 0
    assert "SYS_PWS_OFF" not in set(hits["system_id"])
    assert "SYS_PWS_OFF" not in set(county["system_id"])


def test_both_north_st_paul_labels_resolve_to_one_system():
    systems = pd.DataFrame({
        "system_id": ["SYS_PWS_MN"],
        "name": ["CITY OF NORTH ST PAUL - (MN)"],
        "primary_state": ["MN"],
        "in_federal_registry": [True],
        "owner_org_id": [pd.NA],
    })
    identifiers = pd.DataFrame({
        "system_id": ["SYS_PWS_MN"],
        "scheme": ["pwsid"],
        "value": ["MN1234567"],
        "source_id": ["sdwa"],
    })
    assertions = pd.DataFrame({
        "system_id": ["SYS_PWS_MN"],
        "label": ["North St. Paul"],
        "licence": ["attribution_required"],
        "source_id": ["boundary"],
    })
    organizations = pd.DataFrame(columns=["org_id", "name", "source_id"])
    frame = build_entity_search(
        systems,
        identifiers,
        assertions,
        organizations,
        state_codes={"MN"},
        federal_licence="unknown",
        licence_by_source={"sdwa": "unknown", "boundary": "attribution_required"},
    )
    status = north_st_paul_status(frame, state_codes={"MN"})
    assert status["resolved_to_one_system"] is True
    assert status["entity_ids"] == ["SYS_PWS_MN"]
    only_city = frame.loc[frame["label"].ne("North St. Paul")]
    missing = north_st_paul_status(only_city, state_codes={"MN"})
    assert missing["resolved_to_one_system"] is None
    assert missing["missing_labels"] == ["North St. Paul"]


def test_open_ended_violation_token_is_not_counted_as_a_date(tmp_path: Path):
    table = pa.table({
        "SUBMISSIONYEARQUARTER": ["2026Q3", "2026Q3", "2026Q3", "2026Q3"],
        "PWSID": ["AAA", "AAA", "AAA", "BBB"],
        "VIOLATION_ID": ["1", "1", "2", None],
        "NON_COMPL_PER_BEGIN_DATE": [date(2024, 1, 1), date(2024, 1, 1), date(2010, 1, 1), None],
        "NON_COMPL_PER_END_DATE": [None, None, date(2010, 6, 1), None],
        "NON_COMPL_PER_END_DATE_unparsed": ["--->", "--->", None, None],
        "IS_HEALTH_BASED_IND": ["Y", "Y", "N", None],
    })
    path = tmp_path / "violations.parquet"
    pq.write_table(table, path)
    systems = pd.DataFrame({
        "system_id": ["SYS_PWS_AAA", "SYS_PWS_BBB"],
        "pwsid": ["AAA", "BBB"],
        "in_federal_registry": [True, True],
    })
    summary = build_compliance(
        path,
        systems,
        tmp_path / "compliance.parquet",
        licence="unknown",
        source_id="sdwa",
    )
    frame = pd.read_parquet(tmp_path / "compliance.parquet").set_index("system_id")
    assert summary["as_of_date"] == "2026-09-30"
    assert int(frame.loc["SYS_PWS_AAA", "violations_3y"]) == 1
    assert int(frame.loc["SYS_PWS_AAA", "violations_10y"]) == 1
    assert int(frame.loc["SYS_PWS_AAA", "open_violations"]) == 1
    assert int(frame.loc["SYS_PWS_AAA", "outside_10y"]) == 1
    assert int(frame.loc["SYS_PWS_AAA", "health_based_3y"]) == 1
    assert int(frame.loc["SYS_PWS_BBB", "violations_10y"]) == 0
    assert int(frame.loc["SYS_PWS_BBB", "enforcement_rows_without_violation"]) == 1


def test_append_sector_display_merges_without_dropping_other_sectors(tmp_path: Path):
    water = gpd.GeoDataFrame(
        {
            "service_area_id": ["SA_W1"],
            "system_id": ["SYS_PWS_1"],
            "sector": ["water"],
            "zone_role": ["active_retail_service"],
            "authority": ["state_regulator"],
            "licence": ["public_domain"],
        },
        geometry=[shapely.box(0, 0, 1, 1)],
        crs="EPSG:4326",
    )
    electric = gpd.GeoDataFrame(
        {
            "service_area_id": ["SA_E1"],
            "system_id": ["SYS_EIA_1"],
            "sector": ["electric"],
            "zone_role": ["active_retail_service"],
            "authority": ["state_regulator"],
            "licence": ["cc-by-4.0"],
        },
        geometry=[shapely.box(1, 1, 2, 2)],
        crs="EPSG:4326",
    )
    water_path = tmp_path / "water.parquet"
    display_path = tmp_path / "service_area_display.parquet"
    water.to_parquet(water_path, index=False)
    write_display(water_path, display_path)
    res = append_sector_display(electric, display_path)
    assert res["rows"] == 4
    combined = gpd.read_parquet(display_path)
    assert set(combined["sector"]) == {"water", "electric"}
