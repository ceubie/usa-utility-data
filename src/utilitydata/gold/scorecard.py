"""State and sector coverage scorecard.

Population inside a non-modeled boundary counts a block once. Unknown, mixed,
and modeled boundaries are not counted as non-modeled. The denominator is the
block population of the state.
"""

from datetime import date
from pathlib import Path

import duckdb

from utilitydata.gold.schema import (
    MISSING_STATE,
    SCORECARD_COLUMNS,
    UNMODELED_REPRESENTATION,
)


def write_scorecard(
    *,
    blocks: Path,
    block_coverage: Path,
    territories: Path,
    systems: Path,
    states: Path,
    destination: Path,
    as_of: date,
) -> dict[str, object]:
    """Write one row per state and sector, including systems with no boundary."""
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        connection.execute(
            f"""
            CREATE VIEW blocks AS
            SELECT state, block_geoid, pop20 FROM read_parquet('{_path(blocks)}');
            CREATE VIEW coverage AS
            SELECT system_id, state, block_geoid, pop20 FROM read_parquet('{_path(block_coverage)}');
            CREATE VIEW territory AS
            SELECT service_area_id, system_id, sector, primary_state, source_vintage_date, boundary_representation
            FROM read_parquet('{_path(territories)}');
            CREATE VIEW system AS
            SELECT system_id, sector, status, primary_state FROM read_parquet('{_path(systems)}');
            CREATE VIEW state_ref AS
            SELECT state AS state_fips, usps, pop20 FROM read_parquet('{_path(states)}');
            """
        )
        connection.execute(
            f"""
            COPY (
              WITH state_pop AS (
                SELECT state AS state_fips, sum(pop20)::BIGINT AS population
                FROM blocks
                GROUP BY 1
              ),
              nonmodeled_block AS (
                SELECT c.state AS state_fips, t.sector, c.block_geoid, any_value(c.pop20)::BIGINT AS pop20
                FROM coverage c
                JOIN territory t USING (system_id)
                WHERE t.boundary_representation = '{UNMODELED_REPRESENTATION}'
                GROUP BY 1, 2, 3
              ),
              nonmodeled AS (
                SELECT state_fips, sector, sum(pop20)::BIGINT AS population_in_nonmodeled_boundary
                FROM nonmodeled_block
                GROUP BY 1, 2
              ),
              covered AS (
                SELECT DISTINCT t.service_area_id, c.state AS state_fips, t.source_vintage_date, t.sector
                FROM territory t
                JOIN coverage c USING (system_id)
              ),
              missed AS (
                SELECT t.service_area_id, r.state_fips, t.source_vintage_date, t.sector
                FROM territory t
                LEFT JOIN state_ref r ON r.usps = t.primary_state
                WHERE t.service_area_id NOT IN (SELECT service_area_id FROM covered)
              ),
              area AS (
                SELECT * FROM covered
                UNION ALL
                SELECT * FROM missed
              ),
              age AS (
                SELECT state_fips, sector,
                       median(date_diff('day', source_vintage_date, DATE '{as_of.isoformat()}'))
                         FILTER (WHERE source_vintage_date IS NOT NULL) AS median_boundary_age_days,
                       count(DISTINCT service_area_id) FILTER (WHERE source_vintage_date IS NOT NULL) AS boundaries_with_vintage,
                       count(DISTINCT service_area_id) FILTER (WHERE source_vintage_date IS NULL) AS boundaries_missing_vintage
                FROM area
                GROUP BY 1, 2
              ),
              active AS (
                SELECT CASE WHEN s.primary_state IS NULL THEN '{MISSING_STATE}' ELSE s.primary_state END AS state,
                       s.sector,
                       count(*)::BIGINT AS active_systems,
                       count(*) FILTER (WHERE t.system_id IS NULL)::BIGINT AS systems_with_no_boundary
                FROM system s
                LEFT JOIN (SELECT DISTINCT system_id FROM territory) t USING (system_id)
                WHERE s.status = 'active'
                GROUP BY 1, 2
              ),
              sectors AS (
                SELECT DISTINCT sector FROM active
              ),
              geographic AS (
                SELECT r.usps AS state, sectors.sector, p.population,
                       coalesce(n.population_in_nonmodeled_boundary, 0)::BIGINT AS population_in_nonmodeled_boundary,
                       a.median_boundary_age_days, coalesce(a.boundaries_with_vintage, 0) AS boundaries_with_vintage,
                       coalesce(a.boundaries_missing_vintage, 0) AS boundaries_missing_vintage
                FROM state_ref r
                CROSS JOIN sectors
                LEFT JOIN state_pop p ON p.state_fips = r.state_fips
                LEFT JOIN nonmodeled n ON n.state_fips = r.state_fips AND n.sector = sectors.sector
                LEFT JOIN age a ON a.state_fips = r.state_fips AND a.sector = sectors.sector
              ),
              combined AS (
                SELECT g.state, g.sector, g.population, g.population_in_nonmodeled_boundary,
                       CASE WHEN g.population > 0 THEN g.population_in_nonmodeled_boundary * 1.0 / g.population ELSE NULL END
                         AS share_population_nonmodeled,
                       g.median_boundary_age_days, g.boundaries_with_vintage, g.boundaries_missing_vintage,
                       coalesce(s.active_systems, 0) AS active_systems,
                       coalesce(s.systems_with_no_boundary, 0) AS systems_with_no_boundary,
                       DATE '{as_of.isoformat()}' AS as_of_date
                FROM geographic g
                LEFT JOIN active s ON s.state = g.state AND s.sector = g.sector
                UNION ALL
                SELECT s.state, s.sector, NULL::BIGINT, NULL::BIGINT, NULL::DOUBLE,
                       a.median_boundary_age_days,
                       coalesce(a.boundaries_with_vintage, 0),
                       coalesce(a.boundaries_missing_vintage, 0),
                       s.active_systems, s.systems_with_no_boundary,
                       DATE '{as_of.isoformat()}'
                FROM active s
                LEFT JOIN state_ref r ON r.usps = s.state
                LEFT JOIN age a ON a.state_fips IS NULL AND a.sector = s.sector AND s.state = '{MISSING_STATE}'
                WHERE r.usps IS NULL
              )
              SELECT {", ".join(SCORECARD_COLUMNS)}
              FROM combined
              ORDER BY state, sector
            ) TO '{_path(destination)}' (FORMAT parquet)
            """
        )
        excess = connection.execute(
            f"""
            SELECT state, share_population_nonmodeled
            FROM read_parquet('{_path(destination)}')
            WHERE share_population_nonmodeled > 1
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()
    if excess:
        raise ValueError(f"Non-modeled population share exceeds 1 in {excess[0]}: {excess[1]}")
    return {"as_of_date": as_of.isoformat()}


def write_multi_sector_scorecard(home: Path, quarter: str, *, as_of: date | None = None) -> dict[str, object]:
    """Rebuild state_sector_scorecard.parquet across all built sectors in core and gold."""
    silver = home / "silver" / quarter
    core = home / "core" / quarter
    gold = home / "gold" / quarter
    destination = gold / "state_sector_scorecard.parquet"
    blocks = silver / "ref_block.parquet"
    states = silver / "ref_state.parquet"
    if as_of is None:
        if destination.is_file():
            con = duckdb.connect()
            try:
                row = con.execute(f"SELECT max(as_of_date) FROM read_parquet('{_path(destination)}')").fetchone()
                if row and row[0] is not None:
                    as_of = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0])[:10])
            finally:
                con.close()
        if as_of is None:
            as_of = date(2026, 9, 30)

    sys_files = [
        core / name
        for name in ("system.parquet", "electric_system.parquet", "wastewater_system.parquet", "gas_system.parquet")
        if (core / name).is_file()
    ]
    if not sys_files:
        raise ValueError("No core system tables found for scorecard")

    connection = duckdb.connect()
    try:
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.execute(
            f"""
            CREATE VIEW blocks AS
            SELECT state, block_geoid, pop20, lon, lat FROM read_parquet('{_path(blocks)}');
            CREATE VIEW state_ref AS
            SELECT state AS state_fips, usps, pop20 FROM read_parquet('{_path(states)}');
            """
        )
        sys_union = " UNION ALL ".join(
            f"SELECT system_id, sector, status, primary_state FROM read_parquet('{_path(p)}')"
            for p in sys_files
        )
        connection.execute(f"CREATE VIEW system AS {sys_union}")

        terr_branches: list[str] = []
        for tfile in ("territories_water.parquet", "territories_electric.parquet"):
            tp = gold / tfile
            if tp.is_file():
                terr_branches.append(
                    f"""
                    SELECT service_area_id, system_id, sector, primary_state,
                           CAST(source_vintage_date AS DATE) AS source_vintage_date,
                           CAST(boundary_representation AS VARCHAR) AS boundary_representation,
                           geometry
                    FROM read_parquet('{_path(tp)}')
                    """
                )
        for sa_file, sys_file in (
            ("wastewater_service_area.parquet", "wastewater_system.parquet"),
            ("gas_service_area.parquet", "gas_system.parquet"),
        ):
            sap = core / sa_file
            syp = core / sys_file
            if sap.is_file() and syp.is_file():
                cols = {r[0] for r in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{_path(sap)}')").fetchall()}
                rep_expr = "CAST(a.boundary_representation AS VARCHAR)" if "boundary_representation" in cols else "'unknown'"
                terr_branches.append(
                    f"""
                    SELECT a.service_area_id, a.system_id, a.sector, s.primary_state,
                           CAST(a.source_vintage_date AS DATE) AS source_vintage_date,
                           {rep_expr} AS boundary_representation,
                           a.geometry
                    FROM read_parquet('{_path(sap)}') a
                    JOIN read_parquet('{_path(syp)}') s USING (system_id)
                    WHERE a.is_best
                      AND a.zone_role IN ('active_retail_service', 'certified_franchise_territory')
                      AND s.status = 'active'
                    """
                )
        if not terr_branches:
            raise ValueError("No territory tables found for scorecard")
        connection.execute("CREATE TABLE territory AS " + " UNION ALL ".join(terr_branches))

        cov_branches: list[str] = []
        for cfile in ("system_block_coverage.parquet", "electric_system_block_coverage.parquet"):
            cp = gold / cfile
            if cp.is_file():
                cov_branches.append(
                    f"SELECT system_id, state, block_geoid, pop20 FROM read_parquet('{_path(cp)}')"
                )
        connection.execute(
            """
            CREATE TABLE extra_unmodeled AS
            SELECT system_id, primary_state, geometry AS geom
            FROM territory
            WHERE sector IN ('wastewater', 'natural_gas')
              AND boundary_representation = 'unmodeled'
              AND geometry IS NOT NULL
            """
        )
        n_extra = int(connection.execute("SELECT count(*) FROM extra_unmodeled").fetchone()[0])
        if n_extra > 0:
            connection.execute("CREATE INDEX extra_rtree ON extra_unmodeled USING RTREE (geom)")
            connection.execute(
                """
                CREATE TABLE extra_cov AS
                SELECT u.system_id, b.state, b.block_geoid, b.pop20
                FROM blocks b
                JOIN state_ref r ON r.state_fips = b.state
                JOIN extra_unmodeled u ON u.primary_state = r.usps AND ST_Covers(u.geom, ST_Point(b.lon, b.lat))
                """
            )
            cov_branches.append("SELECT system_id, state, block_geoid, pop20 FROM extra_cov")

        if cov_branches:
            connection.execute("CREATE VIEW coverage AS " + " UNION ALL ".join(cov_branches))
        else:
            connection.execute(
                "CREATE VIEW coverage AS SELECT NULL::VARCHAR AS system_id, NULL::VARCHAR AS state, NULL::VARCHAR AS block_geoid, NULL::BIGINT AS pop20 WHERE false"
            )

        connection.execute(
            f"""
            COPY (
              WITH state_pop AS (
                SELECT state AS state_fips, sum(pop20)::BIGINT AS population
                FROM blocks
                GROUP BY 1
              ),
              nonmodeled_block AS (
                SELECT c.state AS state_fips, t.sector, c.block_geoid, any_value(c.pop20)::BIGINT AS pop20
                FROM coverage c
                JOIN territory t USING (system_id)
                WHERE t.boundary_representation = '{UNMODELED_REPRESENTATION}'
                GROUP BY 1, 2, 3
              ),
              nonmodeled AS (
                SELECT state_fips, sector, sum(pop20)::BIGINT AS population_in_nonmodeled_boundary
                FROM nonmodeled_block
                GROUP BY 1, 2
              ),
              covered AS (
                SELECT DISTINCT t.service_area_id, c.state AS state_fips, t.source_vintage_date, t.sector
                FROM territory t
                JOIN coverage c USING (system_id)
              ),
              missed AS (
                SELECT t.service_area_id, r.state_fips, t.source_vintage_date, t.sector
                FROM territory t
                LEFT JOIN state_ref r ON r.usps = t.primary_state
                WHERE t.service_area_id NOT IN (SELECT service_area_id FROM covered)
              ),
              area AS (
                SELECT * FROM covered
                UNION ALL
                SELECT * FROM missed
              ),
              age AS (
                SELECT state_fips, sector,
                       median(date_diff('day', source_vintage_date, DATE '{as_of.isoformat()}'))
                         FILTER (WHERE source_vintage_date IS NOT NULL) AS median_boundary_age_days,
                       count(DISTINCT service_area_id) FILTER (WHERE source_vintage_date IS NOT NULL) AS boundaries_with_vintage,
                       count(DISTINCT service_area_id) FILTER (WHERE source_vintage_date IS NULL) AS boundaries_missing_vintage
                FROM area
                GROUP BY 1, 2
              ),
              active AS (
                SELECT CASE WHEN s.primary_state IS NULL THEN '{MISSING_STATE}' ELSE s.primary_state END AS state,
                       s.sector,
                       count(*)::BIGINT AS active_systems,
                       count(*) FILTER (WHERE t.system_id IS NULL)::BIGINT AS systems_with_no_boundary
                FROM system s
                LEFT JOIN (SELECT DISTINCT system_id FROM territory) t USING (system_id)
                WHERE s.status = 'active'
                GROUP BY 1, 2
              ),
              sectors AS (
                SELECT DISTINCT sector FROM active
              ),
              geographic AS (
                SELECT r.usps AS state, sectors.sector, p.population,
                       coalesce(n.population_in_nonmodeled_boundary, 0)::BIGINT AS population_in_nonmodeled_boundary,
                       a.median_boundary_age_days, coalesce(a.boundaries_with_vintage, 0) AS boundaries_with_vintage,
                       coalesce(a.boundaries_missing_vintage, 0) AS boundaries_missing_vintage
                FROM state_ref r
                CROSS JOIN sectors
                LEFT JOIN state_pop p ON p.state_fips = r.state_fips
                LEFT JOIN nonmodeled n ON n.state_fips = r.state_fips AND n.sector = sectors.sector
                LEFT JOIN age a ON a.state_fips = r.state_fips AND a.sector = sectors.sector
              ),
              combined AS (
                SELECT g.state, g.sector, g.population, g.population_in_nonmodeled_boundary,
                       CASE WHEN g.population > 0 THEN g.population_in_nonmodeled_boundary * 1.0 / g.population ELSE NULL END
                         AS share_population_nonmodeled,
                       g.median_boundary_age_days, g.boundaries_with_vintage, g.boundaries_missing_vintage,
                       coalesce(s.active_systems, 0) AS active_systems,
                       coalesce(s.systems_with_no_boundary, 0) AS systems_with_no_boundary,
                       DATE '{as_of.isoformat()}' AS as_of_date
                FROM geographic g
                LEFT JOIN active s ON s.state = g.state AND s.sector = g.sector
                UNION ALL
                SELECT s.state, s.sector, NULL::BIGINT, NULL::BIGINT, NULL::DOUBLE,
                       a.median_boundary_age_days,
                       coalesce(a.boundaries_with_vintage, 0),
                       coalesce(a.boundaries_missing_vintage, 0),
                       s.active_systems, s.systems_with_no_boundary,
                       DATE '{as_of.isoformat()}'
                FROM active s
                LEFT JOIN state_ref r ON r.usps = s.state
                LEFT JOIN age a ON a.state_fips IS NULL AND a.sector = s.sector AND s.state = '{MISSING_STATE}'
                WHERE r.usps IS NULL
              )
              SELECT {", ".join(SCORECARD_COLUMNS)}
              FROM combined
              ORDER BY state, sector
            ) TO '{_path(destination)}' (FORMAT parquet)
            """
        )
        excess = connection.execute(
            f"""
            SELECT state, share_population_nonmodeled
            FROM read_parquet('{_path(destination)}')
            WHERE share_population_nonmodeled > 1
            LIMIT 1
            """
        ).fetchone()
        rows = int(connection.execute(f"SELECT count(*) FROM read_parquet('{_path(destination)}')").fetchone()[0])
    finally:
        connection.close()
    if excess:
        raise ValueError(f"Non-modeled population share exceeds 1 in {excess[0]}: {excess[1]}")
    return {"as_of_date": as_of.isoformat(), "rows": rows}


def _path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
