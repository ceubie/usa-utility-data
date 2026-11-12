"""Sector coverage keeps proxies out and writes wastewater and gas tables."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

from utilitydata.sectors.coverage import build_sector_coverage, write_sector_gold


def _block(path: Path) -> None:
    pd.DataFrame([{
        "block_geoid": "48001",
        "state": "48",
        "county_geoid": "48001",
        "tract_geoid": "48001000000",
        "place_geoid": None,
        "pop20": 200,
        "housing20": 80,
        "aland20": 1000,
        "lon": -97.0,
        "lat": 30.0,
    }]).to_parquet(path, index=False)


def _area(role: str, service_area_id: str, system_id: str, polygon: shapely.Polygon, *, best: bool) -> dict[str, object]:
    return {
        "service_area_id": service_area_id,
        "system_id": system_id,
        "sector": "natural_gas",
        "zone_role": role,
        "source_id": "example",
        "authority": "state_regulator" if role != "administrative_unit_proxy" else "admin_proxy",
        "grain": "service_area",
        "source_vintage_date": pd.Timestamp("2020-01-01"),
        "is_best": best,
        "part_count": 1,
        "area_km2": 1.0,
        "footprint_verified": False,
        "licence": "unknown",
        "boundary_representation": "submitted" if role != "administrative_unit_proxy" else "modeled",
        "name": system_id,
        "status": "active",
        "primary_state": "TX",
        "in_federal_registry": True,
        "population_served": 200,
        "geometry": polygon,
    }


def test_proxy_role_does_not_cover_a_block_and_a_best_area_does(tmp_path: Path):
    blocks = tmp_path / "blocks.parquet"
    _block(blocks)
    retail = shapely.box(-97.1, 29.9, -96.9, 30.1)
    proxy = shapely.box(-97.1, 29.9, -96.9, 30.1)
    frame = gpd.GeoDataFrame(
        [
            _area("active_retail_service", "AREA_RETAIL", "SYS_GAS", retail, best=True),
            _area("administrative_unit_proxy", "AREA_PROXY", "SYS_PROXY", proxy, best=True),
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    territories = tmp_path / "territories.parquet"
    frame.to_parquet(territories, index=False)
    result = build_sector_coverage(
        sector="natural_gas",
        file_prefix="gas",
        territories=territories,
        blocks=blocks,
        output=tmp_path / "gold",
        work=tmp_path / "work",
    )
    assert result["block_hits"] == 1
    hits = pd.read_parquet(tmp_path / "gold" / "gas_system_block_coverage.parquet")
    assert list(hits["system_id"]) == ["SYS_GAS"]
    assert list(hits["sector"]) == ["natural_gas"]
    county = pd.read_parquet(tmp_path / "gold" / "gas_system_county_coverage.parquet")
    assert bool(county.iloc[0]["is_served"])
    assert (tmp_path / "gold" / "gas_system_place_coverage.parquet").is_file()
    assert (tmp_path / "gold" / "gas_system_tract_coverage.parquet").is_file()


def test_write_sector_gold_names_wastewater_tables(tmp_path: Path):
    blocks = tmp_path / "ref_block.parquet"
    _block(blocks)
    polygon = shapely.box(-97.1, 29.9, -96.9, 30.1)
    areas = gpd.GeoDataFrame(
        [{
            "service_area_id": "AREA_WW",
            "system_id": "SYS_WW",
            "sector": "wastewater",
            "zone_role": "certified_franchise_territory",
            "source_id": "example",
            "authority": "state_regulator",
            "grain": "service_area",
            "source_vintage_date": pd.Timestamp("2020-01-01"),
            "is_best": True,
            "part_count": 1,
            "area_km2": 1.0,
            "footprint_verified": False,
            "licence": "unknown",
            "boundary_representation": "submitted",
            "geometry": polygon,
        }],
        geometry="geometry",
        crs="EPSG:4326",
    )
    systems = pd.DataFrame([{
        "system_id": "SYS_WW",
        "name": "Example Sewer",
        "status": "active",
        "primary_state": "TX",
        "in_federal_registry": True,
        "population_served": 200,
    }])
    result = write_sector_gold(
        areas,
        systems,
        sector="wastewater",
        file_prefix="wastewater",
        gold=tmp_path / "gold",
        blocks=blocks,
    )
    assert result["territory_rows"] == 1
    saved = gpd.read_parquet(tmp_path / "gold" / "territories_wastewater.parquet")
    assert list(saved["zone_role"]) == ["certified_franchise_territory"]
    assert (tmp_path / "gold" / "wastewater_system_county_coverage.parquet").is_file()
