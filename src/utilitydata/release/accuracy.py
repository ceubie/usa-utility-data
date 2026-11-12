"""Population agreement and the verified point truth set."""

from pathlib import Path

import duckdb
import pandas as pd

from utilitydata.core.config import POPULATION_AGREEMENT
from utilitydata.core.text import require_columns
from utilitydata.gold.schema import TRUTH_COLUMNS


def load_truth(path: Path) -> pd.DataFrame:
    """Read the truth file. Rows are not invented and verified_by is not filled in."""
    if not path.is_file():
        raise ValueError("Truth file is missing: registry/truth/water.csv")
    frame = pd.read_csv(path, dtype="string")
    require_columns(frame, TRUTH_COLUMNS, "water truth")
    return frame.loc[:, list(TRUTH_COLUMNS)]


def within_agreement(block_population: int, reported: int) -> bool:
    """Return whether block population is within the configured fraction of the reported value."""
    if reported <= 0:
        raise ValueError("Reported population must be positive to measure agreement")
    return abs(block_population - reported) / reported <= POPULATION_AGREEMENT


def population_agreement(block_coverage: Path, territories: Path, systems: Path) -> pd.DataFrame:
    """Compare block population in the best area with reported population, by authority and origin."""
    limit = POPULATION_AGREEMENT
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        frame = connection.execute(
            f"""
            WITH pop AS (
              SELECT system_id, sum(pop20)::BIGINT AS block_pop
              FROM read_parquet('{_path(block_coverage)}')
              GROUP BY 1
            ),
            base AS (
              SELECT t.authority,
                     CASE
                       WHEN t.system_id LIKE 'SYS_LOC_%' THEN 'provisional'
                       WHEN s.in_federal_registry THEN 'federal_registry'
                       ELSE 'not_in_federal_registry'
                     END AS origin,
                     s.population_served,
                     coalesce(p.block_pop, 0)::BIGINT AS block_pop
              FROM read_parquet('{_path(territories)}') t
              JOIN read_parquet('{_path(systems)}') s USING (system_id)
              LEFT JOIN pop p USING (system_id)
            )
            SELECT authority, origin,
                   count(*) FILTER (WHERE population_served > 0) AS comparable,
                   count(*) FILTER (
                     WHERE population_served > 0
                       AND abs(block_pop - population_served) * 1.0 / population_served <= {limit}
                   ) AS within_25,
                   count(*) FILTER (WHERE population_served IS NULL) AS null_population,
                   count(*) FILTER (WHERE population_served = 0) AS zero_population,
                   count(*) AS systems
            FROM base
            GROUP BY 1, 2
            ORDER BY 1, 2
            """
        ).fetchdf()
    finally:
        connection.close()
    return frame


def evaluate_truth(frame: pd.DataFrame, territories: Path) -> dict[str, object]:
    """Point-test truth rows. An empty file has zero verified rows."""
    require_columns(frame, TRUTH_COLUMNS, "water truth")
    if frame.empty:
        return {"verified_rows": 0, "passed": 0, "failed": 0}
    prepared = frame.copy()
    prepared["lat_num"] = pd.to_numeric(prepared["lat"], errors="coerce")
    prepared["lon_num"] = pd.to_numeric(prepared["lon"], errors="coerce")
    if bool(prepared["lat_num"].isna().any()) or bool(prepared["lon_num"].isna().any()):
        raise ValueError("A truth row has a non-numeric latitude or longitude")
    prepared["system_id"] = [
        expected_system(scheme, identifier)
        for scheme, identifier in zip(prepared["expected_scheme"], prepared["expected_id"], strict=True)
    ]
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        connection.register("truth", prepared[["system_id", "lon_num", "lat_num"]])
        rows = connection.execute(
            f"""
            SELECT t.system_id,
                   count(a.system_id) > 0
                     AND bool_or(ST_Covers(a.geometry, ST_Point(t.lon_num, t.lat_num))) AS covered
            FROM truth t
            LEFT JOIN read_parquet('{_path(territories)}') a USING (system_id)
            GROUP BY 1
            """
        ).fetchall()
    finally:
        connection.close()
    failed = [system_id for system_id, covered in rows if not covered]
    return {"verified_rows": len(frame), "passed": len(rows) - len(failed), "failed": len(failed)}


def expected_system(scheme: object, identifier: object) -> str:
    """Map a truth scheme to a system id. Other schemes raise."""
    if scheme == "pwsid":
        return "SYS_PWS_" + str(identifier)
    if scheme == "system_id":
        return str(identifier)
    raise ValueError(f"Truth scheme is not supported: {scheme}")


def write_accuracy_report(
    destination: Path,
    agreement: pd.DataFrame,
    truth: dict[str, object],
    *,
    excluded_best_areas: list[dict[str, object]],
) -> None:
    """Write the population comparison and the verified truth-row count."""
    lines = [
        "# Accuracy report",
        "",
        "Block population is the 2020 population of blocks whose internal point falls in the active system's best serving area.",
        "A system is within 25 percent when the absolute relative difference from population_served is at most the configured agreement threshold.",
        "Systems with a null or zero reported population are counted separately and are not in the denominator.",
        "Provisional SYS_LOC_ systems are not mixed into the federal rows.",
        "",
        "## Population within 25 percent",
        "",
        "| Authority | Origin | Comparable | Within 25 percent | Share | Null population | Zero population |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in agreement.itertuples(index=False):
        share = ""
        if row.comparable:
            share = f"{row.within_25 / row.comparable:.4f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.authority),
                    str(row.origin),
                    str(int(row.comparable)),
                    str(int(row.within_25)),
                    share,
                    str(int(row.null_population)),
                    str(int(row.zero_population)),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Provisional systems held out of coverage", ""])
    lines.append("Provisional systems enter coverage only when they are active and have a best serving area.")
    lines.append("These best serving areas belong to systems that are not active, so they are excluded from the percentages above.")
    lines.append("")
    if excluded_best_areas:
        for item in excluded_best_areas:
            lines.append(f"- {item['origin']}, status {item['status']}: {item['areas']} best serving areas")
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Verified truth rows",
            "",
            f"Verified truth rows: {int(truth['verified_rows'])}.",
            f"Point tests passed: {int(truth['passed'])}. Point tests failed: {int(truth['failed'])}.",
            "",
            "The truth file is registry/truth/water.csv. No rows were added and verified_by was not set.",
            "",
        ]
    )
    destination.write_text("\n".join(lines), encoding="utf-8")


def _path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
