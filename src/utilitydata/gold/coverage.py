"""Block, county, place, and tract coverage for active serving water systems.

Block assignment uses the representative point already stored on ``ref_block``.
The spatial predicate runs in DuckDB, one state at a time. A coverage share above
1 stops the build. Shares are not clipped.
"""

from pathlib import Path

import duckdb
import pandas as pd

from utilitydata.core.config import (
    BEST_ROLES,
    IS_SERVED_MIN_POP,
    IS_SERVED_POP_SHARE,
    RESTRICTED_LICENCES,
    SHAREABLE_LICENCES,
)
from utilitydata.core.text import require_columns
from utilitydata.gold.schema import (
    BLOCK_COVERAGE_COLUMNS,
    COUNTY_COVERAGE_COLUMNS,
    PLACE_COVERAGE_COLUMNS,
    TRACT_COVERAGE_COLUMNS,
    TRAVIS_COUNTY_GEOID,
    TRAVIS_SERVED_LIMIT,
)
from utilitydata.gold.tabular import classify_sdwa_geography

_SERVING_SQL = ", ".join("'" + role + "'" for role in sorted(BEST_ROLES))
_SHARE_COLUMNS = {
    "system_county_coverage": ("pop_share_of_county", "pop_share_of_system", "area_share"),
    "system_place_coverage": ("pop_share_of_place", "pop_share_of_system", "area_share"),
    "system_tract_coverage": ("pop_share_of_tract", "pop_share_of_system", "area_share"),
}


def is_served(pop_share: object, pop_in_area: object) -> bool:
    """Return whether a geography meets the configured served rule."""
    share_ok = pop_share is not None and not pd.isna(pop_share) and float(pop_share) >= IS_SERVED_POP_SHARE
    return share_ok or int(pop_in_area) >= IS_SERVED_MIN_POP


def require_shares_at_most_one(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    """Raise when a share column is above 1. Nothing is clipped."""
    require_columns(frame, columns, label)
    for column in columns:
        values = frame[column].dropna()
        excess = values[values > 1]
        if not excess.empty:
            raise ValueError(f"{label}.{column} exceeds 1, for example {float(excess.iloc[0])}")


def build_coverage(
    *,
    service_areas: Path,
    systems: Path,
    blocks: Path,
    assertions: Path,
    geographic: Path,
    states: Path,
    counties: Path,
    places: Path,
    alias: Path,
    identifiers: Path,
    output: Path,
    work: Path,
    sdwa_licence: str,
    sdwa_source_id: str,
    reuse_work: bool = False,
) -> dict[str, object]:
    """Write the four coverage tables and the unresolved geography audit."""
    _require_licence(sdwa_licence)
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    database = work / "coverage.duckdb"
    reused = reuse_work and database.exists()
    if database.exists() and not reused:
        database.unlink()
    connection = duckdb.connect(str(database))
    try:
        _prepare(connection, work)
        if reused and _table_ready(connection, "hit") and _table_ready(connection, "blocks") and _table_ready(connection, "best"):
            print("reusing block hits", flush=True)
            best_count = int(connection.execute("SELECT count(*) FROM best").fetchall()[0][0])
            hit_count = int(connection.execute("SELECT count(*) FROM hit").fetchall()[0][0])
        else:
            print("preparing best serving areas", flush=True)
            best_count = _load_best(connection, service_areas, systems, assertions, work / "best_areas_wkb.parquet")
            print(f"best serving areas: {best_count}", flush=True)
            print("assigning block internal points", flush=True)
            hit_count = _assign_blocks(connection, blocks)
            print(f"block hits: {hit_count}", flush=True)
            _write_columns(connection, "hit", BLOCK_COVERAGE_COLUMNS, output / "system_block_coverage.parquet")
        connection.execute(f"CREATE OR REPLACE VIEW ref_county AS SELECT * FROM read_parquet('{_literal_path(counties)}')")
        connection.execute(f"CREATE OR REPLACE VIEW ref_place AS SELECT * FROM read_parquet('{_literal_path(places)}')")
        links = _geography_links(geographic, systems, states, counties, places, alias, identifiers)
        _register_links(connection, links[0], links[1])
        print("rolling coverage up to counties, places, and tracts", flush=True)
        _write_geography(
            connection,
            geoid="county_geoid",
            share="pop_share_of_county",
            tabular="tabular_county",
            destination=output / "system_county_coverage.parquet",
            columns=COUNTY_COVERAGE_COLUMNS,
            sdwa_licence=sdwa_licence,
            sdwa_source_id=sdwa_source_id,
            reference="ref_county",
        )
        _write_geography(
            connection,
            geoid="place_geoid",
            share="pop_share_of_place",
            tabular="tabular_place",
            destination=output / "system_place_coverage.parquet",
            columns=PLACE_COVERAGE_COLUMNS,
            sdwa_licence=sdwa_licence,
            sdwa_source_id=sdwa_source_id,
            reference="ref_place",
        )
        _write_geography(
            connection,
            geoid="tract_geoid",
            share="pop_share_of_tract",
            tabular=None,
            destination=output / "system_tract_coverage.parquet",
            columns=TRACT_COVERAGE_COLUMNS,
            sdwa_licence=sdwa_licence,
            sdwa_source_id=sdwa_source_id,
            reference=None,
        )
        _require_active(connection, systems)
        for table, columns in _SHARE_COLUMNS.items():
            _raise_if_share_exceeds_one(connection, table, columns)
        travis = _travis_count(connection)
        if travis >= TRAVIS_SERVED_LIMIT:
            raise ValueError(
                f"Travis County has {travis} active served water providers, "
                f"which is not below {TRAVIS_SERVED_LIMIT}"
            )
        links[2].to_parquet(output / "tabular_geography_unresolved.parquet", index=False)
        excluded = _excluded_best_areas(connection, service_areas, systems)
    finally:
        connection.close()
    database.unlink(missing_ok=True)
    return {
        "best_serving_areas": best_count,
        "block_hits": hit_count,
        "travis_county_served_systems": travis,
        "geography_unresolved": dict(links[3]),
        "excluded_best_areas": excluded,
        "best_areas_wkb": "gold/_work/best_areas_wkb.parquet",
    }


def _table_ready(connection: duckdb.DuckDBPyConnection, name: str) -> bool:
    try:
        connection.execute(f"SELECT 1 FROM {name} LIMIT 0").fetchall()
    except duckdb.Error:
        return False
    return True


def _prepare(connection: duckdb.DuckDBPyConnection, work: Path) -> None:
    connection.execute("INSTALL spatial")
    connection.execute("LOAD spatial")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET memory_limit='8GB'")
    connection.execute(f"SET temp_directory='{_literal_path(work / 'tmp')}'")


def _load_best(
    connection: duckdb.DuckDBPyConnection,
    service_areas: Path,
    systems: Path,
    assertions: Path,
    wkb_path: Path,
) -> int:
    areas = _literal_path(service_areas)
    system_path = _literal_path(systems)
    assertion_path = _literal_path(assertions)
    area_cols = {row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{areas}')").fetchall()}
    assertion_cols = {row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{assertion_path}')").fetchall()}
    if "boundary_representation" in area_cols:
        connection.execute(
            f"""
            CREATE TABLE best AS
            SELECT a.service_area_id, a.system_id, s.name, s.sector, s.status, s.primary_state,
                   s.in_federal_registry, s.population_served, a.zone_role, a.source_id, a.authority,
                   a.grain, a.source_vintage_date, a.is_best, a.part_count, a.area_km2,
                   a.footprint_verified, a.licence, a.boundary_representation, a.geometry AS geom
            FROM read_parquet('{areas}') a
            JOIN read_parquet('{system_path}') s USING (system_id)
            WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status = 'active'
            """
        )
        bad = connection.execute("SELECT service_area_id FROM best WHERE boundary_representation IS NULL LIMIT 5").fetchall()
        if bad:
            raise ValueError(f"Best serving area has null boundary representation, for example {bad[0]}")
    elif "authority" in assertion_cols:
        connection.execute(
            f"""
            CREATE TABLE representation AS
            SELECT source_id,
                   authority,
                   CASE
                     WHEN count(DISTINCT boundary_representation) = 1 THEN min(boundary_representation)
                     ELSE 'mixed'
                   END AS boundary_representation,
                   count(*) FILTER (WHERE boundary_representation IS NULL) AS n_null
            FROM read_parquet('{assertion_path}')
            GROUP BY 1, 2
            """
        )
        bad = connection.execute(
            f"""
            SELECT a.source_id, a.authority, r.n_null, r.boundary_representation
            FROM (
              SELECT DISTINCT a.source_id, a.authority
              FROM read_parquet('{areas}') a
              JOIN read_parquet('{system_path}') s USING (system_id)
              WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status = 'active'
            ) a
            LEFT JOIN representation r USING (source_id, authority)
            WHERE r.source_id IS NULL OR r.n_null > 0 OR r.boundary_representation IS NULL
            LIMIT 5
            """
        ).fetchall()
        if bad:
            raise ValueError(f"Best serving area has no resolved boundary representation, for example {bad[0]}")
        connection.execute(
            f"""
            CREATE TABLE best AS
            SELECT a.service_area_id, a.system_id, s.name, s.sector, s.status, s.primary_state,
                   s.in_federal_registry, s.population_served, a.zone_role, a.source_id, a.authority,
                   a.grain, a.source_vintage_date, a.is_best, a.part_count, a.area_km2,
                   a.footprint_verified, a.licence, r.boundary_representation, a.geometry AS geom
            FROM read_parquet('{areas}') a
            JOIN read_parquet('{system_path}') s USING (system_id)
            JOIN representation r USING (source_id, authority)
            WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status = 'active'
            """
        )
    else:
        connection.execute(
            f"""
            CREATE TABLE representation AS
            SELECT source_id,
                   min(boundary_representation) AS boundary_representation,
                   count(DISTINCT boundary_representation) AS n_rep,
                   count(*) FILTER (WHERE boundary_representation IS NULL) AS n_null
            FROM read_parquet('{assertion_path}')
            GROUP BY 1
            """
        )
        bad = connection.execute(
            f"""
            SELECT a.source_id, r.n_rep, r.n_null, r.boundary_representation
            FROM (
              SELECT DISTINCT a.source_id
              FROM read_parquet('{areas}') a
              JOIN read_parquet('{system_path}') s USING (system_id)
              WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status = 'active'
            ) a
            LEFT JOIN representation r USING (source_id)
            WHERE r.source_id IS NULL OR r.n_rep <> 1 OR r.n_null > 0 OR r.boundary_representation IS NULL
            LIMIT 5
            """
        ).fetchall()
        if bad:
            raise ValueError(f"Best serving area has no single boundary representation, for example {bad[0]}")
        connection.execute(
            f"""
            CREATE TABLE best AS
            SELECT a.service_area_id, a.system_id, s.name, s.sector, s.status, s.primary_state,
                   s.in_federal_registry, s.population_served, a.zone_role, a.source_id, a.authority,
                   a.grain, a.source_vintage_date, a.is_best, a.part_count, a.area_km2,
                   a.footprint_verified, a.licence, r.boundary_representation, a.geometry AS geom
            FROM read_parquet('{areas}') a
            JOIN read_parquet('{system_path}') s USING (system_id)
            JOIN representation r USING (source_id)
            WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status = 'active'
            """
        )
    problems = connection.execute(
        """
        SELECT licence, count(*)
        FROM best
        WHERE licence IS NULL OR geom IS NULL OR ST_IsEmpty(geom)
           OR sector IS NULL OR authority IS NULL
        GROUP BY 1
        """
    ).fetchall()
    if problems:
        raise ValueError(f"Best serving area is missing licence, authority, or geometry: {problems}")
    unknown = connection.execute(
        f"""
        SELECT DISTINCT licence FROM best
        WHERE licence NOT IN ({_licence_list()})
        """
    ).fetchall()
    if unknown:
        raise ValueError(f"Best serving area has an unclassified licence: {unknown}")
    disagreed = connection.execute(
        f"""
        SELECT count(*)
        FROM read_parquet('{areas}') a
        JOIN read_parquet('{system_path}') s USING (system_id)
        WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status = 'active'
          AND a.sector IS DISTINCT FROM s.sector
        """
    ).fetchone()
    if disagreed and int(disagreed[0]):
        raise ValueError("A best serving area sector does not match its system")
    count = connection.execute("SELECT count(*) FROM best").fetchone()
    if count is None or int(count[0]) == 0:
        raise ValueError("No active best serving areas were found")
    if int(connection.execute("SELECT count(*) - count(DISTINCT system_id) FROM best").fetchone()[0]):
        raise ValueError("More than one best serving area was selected for a system")
    connection.execute("CREATE INDEX best_rtree ON best USING RTREE (geom)")
    connection.execute(
        f"""
        COPY (
          SELECT service_area_id, system_id, name, sector, status, primary_state,
                 in_federal_registry, population_served, zone_role, source_id, authority, grain,
                 source_vintage_date, is_best, part_count, area_km2, footprint_verified, licence,
                 boundary_representation, ST_AsWKB(geom) AS geometry
          FROM best
        ) TO '{_literal_path(wkb_path)}' (FORMAT parquet)
        """
    )
    return int(count[0])


def _assign_blocks(connection: duckdb.DuckDBPyConnection, blocks: Path) -> int:
    connection.execute(
        f"""
        CREATE TABLE blocks AS
        SELECT block_geoid, state, county_geoid, tract_geoid, place_geoid,
               pop20, housing20, aland20, lon, lat, ST_Point(lon, lat) AS geom
        FROM read_parquet('{_literal_path(blocks)}')
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
    states = [row[0] for row in connection.execute("SELECT DISTINCT state FROM blocks ORDER BY 1").fetchall()]
    for state in states:
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
        print(f"block state {state}", flush=True)
    duplicated = connection.execute(
        """
        SELECT system_id, block_geoid, count(*) AS n
        FROM hit
        GROUP BY 1, 2
        HAVING n > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicated:
        raise ValueError(f"A block was assigned twice to one system: {duplicated[0]} {duplicated[1]}")
    total = connection.execute("SELECT count(*) FROM hit").fetchone()
    if total is None or int(total[0]) == 0:
        raise ValueError("Block assignment produced no rows")
    return int(total[0])


def _write_geography(
    connection: duckdb.DuckDBPyConnection,
    *,
    geoid: str,
    share: str,
    tabular: str | None,
    destination: Path,
    columns: tuple[str, ...],
    sdwa_licence: str,
    sdwa_source_id: str,
    reference: str | None,
) -> None:
    if geoid not in {"county_geoid", "place_geoid", "tract_geoid"}:
        raise ValueError(f"Unsupported coverage geography: {geoid}")
    base = f"{geoid}_base"
    where = "" if geoid == "county_geoid" else f"WHERE {geoid} IS NOT NULL"
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {base} AS
        SELECT {geoid}::VARCHAR AS geoid,
               min(state)::VARCHAR AS state,
               count(DISTINCT state)::BIGINT AS n_state,
               sum(pop20)::BIGINT AS pop,
               sum(aland20)::BIGINT AS aland
        FROM blocks
        {where}
        GROUP BY 1
        """
    )
    split = connection.execute(f"SELECT geoid FROM {base} WHERE n_state > 1 LIMIT 1").fetchone()
    if split:
        raise ValueError(f"{geoid} {split[0]} is in more than one state")
    if reference == "ref_county":
        _require_reference_population(connection, base, reference, geoid)
    if reference is not None:
        connection.execute(
            f"""
            INSERT INTO {base}
            SELECT r.{geoid}, r.state, 1, coalesce(r.pop20, 0)::BIGINT, NULL::BIGINT
            FROM {reference} r
            ANTI JOIN {base} b ON b.geoid = r.{geoid}
            """
        ).fetchall()
    tab_sql = (
        f"SELECT system_id, {geoid} AS geoid, sector, in_federal_registry FROM {tabular}"
        if tabular is not None
        else "SELECT NULL::VARCHAR AS system_id, NULL::VARCHAR AS geoid, NULL::VARCHAR AS sector, NULL::BOOLEAN AS in_federal_registry WHERE false"
    )
    _raise_if_part_exceeds_whole(connection, geoid, base)
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE {geoid}_coverage AS
        WITH poly AS (
          SELECT system_id, {geoid} AS geoid,
                 sum(pop20)::BIGINT AS pop_in_area,
                 sum(housing20)::BIGINT AS housing_in_area,
                 sum(aland20)::BIGINT AS aland_in_area,
                 any_value(authority) AS authority,
                 count(DISTINCT authority) AS n_authority,
                 any_value(licence) AS licence,
                 any_value(source_id) AS source_id,
                 any_value(sector) AS sector,
                 any_value(in_federal_registry) AS in_federal_registry
          FROM hit
          WHERE {geoid} IS NOT NULL
          GROUP BY 1, 2
        ),
        tab AS ({tab_sql}),
        keys AS (
          SELECT system_id, geoid FROM poly
          UNION
          SELECT system_id, geoid FROM tab
        ),
        system_pop AS (
          SELECT system_id, sum(pop20)::BIGINT AS system_pop FROM hit GROUP BY 1
        ),
        measured AS (
          SELECT
            k.system_id,
            k.geoid AS {geoid},
            b.state,
            coalesce(p.sector, t.sector) AS sector,
            coalesce(p.pop_in_area, 0)::BIGINT AS pop_in_area,
            coalesce(p.housing_in_area, 0)::BIGINT AS housing_in_area,
            CASE
              WHEN b.pop IS NULL OR b.pop = 0 THEN NULL
              WHEN coalesce(p.pop_in_area, 0) = b.pop THEN 1.0
              ELSE coalesce(p.pop_in_area, 0) * 1.0 / b.pop
            END AS {share},
            CASE
              WHEN s.system_pop IS NULL OR s.system_pop = 0 THEN NULL
              WHEN coalesce(p.pop_in_area, 0) = s.system_pop THEN 1.0
              ELSE coalesce(p.pop_in_area, 0) * 1.0 / s.system_pop
            END AS pop_share_of_system,
            CASE
              WHEN b.aland IS NULL OR b.aland = 0 THEN NULL
              WHEN coalesce(p.aland_in_area, 0) = b.aland THEN 1.0
              ELSE coalesce(p.aland_in_area, 0) * 1.0 / b.aland
            END AS area_share,
            CASE
              WHEN p.system_id IS NOT NULL AND t.system_id IS NOT NULL THEN 'both'
              WHEN p.system_id IS NOT NULL THEN 'polygon'
              ELSE 'tabular'
            END AS evidence,
            p.authority,
            CASE WHEN p.system_id IS NOT NULL THEN p.licence ELSE '{sdwa_licence}' END AS licence,
            CASE WHEN p.system_id IS NOT NULL THEN p.source_id ELSE '{sdwa_source_id}' END AS source_id,
            coalesce(p.in_federal_registry, t.in_federal_registry) AS in_federal_registry
          FROM keys k
          LEFT JOIN poly p ON p.system_id = k.system_id AND p.geoid = k.geoid
          LEFT JOIN tab t ON t.system_id = k.system_id AND t.geoid = k.geoid
          JOIN {base} b ON b.geoid = k.geoid
          LEFT JOIN system_pop s ON s.system_id = k.system_id
        )
        SELECT measured.*,
               (coalesce({share} >= {IS_SERVED_POP_SHARE}, false) OR pop_in_area >= {IS_SERVED_MIN_POP}) AS is_served
        FROM measured
        """
    )
    conflict = connection.execute(
        f"""
        WITH poly AS (
          SELECT system_id, {geoid} AS geoid, count(DISTINCT authority) AS n_authority,
                 count(DISTINCT licence) AS n_licence, count(DISTINCT source_id) AS n_source
          FROM hit
          WHERE {geoid} IS NOT NULL
          GROUP BY 1, 2
        )
        SELECT count(*) FROM poly WHERE n_authority > 1 OR n_licence > 1 OR n_source > 1
        """
    ).fetchone()
    if conflict and int(conflict[0]):
        raise ValueError(f"A {geoid} coverage row has more than one authority, licence, or source")
    table = _output_name(destination)
    connection.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM {geoid}_coverage")
    missing_base = connection.execute(
        f"""
        SELECT count(*)
        FROM (
          SELECT system_id, {geoid} AS geoid FROM hit WHERE {geoid} IS NOT NULL
          UNION
          SELECT system_id, geoid FROM ({tab_sql})
        ) keys
        ANTI JOIN {base} b ON b.geoid = keys.geoid
        """
    ).fetchone()
    if missing_base and int(missing_base[0]):
        raise ValueError(f"{int(missing_base[0])} {geoid} coverage keys are missing from the block base")
    _write_columns(connection, f"{geoid}_coverage", columns, destination)


def _require_reference_population(
    connection: duckdb.DuckDBPyConnection,
    base: str,
    reference: str,
    geoid: str,
) -> None:
    ref_pop = "pop20"
    mismatch = connection.execute(
        f"""
        SELECT b.geoid, b.pop, r.{ref_pop}
        FROM {base} b
        JOIN {reference} r ON r.{geoid} = b.geoid
        WHERE b.pop IS DISTINCT FROM r.{ref_pop}
        LIMIT 1
        """
    ).fetchone()
    if mismatch:
        raise ValueError(f"{geoid} {mismatch[0]} block population {mismatch[1]} does not match the reference {mismatch[2]}")


def _raise_if_part_exceeds_whole(connection: duckdb.DuckDBPyConnection, geoid: str, base: str) -> None:
    row = connection.execute(
        f"""
        WITH poly AS (
          SELECT system_id, {geoid} AS geoid,
                 sum(pop20)::BIGINT AS pop_in_area,
                 sum(aland20)::BIGINT AS aland_in_area
          FROM hit
          WHERE {geoid} IS NOT NULL
          GROUP BY 1, 2
        ),
        system_pop AS (
          SELECT system_id, sum(pop20)::BIGINT AS system_pop FROM hit GROUP BY 1
        )
        SELECT poly.system_id, poly.geoid, poly.pop_in_area, b.pop, poly.aland_in_area, b.aland, s.system_pop
        FROM poly
        JOIN {base} b ON b.geoid = poly.geoid
        JOIN system_pop s USING (system_id)
        WHERE poly.pop_in_area > b.pop
           OR poly.aland_in_area > b.aland
           OR poly.pop_in_area > s.system_pop
        LIMIT 1
        """
    ).fetchone()
    if row:
        raise ValueError(f"{geoid} coverage part exceeds its whole: system {row[0]} geography {row[1]}")


def _raise_if_share_exceeds_one(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    columns: tuple[str, ...],
) -> None:
    for column in columns:
        row = connection.execute(f"SELECT system_id, {column} FROM {table} WHERE {column} > 1 LIMIT 1").fetchone()
        if row:
            raise ValueError(f"{table}.{column} exceeds 1 for {row[0]}: {row[1]}")


def _require_active(connection: duckdb.DuckDBPyConnection, systems: Path) -> None:
    for table in ("hit", "county_geoid_coverage", "place_geoid_coverage", "tract_geoid_coverage"):
        row = connection.execute(
            f"""
            SELECT c.system_id, s.status
            FROM {table} c
            LEFT JOIN read_parquet('{_literal_path(systems)}') s USING (system_id)
            WHERE s.system_id IS NULL OR s.status <> 'active'
            LIMIT 1
            """
        ).fetchone()
        if row:
            raise ValueError(f"{table} contains a system that is not active: {row}")


def _travis_count(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        """
        SELECT count(DISTINCT system_id)
        FROM county_geoid_coverage
        WHERE county_geoid = ? AND is_served
        """,
        [TRAVIS_COUNTY_GEOID],
    ).fetchone()
    return int(row[0]) if row else 0


def _excluded_best_areas(
    connection: duckdb.DuckDBPyConnection,
    service_areas: Path,
    systems: Path,
) -> list[dict[str, object]]:
    rows = connection.execute(
        f"""
        SELECT s.status,
               CASE WHEN s.system_id LIKE 'SYS_LOC_%' THEN 'provisional' ELSE 'other' END AS origin,
               count(*) AS areas
        FROM read_parquet('{_literal_path(service_areas)}') a
        JOIN read_parquet('{_literal_path(systems)}') s USING (system_id)
        WHERE a.is_best AND a.zone_role IN ({_SERVING_SQL}) AND s.status <> 'active'
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchall()
    return [{"status": status, "origin": origin, "areas": int(areas)} for status, origin, areas in rows]


def _geography_links(
    geographic: Path,
    systems: Path,
    states: Path,
    counties: Path,
    places: Path,
    alias: Path,
    identifiers: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, object]:
    system = pd.read_parquet(
        systems,
        columns=["system_id", "status", "primary_state", "sector", "in_federal_registry"],
    )
    identifier = pd.read_parquet(identifiers, columns=["system_id", "scheme", "value"])
    identifier = identifier.loc[identifier["scheme"].eq("pwsid"), ["system_id", "value"]].drop_duplicates()
    identifier = identifier.rename(columns={"value": "pwsid"})
    lookup = system.merge(identifier, on="system_id", how="inner")
    geographic_frame = pd.read_parquet(
        geographic,
        columns=["PWSID", "AREA_TYPE_CODE", "ANSI_ENTITY_CODE", "COUNTY_SERVED", "CITY_SERVED", "STATE_SERVED"],
    )
    return classify_sdwa_geography(
        geographic_frame,
        lookup,
        pd.read_parquet(states, columns=["state", "usps"]),
        pd.read_parquet(counties, columns=["county_geoid", "state", "name", "pop20"]),
        pd.read_parquet(places, columns=["place_geoid", "state", "name", "pop20"]),
        pd.read_parquet(alias, columns=["old_county_geoid", "old_county_name", "county_geoid", "county_name"]),
    )


def _register_links(connection: duckdb.DuckDBPyConnection, counties: pd.DataFrame, places: pd.DataFrame) -> None:
    connection.register("tabular_county_frame", counties)
    connection.register("tabular_place_frame", places)
    connection.execute("CREATE OR REPLACE TABLE tabular_county AS SELECT * FROM tabular_county_frame")
    connection.execute("CREATE OR REPLACE TABLE tabular_place AS SELECT * FROM tabular_place_frame")
    connection.unregister("tabular_county_frame")
    connection.unregister("tabular_place_frame")


def _write_columns(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    columns: tuple[str, ...],
    destination: Path,
) -> None:
    listed = ", ".join(columns)
    connection.execute(
        f"COPY (SELECT {listed} FROM {table} ORDER BY 1, 2) TO '{_literal_path(destination)}' (FORMAT parquet)"
    )


def _output_name(path: Path) -> str:
    return path.stem


def _licence_list() -> str:
    values = sorted(SHAREABLE_LICENCES | RESTRICTED_LICENCES)
    return ", ".join("'" + value + "'" for value in values)


def _require_licence(licence: str) -> None:
    if licence not in SHAREABLE_LICENCES | RESTRICTED_LICENCES:
        raise ValueError(f"SDWA licence is not classified: {licence}")


def _literal_path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
