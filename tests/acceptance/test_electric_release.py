"""Acceptance cases for the electric product. They run when the release is built."""

import os
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import pytest
import shapely

from utilitydata.paths import DataPaths

pytestmark = pytest.mark.skipif(not os.environ.get("UTILITYDATA_HOME"), reason="UTILITYDATA_HOME is not set")


def _home() -> Path:
    return DataPaths.from_environment().home


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"{path.name} has not been built")
    return path


def test_electric_truth_file_has_no_invented_rows():
    path = Path(__file__).resolve().parents[2] / "registry" / "truth" / "electric.csv"
    frame = pd.read_csv(path, dtype="string")
    assert list(frame.columns) == ["lat", "lon", "expected_scheme", "expected_id", "evidence_url", "verified_by", "verified_on"]
    assert frame.empty


def test_water_truth_file_is_still_header_only():
    path = Path(__file__).resolve().parents[2] / "registry" / "truth" / "water.csv"
    frame = pd.read_csv(path, dtype="string")
    assert frame.empty


def test_dominion_is_one_system_in_virginia_and_north_carolina():
    systems = pd.read_parquet(_require(_home() / "core" / "2026-Q4" / "electric_system.parquet"))
    states = pd.read_parquet(_require(_home() / "core" / "2026-Q4" / "electric_system_state.parquet"))
    dominion = systems.loc[systems["system_id"].eq("SYS_EIA_19876")]
    assert len(dominion) == 1
    assert set(states.loc[states["system_id"].eq("SYS_EIA_19876"), "state"]) == {"VA", "NC"}


def test_downtown_washington_point_returns_pepco():
    territories = gpd.read_parquet(_require(_home() / "gold" / "2026-Q4" / "territories_electric.parquet"))
    point = shapely.Point(-77.0369, 38.9072)
    hits = territories.loc[territories.geometry.covers(point)]
    assert hits["name"].astype(str).str.contains("Potomac Electric", case=False).any()


def test_alabama_power_served_counties_match_its_eia_filing():
    home = _home()
    coverage = pd.read_parquet(_require(home / "gold" / "2026-Q4" / "electric_system_county_coverage.parquet"))
    retail = pd.read_parquet(_require(home / "silver" / "2026-Q4" / "electric_sales_retail.parquet"))
    territory = pd.read_parquet(home / "reference" / "pudl" / "v2026.10.0" / "core_eia861__yearly_service_territory.parquet")
    alabama = retail.loc[retail["utility_name_eia"].astype(str).str.contains("Alabama Power", case=False)]
    utility_id = int(alabama["utility_id_eia"].iloc[0])
    latest = territory["report_date"].max()
    filing = territory.loc[territory["utility_id_eia"].eq(utility_id) & territory["report_date"].eq(latest)]
    filing_counties = set(filing["county_id_fips"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5))
    served = coverage.loc[coverage["system_id"].eq(f"SYS_EIA_{utility_id}") & coverage["is_served"]]
    served_counties = set(served["county_geoid"].astype(str))
    assert set(filing["state"].astype(str)) == {"AL"}
    assert len(filing_counties) == 59
    assert served_counties <= filing_counties
    assert served_counties
    assert all(geoid.startswith("01") for geoid in served_counties)
    assert len(filing_counties) - len(served_counties) <= 5


def test_ameren_illinois_appears_once_and_shelby_electric_appears_once():
    systems = pd.read_parquet(_require(_home() / "core" / "2026-Q4" / "electric_system.parquet"))
    ameren = systems.loc[systems["name"].astype(str).eq("Ameren Illinois Company")]
    shelby = systems.loc[systems["name"].astype(str).str.contains(r"Shelby Electric Coop", case=False, regex=True)]
    assert len(ameren) == 1
    assert ameren["status"].iloc[0] == "active"
    assert ameren["system_id"].iloc[0] == "SYS_EIA_56697"
    assert len(shelby) == 1


def test_truth_or_consequences_geometry_is_flagged_when_present():
    home = _home()
    path = home / "core" / "2026-Q4" / "electric_service_area.parquet"
    # The flag lives on the boundary assertion, which is folded into service areas only after a link.
    # Read the assertion review flag from the electric report's source extract if the geoparquet kept it.
    assertions = gpd.read_parquet(_require(home / "silver" / "2026-Q4" / "electric_boundary_assertion.parquet"))
    rows = assertions.loc[
        assertions["raw_name"].astype(str).str.contains("TRUTH OR CONSEQUENCES", case=False)
        & assertions["authority"].eq("federal_modeled")
    ]
    if rows.empty:
        pytest.skip("The Truth or Consequences HIFLD record is not in the reviewed extract")
    assert bool(rows["state_mismatch"].all())
    assert set(rows["geom_state"].dropna().astype(str)) == {"OR"}
    del path


def test_no_electric_coverage_share_exceeds_one():
    home = _home()
    connection = duckdb.connect()
    try:
        for name, column in (
            ("electric_system_county_coverage.parquet", "pop_share_of_county"),
            ("electric_system_place_coverage.parquet", "pop_share_of_place"),
            ("electric_system_tract_coverage.parquet", "pop_share_of_tract"),
        ):
            path = _require(home / "gold" / "2026-Q4" / name)
            row = connection.execute(f"SELECT max({column}) FROM read_parquet(?)", [str(path)]).fetchone()
            assert row is not None
            assert row[0] is None or float(row[0]) <= 1
    finally:
        connection.close()


def test_every_active_retail_utility_has_customers_and_sales():
    systems = pd.read_parquet(_require(_home() / "core" / "2026-Q4" / "electric_system.parquet"))
    active = systems.loc[systems["status"].eq("active")]
    assert not active.empty
    assert bool(active["customers"].notna().all())
    assert bool(active["sales_mwh"].notna().all())


def test_water_coverage_still_excludes_inactive_systems_and_keeps_travis_small():
    home = _home()
    coverage = _require(home / "gold" / "2026-Q4" / "system_county_coverage.parquet")
    systems = _require(home / "core" / "2026-Q4" / "system.parquet")
    connection = duckdb.connect()
    try:
        inactive = connection.execute(
            """
            SELECT count(*)
            FROM read_parquet(?) coverage
            JOIN read_parquet(?) systems USING (system_id)
            WHERE systems.status <> 'active'
            """,
            [str(coverage), str(systems)],
        ).fetchone()
        travis = connection.execute(
            """
            SELECT count(DISTINCT system_id)
            FROM read_parquet(?)
            WHERE county_geoid = '48453' AND is_served
            """,
            [str(coverage)],
        ).fetchone()
    finally:
        connection.close()
    assert inactive is not None and int(inactive[0]) == 0
    assert travis is not None and int(travis[0]) < 120
