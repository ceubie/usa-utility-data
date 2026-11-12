"""Release artifacts that do not need the national build."""

from pathlib import Path

import duckdb
import pytest

from utilitydata.gold.schema import TRUTH_COLUMNS
from utilitydata.release.accuracy import expected_system, load_truth, within_agreement
from utilitydata.release.editions import open_release_sql


def test_truth_file_has_no_fabricated_rows():
    frame = load_truth(Path("registry/truth/water.csv"))
    assert list(frame.columns) == list(TRUTH_COLUMNS)
    assert len(frame) == 0
    assert "Cole" not in Path("registry/truth/water.csv").read_text(encoding="utf-8")


def test_agreement_threshold_and_truth_schemes():
    assert within_agreement(100, 100) is True
    assert within_agreement(126, 100) is False
    assert within_agreement(75, 100) is True
    assert expected_system("pwsid", "090600058") == "SYS_PWS_090600058"
    assert expected_system("system_id", "SYS_LOC_abc") == "SYS_LOC_abc"


def test_built_travis_county_served_count_is_far_below_362():
    path = Path("data/gold/2026-Q4/system_county_coverage.parquet")
    if not path.is_file():
        pytest.skip("county coverage is not built")
    count = duckdb.connect().execute(
        "SELECT count(DISTINCT system_id) FROM read_parquet(?) WHERE county_geoid = ? AND is_served",
        [str(path), "48453"],
    ).fetchone()[0]
    assert int(count) < 120


def test_open_release_sql_uses_relative_paths():
    sql = open_release_sql()
    assert "internal/territories_water.parquet" in sql
    assert "shareable/territories_water.parquet" in sql
    assert "CREATE OR REPLACE VIEW state_sector_scorecard" in sql
    assert ":\\" not in sql
    assert "/Users/" not in sql
