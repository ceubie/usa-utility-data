"""Write the versioned drinking-water release under the data root."""

from pathlib import Path

import duckdb

from utilitydata.core.config import DEFAULT_QUARTER
from utilitydata.gold.build import build_water_gold
from utilitydata.gold.schema import TRAVIS_COUNTY_GEOID
from utilitydata.pipeline import open_release
from utilitydata.release.accuracy import (
    evaluate_truth,
    load_truth,
    population_agreement,
    write_accuracy_report,
)
from utilitydata.release.dictionary import write_dictionary
from utilitydata.release.editions import open_release_sql, split_release
from utilitydata.release.reports import (
    reject_absolute_paths,
    write_change_report,
    write_manifest,
)


def build_water_release(
    home: Path,
    registry_dir: Path,
    repository_root: Path,
    *,
    quarter: str = DEFAULT_QUARTER,
    release_id: str,
    rebuild_coverage: bool = True,
) -> dict[str, object]:
    """Build Gold if needed and write the release folder under the data root."""
    release = open_release(home, release_id)
    summary = build_water_gold(home, registry_dir, quarter=quarter, rebuild_coverage=rebuild_coverage)
    gold = home / "gold" / quarter
    prior = sorted(path.name for path in (home / "releases").glob("*") if path.is_dir() and path.name != release_id)
    split_release(gold, release)
    agreement = population_agreement(
        gold / "system_block_coverage.parquet",
        gold / "territories_water.parquet",
        home / "core" / quarter / "system.parquet",
    )
    truth_path = repository_root / "registry" / "truth" / "water.csv"
    truth = evaluate_truth(load_truth(truth_path), gold / "territories_water.parquet")
    excluded = list(summary.get("coverage", {}).get("excluded_best_areas", []))
    if not excluded:
        excluded = _excluded_best_areas(home, quarter)
    write_accuracy_report(release / "accuracy_report.md", agreement, truth, excluded_best_areas=excluded)
    write_dictionary(repository_root / "contracts" / "gold", release / "data_dictionary.md")
    write_change_report(release / "change_report.md", release_id, prior, home, quarter, gold, registry_dir)
    (release / "open_release.sql").write_text(open_release_sql(), encoding="utf-8")
    write_manifest(release, home, quarter, gold, repository_root)
    reject_absolute_paths(release)
    return {
        "release": "releases/" + release_id,
        "travis_county_served_systems": _travis(gold / "system_county_coverage.parquet"),
        "agreement": agreement.to_dict(orient="records"),
        "truth": truth,
        "gold": summary,
    }


def _travis(path: Path) -> int:
    connection = duckdb.connect()
    try:
        row = connection.execute(
            "SELECT count(DISTINCT system_id) FROM read_parquet(?) WHERE county_geoid = ? AND is_served",
            [str(path), TRAVIS_COUNTY_GEOID],
        ).fetchone()
    finally:
        connection.close()
    return int(row[0]) if row else 0


def _excluded_best_areas(home: Path, quarter: str) -> list[dict[str, object]]:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            """
            SELECT s.status,
                   CASE WHEN starts_with(s.system_id, 'SYS_LOC_') THEN 'provisional' ELSE 'other' END,
                   count(*)
            FROM read_parquet(?) a
            JOIN read_parquet(?) s USING (system_id)
            WHERE a.is_best
              AND a.zone_role IN ('active_retail_service', 'certified_franchise_territory')
              AND s.status <> 'active'
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            [
                str(home / "core" / quarter / "service_area.parquet"),
                str(home / "core" / quarter / "system.parquet"),
            ],
        ).fetchall()
    finally:
        connection.close()
    return [{"status": status, "origin": origin, "areas": int(areas)} for status, origin, areas in rows]
