"""Block, county, place, and tract coverage for one sector's best areas.

Electric, wastewater, and gas call this. A block is inside a territory when
the territory covers the block's stored longitude and latitude. Shares above
1 stop the build. County administrative proxies are not a best serving role,
so they never enter these tables.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq
import shapely

from utilitydata.core.config import BEST_ROLES, IS_SERVED_MIN_POP, IS_SERVED_POP_SHARE
from utilitydata.core.text import require_columns
from utilitydata.gold.schema import (
    BLOCK_COVERAGE_COLUMNS,
    COUNTY_COVERAGE_COLUMNS,
    PLACE_COVERAGE_COLUMNS,
    TERRITORY_COLUMNS,
    TRACT_COVERAGE_COLUMNS,
)

_LEVELS = ("block", "county", "place", "tract")
_AREA_COLUMNS = (
    "service_area_id",
    "system_id",
    "sector",
    "zone_role",
    "source_id",
    "authority",
    "grain",
    "source_vintage_date",
    "is_best",
    "part_count",
    "area_km2",
    "footprint_verified",
    "licence",
    "boundary_representation",
    "geometry",
)
_SYSTEM_COLUMNS = (
    "system_id",
    "name",
    "status",
    "primary_state",
    "in_federal_registry",
    "population_served",
)


def coverage_paths(output: Path, file_prefix: str) -> list[Path]:
    """Return the four coverage outputs for one sector file prefix."""
    return [output / f"{file_prefix}_system_{level}_coverage.parquet" for level in _LEVELS]


def select_active_best(areas: gpd.GeoDataFrame, systems: pd.DataFrame, *, sector: str) -> gpd.GeoDataFrame:
    """Keep active best areas whose role can serve. A proxy role is excluded."""
    require_columns(areas, _AREA_COLUMNS, f"{sector} service areas")
    require_columns(systems, _SYSTEM_COLUMNS, f"{sector} systems")
    if bool(areas["sector"].isna().any()) or not bool(areas["sector"].eq(sector).all()):
        raise ValueError(f"A {sector} service area has a different sector")
    attributes = areas.drop(columns=["geometry"])
    overlap = [name for name in _SYSTEM_COLUMNS if name != "system_id" and name in attributes.columns]
    if overlap:
        attributes = attributes.drop(columns=overlap)
    best = attributes.merge(systems.loc[:, list(_SYSTEM_COLUMNS)], on="system_id", how="left")
    best = best.merge(areas.loc[:, ["service_area_id", "geometry"]], on="service_area_id", how="left")
    best = best.loc[best["is_best"].fillna(False) & best["status"].eq("active") & best["zone_role"].isin(BEST_ROLES)].copy()
    if best.empty:
        raise ValueError(f"No active {sector} best area was selected")
    if bool(best["licence"].isna().any()):
        raise ValueError(f"A {sector} best area is missing a licence")
    return gpd.GeoDataFrame(best, geometry="geometry", crs="EPSG:4326")


def write_territories(frame: gpd.GeoDataFrame, destination: Path, *, sector: str) -> int:
    """Write active best areas for one sector."""
    missing = [name for name in TERRITORY_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"{sector} territories are missing columns: {', '.join(missing)}")
    geo = gpd.GeoDataFrame(frame.loc[:, list(TERRITORY_COLUMNS)], geometry="geometry", crs="EPSG:4326")
    if not bool(geo["status"].eq("active").all()):
        raise ValueError(f"A {sector} territory is not an active system")
    if not bool(geo["is_best"].all()):
        raise ValueError(f"A {sector} territory is not the best area")
    if not bool(geo["zone_role"].isin(BEST_ROLES).all()):
        raise ValueError(f"A {sector} territory is not a serving role")
    if bool(geo["service_area_id"].duplicated().any()) or bool(geo["system_id"].duplicated().any()):
        raise ValueError(f"{sector} territory ids are not unique")
    destination.parent.mkdir(parents=True, exist_ok=True)
    geo.to_parquet(destination, index=False)
    return len(geo)


def write_sector_gold(
    areas: gpd.GeoDataFrame,
    systems: pd.DataFrame,
    *,
    sector: str,
    file_prefix: str,
    gold: Path,
    blocks: Path,
) -> dict[str, object]:
    """Write territories and the four coverage tables. A changed territory file drops stale coverage."""
    if not blocks.is_file():
        raise ValueError(f"Census blocks are missing: {blocks.as_posix()}")
    best = select_active_best(areas, systems, sector=sector)
    gold.mkdir(parents=True, exist_ok=True)
    territory_path = gold / f"territories_{file_prefix}.parquet"
    identity = ["service_area_id", "licence", "boundary_representation"]
    previous = pq.read_table(territory_path, columns=identity).to_pydict() if territory_path.is_file() else None
    rows = write_territories(best, territory_path, sector=sector)
    current = pq.read_table(territory_path, columns=identity).to_pydict()
    if previous != current:
        for path in coverage_paths(gold, file_prefix):
            path.unlink(missing_ok=True)
    coverage = build_sector_coverage(
        sector=sector,
        file_prefix=file_prefix,
        territories=territory_path,
        blocks=blocks,
        output=gold,
        work=gold / f"{file_prefix}_work",
    )
    coverage["territory_rows"] = rows
    return coverage


def build_sector_coverage(
    *,
    sector: str,
    file_prefix: str,
    territories: Path,
    blocks: Path,
    output: Path,
    work: Path,
) -> dict[str, object]:
    """Write block, county, place, and tract coverage for one sector's best areas."""
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    existing = coverage_paths(output, file_prefix)
    areas = gpd.read_parquet(territories)
    if all(path.is_file() and path.stat().st_size > 0 for path in existing):
        print(f"reusing {sector} block coverage", flush=True)
        return {
            "sector": sector,
            "best_areas": len(areas),
            "block_hits": pq_count(existing[0]),
            "reused_coverage": True,
        }
    payload = areas.drop(columns=["geometry"]).copy()
    payload["geometry"] = shapely.to_wkb(areas.geometry)
    wkb_path = work / f"{file_prefix}_best_wkb.parquet"
    payload.to_parquet(wkb_path, index=False)
    database = work / f"{file_prefix}_coverage.duckdb"
    if database.exists():
        database.unlink()
    connection = duckdb.connect(str(database))
    try:
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.execute("SET preserve_insertion_order=false")
        connection.execute("SET memory_limit='8GB'")
        connection.execute(f"SET temp_directory='{_path(work / 'tmp')}'")
        best_count = _load_best(connection, wkb_path, sector)
        print(f"{sector} best areas: {best_count}", flush=True)
        hit_count = _assign_blocks(connection, blocks, sector)
        print(f"{sector} block hits: {hit_count}", flush=True)
        _write_columns(connection, "hit", BLOCK_COVERAGE_COLUMNS, existing[0])
        _rollups(connection, output, file_prefix)
        for table, columns in (
            ("county_coverage", ("pop_share_of_county", "pop_share_of_system", "area_share")),
            ("place_coverage", ("pop_share_of_place", "pop_share_of_system", "area_share")),
            ("tract_coverage", ("pop_share_of_tract", "pop_share_of_system", "area_share")),
        ):
            _raise_if_share_exceeds_one(connection, table, columns)
    finally:
        connection.close()
    database.unlink(missing_ok=True)
    return {"sector": sector, "best_areas": best_count, "block_hits": hit_count, "reused_coverage": False}


def pq_count(path: Path) -> int:
    connection = duckdb.connect()
    try:
        row = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()
    finally:
        connection.close()
    return int(row[0]) if row else 0


def _load_best(connection: duckdb.DuckDBPyConnection, wkb_path: Path, sector: str) -> int:
    roles = ", ".join("'" + role + "'" for role in sorted(BEST_ROLES))
    connection.execute(
        f"""
        CREATE TABLE best AS
        SELECT service_area_id, system_id, sector, zone_role, source_id, authority, licence,
               in_federal_registry, ST_GeomFromWKB(geometry) AS geom
        FROM read_parquet('{_path(wkb_path)}')
        WHERE is_best AND status = 'active' AND zone_role IN ({roles})
        """
    )
    count = connection.execute("SELECT count(*) FROM best").fetchone()
    if count is None or int(count[0]) == 0:
        raise ValueError(f"No active {sector} best areas were found")
    connection.execute("CREATE INDEX best_rtree ON best USING RTREE (geom)")
    return int(count[0])


def _assign_blocks(connection: duckdb.DuckDBPyConnection, blocks: Path, sector: str) -> int:
    connection.execute(
        f"""
        CREATE TABLE blocks AS
        SELECT block_geoid, state, county_geoid, tract_geoid, place_geoid,
               pop20, housing20, aland20, lon, lat, ST_Point(lon, lat) AS geom
        FROM read_parquet('{_path(blocks)}')
        """
    )
    missing = connection.execute(
        """
        SELECT count(*) FROM blocks
        WHERE block_geoid IS NULL OR state IS NULL OR county_geoid IS NULL OR tract_geoid IS NULL
           OR pop20 IS NULL OR housing20 IS NULL OR aland20 IS NULL OR lon IS NULL OR lat IS NULL
        """
    ).fetchone()
    if missing and int(missing[0]):
        raise ValueError(f"{int(missing[0])} blocks are missing a point, population, or geography code")
    connection.execute(
        """
        CREATE TABLE hit (
          system_id VARCHAR, block_geoid VARCHAR, state VARCHAR, county_geoid VARCHAR,
          tract_geoid VARCHAR, place_geoid VARCHAR, pop20 BIGINT, housing20 BIGINT, aland20 BIGINT,
          service_area_id VARCHAR, source_id VARCHAR, authority VARCHAR, licence VARCHAR,
          sector VARCHAR, in_federal_registry BOOLEAN
        )
        """
    )
    state_codes = [row[0] for row in connection.execute("SELECT DISTINCT state FROM blocks ORDER BY 1").fetchall()]
    for state in state_codes:
        connection.execute(
            """
            INSERT INTO hit
            SELECT a.system_id, b.block_geoid, b.state, b.county_geoid, b.tract_geoid, b.place_geoid,
                   b.pop20, b.housing20, b.aland20, a.service_area_id, a.source_id, a.authority,
                   a.licence, a.sector, a.in_federal_registry
            FROM blocks b
            JOIN best a ON ST_Covers(a.geom, b.geom)
            WHERE b.state = ?
            """,
            [state],
        )
        print(f"{sector} block state {state}", flush=True)
    duplicated = connection.execute(
        "SELECT system_id, block_geoid FROM hit GROUP BY 1, 2 HAVING count(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicated:
        raise ValueError(f"A block was assigned twice to one {sector} system: {duplicated[0]} {duplicated[1]}")
    total = connection.execute("SELECT count(*) FROM hit").fetchone()
    if total is None or int(total[0]) == 0:
        raise ValueError(f"{sector} block assignment produced no rows")
    return int(total[0])


def _rollups(connection: duckdb.DuckDBPyConnection, output: Path, file_prefix: str) -> None:
    specs = (
        ("county_geoid", "pop_share_of_county", "county_coverage", COUNTY_COVERAGE_COLUMNS, output / f"{file_prefix}_system_county_coverage.parquet"),
        ("place_geoid", "pop_share_of_place", "place_coverage", PLACE_COVERAGE_COLUMNS, output / f"{file_prefix}_system_place_coverage.parquet"),
        ("tract_geoid", "pop_share_of_tract", "tract_coverage", TRACT_COVERAGE_COLUMNS, output / f"{file_prefix}_system_tract_coverage.parquet"),
    )
    for geoid, share, table, columns, destination in specs:
        where = "" if geoid == "county_geoid" else f"WHERE {geoid} IS NOT NULL"
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE {table} AS
            WITH base AS (
              SELECT {geoid}::VARCHAR AS geoid,
                     min(state)::VARCHAR AS state,
                     sum(pop20)::BIGINT AS pop,
                     sum(aland20)::BIGINT AS aland
              FROM blocks
              {where}
              GROUP BY 1
            ),
            poly AS (
              SELECT system_id, {geoid}::VARCHAR AS geoid,
                     sum(pop20)::BIGINT AS pop_in_area,
                     sum(housing20)::BIGINT AS housing_in_area,
                     sum(aland20)::BIGINT AS aland_in_area,
                     any_value(authority) AS authority,
                     any_value(licence) AS licence,
                     any_value(source_id) AS source_id,
                     any_value(sector) AS sector,
                     any_value(in_federal_registry) AS in_federal_registry
              FROM hit
              WHERE {geoid} IS NOT NULL
              GROUP BY 1, 2
            ),
            system_pop AS (
              SELECT system_id, sum(pop20)::BIGINT AS system_pop FROM hit GROUP BY 1
            )
            SELECT
              poly.system_id,
              poly.geoid AS {geoid},
              base.state,
              poly.sector,
              poly.pop_in_area,
              poly.housing_in_area,
              CASE
                WHEN base.pop IS NULL OR base.pop = 0 THEN NULL
                WHEN poly.pop_in_area = base.pop THEN 1.0
                ELSE poly.pop_in_area * 1.0 / base.pop
              END AS {share},
              CASE
                WHEN system_pop.system_pop IS NULL OR system_pop.system_pop = 0 THEN NULL
                WHEN poly.pop_in_area = system_pop.system_pop THEN 1.0
                ELSE poly.pop_in_area * 1.0 / system_pop.system_pop
              END AS pop_share_of_system,
              CASE
                WHEN base.aland IS NULL OR base.aland = 0 THEN NULL
                WHEN poly.aland_in_area = base.aland THEN 1.0
                ELSE poly.aland_in_area * 1.0 / base.aland
              END AS area_share,
              'polygon' AS evidence,
              poly.authority,
              (
                coalesce(
                  (CASE
                    WHEN base.pop IS NULL OR base.pop = 0 THEN NULL
                    WHEN poly.pop_in_area = base.pop THEN 1.0
                    ELSE poly.pop_in_area * 1.0 / base.pop
                  END) >= {IS_SERVED_POP_SHARE},
                  false
                )
                OR poly.pop_in_area >= {IS_SERVED_MIN_POP}
              ) AS is_served,
              poly.licence,
              poly.source_id,
              poly.in_federal_registry
            FROM poly
            JOIN base ON base.geoid = poly.geoid
            JOIN system_pop USING (system_id)
            """
        )
        _write_columns(connection, table, columns, destination)


def _raise_if_share_exceeds_one(connection: duckdb.DuckDBPyConnection, table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        row = connection.execute(f"SELECT system_id, {column} FROM {table} WHERE {column} > 1 LIMIT 1").fetchone()
        if row:
            raise ValueError(f"{table}.{column} exceeds 1 for {row[0]}: {row[1]}")


def _write_columns(connection: duckdb.DuckDBPyConnection, table: str, columns: tuple[str, ...], destination: Path) -> None:
    names = [row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()]
    missing = [name for name in columns if name not in names]
    if missing:
        raise ValueError(f"{table} is missing columns: {', '.join(missing)}")
    selected = ", ".join(columns)
    connection.execute(f"COPY (SELECT {selected} FROM {table}) TO '{_path(destination)}' (FORMAT parquet)")


def _path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
