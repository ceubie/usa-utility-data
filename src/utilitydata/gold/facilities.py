"""Drinking-water facilities and the violation summary.

``--->`` in ``NON_COMPL_PER_END_DATE_unparsed`` is an open-ended period. It is
never read as a date. The typed end-date column stays null for that token.
"""

import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from utilitydata.core.config import COMPLIANCE_WINDOW_YEARS
from utilitydata.gold.schema import COMPLIANCE_COLUMNS, OPEN_ENDED_DATE

_QUARTER = re.compile(r"^([0-9]{4})Q([1-4])$")
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def submission_as_of(token: str) -> date:
    """Return the last day of an SDWA submission quarter such as ``2026Q3``."""
    match = _QUARTER.fullmatch(token)
    if match is None:
        raise ValueError(f"Unrecognized submission quarter: {token}")
    year = int(match.group(1))
    quarter = int(match.group(2))
    month, day = _QUARTER_END[quarter]
    return date(year, month, day)


def build_facilities(
    facilities: Path,
    systems: pd.DataFrame,
    destination: Path,
    *,
    licence: str,
    source_id: str,
) -> int:
    """Write one row per SDWA facility. A PWSID with no system raises."""
    _require_lookup(systems)
    connection = duckdb.connect()
    try:
        connection.register("systems", systems)
        missing = connection.execute(
            f"""
            SELECT f.PWSID
            FROM read_parquet('{_path(facilities)}') f
            ANTI JOIN systems s ON s.pwsid = f.PWSID
            LIMIT 1
            """
        ).fetchone()
        if missing:
            raise ValueError(f"SDWA facility PWSID has no system: {missing[0]}")
        duplicated = connection.execute(
            f"""
            SELECT PWSID, FACILITY_ID, count(*) AS n
            FROM read_parquet('{_path(facilities)}')
            GROUP BY 1, 2
            HAVING n > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicated:
            raise ValueError(f"SDWA facility id is duplicated: {duplicated[0]} {duplicated[1]}")
        connection.execute(
            f"""
            COPY (
              SELECT s.system_id, f.PWSID AS pwsid, f.FACILITY_ID AS facility_id,
                     f.FACILITY_NAME AS facility_name, f.STATE_FACILITY_ID AS state_facility_id,
                     f.FACILITY_ACTIVITY_CODE AS activity_code,
                     f.FACILITY_DEACTIVATION_DATE AS deactivation_date,
                     f.FACILITY_DEACTIVATION_DATE_unparsed AS deactivation_date_unparsed,
                     f.FACILITY_TYPE_CODE AS facility_type_code,
                     f.WATER_TYPE_CODE AS water_type_code,
                     f.AVAILABILITY_CODE AS availability_code,
                     f.IS_SOURCE_IND AS is_source_ind,
                     f.SELLER_PWSID AS seller_pwsid,
                     f.SELLER_PWS_NAME AS seller_pws_name,
                     f.FILTRATION_STATUS_CODE AS filtration_status_code,
                     f.FIRST_REPORTED_DATE AS first_reported_date,
                     f.LAST_REPORTED_DATE AS last_reported_date,
                     f.SUBMISSIONYEARQUARTER AS submission_year_quarter,
                     '{licence}' AS licence,
                     '{source_id}' AS source_id,
                     s.in_federal_registry
              FROM read_parquet('{_path(facilities)}') f
              JOIN systems s ON s.pwsid = f.PWSID
              ORDER BY s.system_id, f.FACILITY_ID
            ) TO '{_path(destination)}' (FORMAT parquet)
            """
        )
        written = connection.execute(f"SELECT count(*) FROM read_parquet('{_path(destination)}')").fetchone()
        source_rows = connection.execute(f"SELECT count(*) FROM read_parquet('{_path(facilities)}')").fetchone()
    finally:
        connection.close()
    if written is None or source_rows is None or int(written[0]) != int(source_rows[0]):
        raise ValueError("Facility rows were lost while linking them to systems")
    return int(written[0])


def build_compliance(
    violations: Path,
    systems: pd.DataFrame,
    destination: Path,
    *,
    licence: str,
    source_id: str,
) -> dict[str, object]:
    """Summarize violations by system for the configured 3-year and 10-year windows."""
    if COMPLIANCE_WINDOW_YEARS != (3, 10):
        raise ValueError("Compliance columns are violations_3y and violations_10y")
    _require_lookup(systems)
    connection = duckdb.connect()
    try:
        quarters = connection.execute(
            f"SELECT DISTINCT SUBMISSIONYEARQUARTER FROM read_parquet('{_path(violations)}')"
        ).fetchall()
        if len(quarters) != 1 or quarters[0][0] is None:
            raise ValueError(f"Violations do not have one submission quarter: {quarters}")
        as_of = submission_as_of(str(quarters[0][0]))
        conflicts = connection.execute(
            f"""
            SELECT PWSID, VIOLATION_ID
            FROM read_parquet('{_path(violations)}')
            WHERE VIOLATION_ID IS NOT NULL
            GROUP BY 1, 2
            HAVING min(NON_COMPL_PER_BEGIN_DATE) IS DISTINCT FROM max(NON_COMPL_PER_BEGIN_DATE)
                OR min(NON_COMPL_PER_END_DATE) IS DISTINCT FROM max(NON_COMPL_PER_END_DATE)
                OR (count(*) FILTER (WHERE NON_COMPL_PER_END_DATE_unparsed = '{OPEN_ENDED_DATE}') > 0
                    AND count(*) FILTER (WHERE NON_COMPL_PER_END_DATE IS NOT NULL) > 0)
                OR count(DISTINCT IS_HEALTH_BASED_IND) FILTER (WHERE IS_HEALTH_BASED_IND IS NOT NULL) > 1
            LIMIT 1
            """
        ).fetchall()
        if conflicts:
            raise ValueError(f"A violation has conflicting dates or health flags: {conflicts[0][0]} {conflicts[0][1]}")
        dated_without_id = connection.execute(
            f"""
            SELECT count(*)
            FROM read_parquet('{_path(violations)}')
            WHERE VIOLATION_ID IS NULL
              AND (NON_COMPL_PER_BEGIN_DATE IS NOT NULL
                   OR NON_COMPL_PER_END_DATE IS NOT NULL
                   OR NON_COMPL_PER_END_DATE_unparsed IS NOT NULL)
            """
        ).fetchall()
        connection.register("systems", systems)
        missing = connection.execute(
            f"""
            SELECT v.PWSID
            FROM read_parquet('{_path(violations)}') v
            ANTI JOIN systems s ON s.pwsid = v.PWSID
            LIMIT 1
            """
        ).fetchall()
        if missing:
            raise ValueError(f"SDWA violation PWSID has no system: {missing[0][0]}")
        recent, decade = COMPLIANCE_WINDOW_YEARS
        as_of_sql = f"DATE '{as_of.isoformat()}'"
        in_3y = _window_sql("begin_date", "end_date", "open_ended", as_of_sql, recent)
        in_10y = _window_sql("begin_date", "end_date", "open_ended", as_of_sql, decade)
        connection.execute(
            f"""
            COPY (
              WITH raw AS (
                SELECT * FROM read_parquet('{_path(violations)}')
              ),
              violation AS (
                SELECT PWSID, VIOLATION_ID,
                       min(NON_COMPL_PER_BEGIN_DATE) AS begin_date,
                       min(NON_COMPL_PER_END_DATE) AS end_date,
                       count(*) FILTER (WHERE NON_COMPL_PER_END_DATE_unparsed = '{OPEN_ENDED_DATE}') > 0 AS open_ended,
                       count(*) FILTER (WHERE IS_HEALTH_BASED_IND = 'Y') > 0 AS health_based
                FROM raw
                WHERE VIOLATION_ID IS NOT NULL
                GROUP BY 1, 2
              ),
              marked AS (
                SELECT *,
                       {in_3y} AS in_3y,
                       {in_10y} AS in_10y,
                       open_ended AND (begin_date IS NULL OR begin_date <= DATE '{as_of}') AS is_open,
                       NOT open_ended AND begin_date IS NULL AND end_date IS NULL AS is_undated
                FROM violation
              ),
              rolled AS (
                SELECT PWSID,
                       count(*) FILTER (WHERE in_3y) AS violations_3y,
                       count(*) FILTER (WHERE in_10y) AS violations_10y,
                       count(*) FILTER (WHERE in_3y AND health_based) AS health_based_3y,
                       count(*) FILTER (WHERE in_10y AND health_based) AS health_based_10y,
                       count(*) FILTER (WHERE is_open) AS open_violations,
                       count(*) FILTER (WHERE is_undated) AS undated_violations,
                       count(*) FILTER (WHERE NOT in_10y AND NOT is_undated) AS outside_10y,
                       count(*) AS violation_rows
                FROM marked
                GROUP BY 1
              ),
              enforcement AS (
                SELECT PWSID, count(*) AS enforcement_rows_without_violation
                FROM raw
                WHERE VIOLATION_ID IS NULL
                GROUP BY 1
              ),
              pwids AS (
                SELECT PWSID FROM rolled
                UNION
                SELECT PWSID FROM enforcement
              )
              SELECT s.system_id, p.PWSID AS pwsid,
                     coalesce(r.violations_3y, 0) AS violations_3y,
                     coalesce(r.violations_10y, 0) AS violations_10y,
                     coalesce(r.health_based_3y, 0) AS health_based_3y,
                     coalesce(r.health_based_10y, 0) AS health_based_10y,
                     coalesce(r.open_violations, 0) AS open_violations,
                     coalesce(r.undated_violations, 0) AS undated_violations,
                     coalesce(r.outside_10y, 0) AS outside_10y,
                     coalesce(e.enforcement_rows_without_violation, 0) AS enforcement_rows_without_violation,
                     DATE '{as_of}' AS as_of_date,
                     '{licence}' AS licence,
                     '{source_id}' AS source_id,
                     s.in_federal_registry
              FROM pwids p
              JOIN systems s ON s.pwsid = p.PWSID
              LEFT JOIN rolled r ON r.PWSID = p.PWSID
              LEFT JOIN enforcement e ON e.PWSID = p.PWSID
              ORDER BY s.system_id
            ) TO '{_path(destination)}' (FORMAT parquet)
            """
        )
        broken = connection.execute(
            f"""
            WITH actual AS (
              SELECT PWSID, count(DISTINCT VIOLATION_ID) AS n
              FROM read_parquet('{_path(violations)}')
              WHERE VIOLATION_ID IS NOT NULL
              GROUP BY 1
            )
            SELECT count(*)
            FROM read_parquet('{_path(destination)}') d
            LEFT JOIN actual a ON a.PWSID = d.pwsid
            WHERE d.violations_3y > d.violations_10y
               OR d.health_based_3y > d.violations_3y
               OR d.health_based_10y > d.violations_10y
               OR d.violations_10y + d.outside_10y + d.undated_violations
                    IS DISTINCT FROM coalesce(a.n, 0)
            """
        ).fetchall()
    finally:
        connection.close()
    if broken and int(broken[0][0]):
        raise ValueError("Violation windows do not reconcile")
    return {
        "as_of_date": as_of.isoformat(),
        "enforcement_rows_with_dates": int(dated_without_id[0][0]) if dated_without_id else 0,
        "rows": _row_count(destination),
    }


def _window_sql(begin: str, end: str, open_ended: str, as_of: str, years: int) -> str:
    start = f"({as_of} - INTERVAL {int(years)} YEAR)"
    return f"""(
      ({open_ended} AND ({begin} IS NULL OR {begin} <= {as_of}))
      OR (NOT {open_ended} AND {end} IS NOT NULL AND {end} >= {start} AND ({begin} IS NULL OR {begin} <= {as_of}))
      OR (NOT {open_ended} AND {end} IS NULL AND {begin} IS NOT NULL AND {begin} >= {start} AND {begin} <= {as_of})
    )"""


def _require_lookup(systems: pd.DataFrame) -> None:
    missing = [name for name in ("system_id", "pwsid", "in_federal_registry") if name not in systems.columns]
    if missing:
        raise ValueError(f"Facility system lookup is missing columns: {', '.join(missing)}")
    if bool(systems["pwsid"].duplicated().any()):
        raise ValueError("Facility system lookup has a duplicated PWSID")


def _row_count(path: Path) -> int:
    frame = pd.read_parquet(path, columns=["system_id"])
    if list(pd.read_parquet(path, columns=list(COMPLIANCE_COLUMNS[:1])).columns) != ["system_id"]:
        raise ValueError("Compliance output is missing system_id")
    return len(frame)


def _path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
