"""County location for facilities and places.

A facility is located in the county polygon that contains its longitude and
latitude. A facility with no coordinates gets no edge. A place that spans
counties is located in the county whose blocks inside the place have the
largest population. Equal population uses the lower county GEOID. County
service stays on servesCounty and is not this link.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from utilitydata.core.text import require_columns
from utilitydata.electric.boundaries import load_counties
from utilitydata.registry import Source

LOCATION_COLUMNS = ("subject_id", "county_geoid", "subject_class")


def write_location_tables(
    home: Path,
    quarter: str,
    sources: list[Source],
    facilities: pd.DataFrame,
) -> dict[str, int]:
    """Write facility and place county tables beside the cross-sector core files."""
    geometries, geoids, _states = load_counties(home, sources)
    facility_rows, facility_report = facility_counties(facilities, geometries, geoids)
    blocks = pd.read_parquet(
        home / "silver" / quarter / "ref_block.parquet",
        columns=["place_geoid", "county_geoid", "pop20"],
    )
    place_rows = place_counties(blocks)
    core = home / "core" / quarter
    core.mkdir(parents=True, exist_ok=True)
    facility_rows.to_parquet(core / "facility_county.parquet", index=False)
    place_rows.to_parquet(core / "place_county.parquet", index=False)
    return facility_report | {"place_locations": len(place_rows)}


def facility_counties(
    facilities: pd.DataFrame,
    geometries: list[object],
    geoids: list[str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return one county per coordinated facility and the counts left without an edge."""
    require_columns(facilities, ("facility_id", "longitude", "latitude"), "facilities")
    if len(geometries) != len(geoids):
        raise ValueError("County geometries and GEOIDs do not match")
    missing = facilities["longitude"].isna() | facilities["latitude"].isna()
    located = facilities.loc[~missing]
    rows: list[dict[str, str]] = []
    outside = 0
    if not located.empty and geometries:
        tree = shapely.STRtree(np.asarray(geometries, dtype=object))
        points = shapely.points(located["longitude"].to_numpy(), located["latitude"].to_numpy())
        for facility_id, point in zip(located["facility_id"].astype(str), points, strict=True):
            hits = tree.query(point, predicate="intersects")
            if len(hits) == 0:
                outside += 1
                continue
            chosen = min(geoids[int(index)] for index in hits)
            rows.append({
                "subject_id": facility_id,
                "county_geoid": chosen,
                "subject_class": "facility",
            })
    elif not located.empty:
        outside = len(located)
    frame = pd.DataFrame(rows, columns=list(LOCATION_COLUMNS))
    return frame, {"without_coordinates": int(missing.sum()), "outside_counties": outside}


def place_counties(blocks: pd.DataFrame) -> pd.DataFrame:
    """Assign each place to one county by block population."""
    require_columns(blocks, ("place_geoid", "county_geoid", "pop20"), "place blocks")
    present = blocks.loc[blocks["place_geoid"].notna() & blocks["county_geoid"].notna()].copy()
    if present.empty:
        return pd.DataFrame(columns=list(LOCATION_COLUMNS))
    if bool(present["pop20"].isna().any()):
        raise ValueError("A place block is missing population")
    totals = (
        present.groupby(["place_geoid", "county_geoid"], dropna=False)["pop20"]
        .sum()
        .reset_index()
        .sort_values(["place_geoid", "pop20", "county_geoid"], ascending=[True, False, True], kind="mergesort")
    )
    winners = totals.groupby("place_geoid", sort=False).head(1)
    return pd.DataFrame({
        "subject_id": winners["place_geoid"].astype(str),
        "county_geoid": winners["county_geoid"].astype(str),
        "subject_class": "place",
    }).loc[:, list(LOCATION_COLUMNS)].reset_index(drop=True)
