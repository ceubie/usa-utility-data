"""Split Gold tables into internal and shareable editions."""

from pathlib import Path

import duckdb
import geopandas as gpd

from utilitydata.core.config import RESTRICTED_LICENCES, SHAREABLE_LICENCES

ATTRIBUTE_TABLES = (
    "system_block_coverage.parquet",
    "system_county_coverage.parquet",
    "system_place_coverage.parquet",
    "system_tract_coverage.parquet",
    "water_facilities.parquet",
    "water_compliance_summary.parquet",
    "entity_search.parquet",
)
GEO_TABLES = ("territories_water.parquet", "service_area_display.parquet")
SECTOR_COVERAGE_TABLES = tuple(
    f"{prefix}_system_{level}_coverage.parquet"
    for prefix in ("electric", "wastewater", "gas")
    for level in ("block", "county", "place", "tract")
)
SECTOR_TERRITORY_TABLES = (
    "territories_electric.parquet",
    "territories_wastewater.parquet",
    "territories_gas.parquet",
)
VIEW_TABLES = tuple(
    name.removesuffix(".parquet")
    for name in (*ATTRIBUTE_TABLES, *GEO_TABLES, *SECTOR_COVERAGE_TABLES, *SECTOR_TERRITORY_TABLES)
)


def split_release(gold: Path, release: Path) -> None:
    """Copy each licensed table into exactly one edition."""
    (release / "internal").mkdir(parents=True, exist_ok=True)
    (release / "shareable").mkdir(parents=True, exist_ok=True)
    for name in ATTRIBUTE_TABLES:
        _split_attribute(gold / name, release)
    for name in GEO_TABLES:
        _split_geographic(gold / name, release)
    destination = release / "internal" / "state_sector_scorecard.parquet"
    destination.write_bytes((gold / "state_sector_scorecard.parquet").read_bytes())


def open_release_sql() -> str:
    """Views that read edition files with paths relative to the release folder."""
    lines = [
        "-- Run this from inside the release folder.",
        "-- Unknown and restricted licences are in internal/. Shareable licences are in shareable/.",
        "",
    ]
    for name in VIEW_TABLES:
        lines.extend([
            f"CREATE OR REPLACE VIEW {name} AS",
            f"SELECT * FROM read_parquet('internal/{name}.parquet')",
            "UNION ALL BY NAME",
            f"SELECT * FROM read_parquet('shareable/{name}.parquet');",
            "",
        ])
    lines.extend([
        "CREATE OR REPLACE VIEW state_sector_scorecard AS",
        "SELECT * FROM read_parquet('internal/state_sector_scorecard.parquet');",
        "",
    ])
    return "\n".join(lines)


def split_sector_table(source: Path, release: Path, *, geographic: bool) -> None:
    """Copy one sector table into the two editions. A missing file is an error."""
    if not source.is_file():
        raise ValueError(f"Sector release file is missing: {source.name}")
    if geographic:
        _split_geographic(source, release)
    else:
        _split_attribute(source, release)


def _split_attribute(source: Path, release: Path) -> None:
    allowed = ", ".join("'" + value + "'" for value in sorted(SHAREABLE_LICENCES | RESTRICTED_LICENCES))
    connection = duckdb.connect()
    try:
        query = f"SELECT count(*) FROM read_parquet('{_path(source)}') WHERE licence IS NULL OR licence NOT IN ({allowed})"
        bad = connection.execute(query).fetchone()
        if bad and int(bad[0]):
            raise ValueError(f"{source.name} has a null or unclassified licence")
        for folder, licences in (("internal", RESTRICTED_LICENCES), ("shareable", SHAREABLE_LICENCES)):
            quoted = ", ".join("'" + value + "'" for value in sorted(licences))
            destination = release / folder / source.name
            connection.execute(
                f"""
                COPY (
                  SELECT * FROM read_parquet('{_path(source)}') WHERE licence IN ({quoted})
                ) TO '{_path(destination)}' (FORMAT parquet)
                """
            )
        total = _count(connection, source)
        internal = _count(connection, release / "internal" / source.name)
        shareable = _count(connection, release / "shareable" / source.name)
    finally:
        connection.close()
    if internal + shareable != total:
        raise ValueError(f"{source.name} did not split cleanly across editions")


def _split_geographic(source: Path, release: Path) -> None:
    frame = gpd.read_parquet(source)
    unknown = set(frame["licence"].dropna().astype(str)) - SHAREABLE_LICENCES - RESTRICTED_LICENCES
    if unknown or bool(frame["licence"].isna().any()):
        raise ValueError(f"{source.name} has a null or unclassified licence")
    _write_geo(frame.loc[frame["licence"].isin(RESTRICTED_LICENCES)], release / "internal" / source.name)
    _write_geo(frame.loc[frame["licence"].isin(SHAREABLE_LICENCES)], release / "shareable" / source.name)


def _write_geo(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(frame, geometry="geometry", crs="EPSG:4326").to_parquet(path, index=False)


def _count(connection: duckdb.DuckDBPyConnection, path: Path) -> int:
    row = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()
    return int(row[0]) if row else 0


def _path(path: Path) -> str:
    text = path.resolve().as_posix()
    if "'" in text:
        raise ValueError("A data path contains a quote")
    return text
