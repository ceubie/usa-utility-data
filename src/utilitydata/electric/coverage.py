"""Block coverage for active electric retail territories.

Block assignment uses the same internal-point predicate as drinking water.
The shared writer lives in ``sectors.coverage``. This module adds the
state-outline check, which is electric-specific. Shares above 1 stop the build.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from utilitydata.core.config import ELECTRIC_BEST_AREA_LAND_RATIO
from utilitydata.core.geometry import polygonal_area_km2
from utilitydata.registry import Source
from utilitydata.sectors.coverage import build_sector_coverage, write_territories
from utilitydata.silver.boundaries import _load_state_regions

__all__ = ["build_electric_coverage", "build_state_land_ratios", "write_territories"]


def build_electric_coverage(
    *,
    territories: Path,
    blocks: Path,
    states: Path,
    output: Path,
    work: Path,
    home: Path,
    sources: list[Source],
    quarter: str,
) -> dict[str, object]:
    """Write block, county, place, and tract coverage for the best electric areas."""
    result = build_sector_coverage(
        sector="electric",
        file_prefix="electric",
        territories=territories,
        blocks=blocks,
        output=output,
        work=work,
    )
    areas = gpd.read_parquet(territories)
    ratios = build_state_land_ratios(areas, blocks, states, home, sources, quarter)
    _require_land_ratios(ratios)
    result["land_ratios"] = ratios.to_dict(orient="records")
    return result


def build_state_land_ratios(
    areas: gpd.GeoDataFrame,
    blocks: Path,
    states: Path,
    home: Path,
    sources: list[Source],
    quarter: str,
) -> pd.DataFrame:
    """Union best areas inside each state polygon and divide by block land area."""
    if states.parent.name != quarter:
        raise ValueError("State reference quarter does not match the electric build")
    reference = pd.read_parquet(states, columns=["state", "usps"])
    reference["state"] = reference["state"].astype(str).str.zfill(2)
    connection = duckdb.connect()
    try:
        land = connection.execute(
            """
            SELECT state, sum(aland20)::DOUBLE / 1000000.0 AS land_km2
            FROM read_parquet(?)
            GROUP BY 1
            """,
            [str(blocks)],
        ).fetchdf()
    finally:
        connection.close()
    land["state"] = land["state"].astype(str).str.zfill(2)
    land = land.merge(reference, on="state", how="inner")
    geometries, codes = _load_state_regions(home, sources, states)
    code_to_land = {str(usps): float(value) for usps, value in zip(land["usps"], land["land_km2"], strict=True)}
    rows = []
    tree = shapely.STRtree(np.asarray(areas.geometry.values, dtype=object))
    for geometry, code in zip(geometries, codes, strict=True):
        code = str(code)
        hits = tree.query(geometry, predicate="intersects")
        land_km2 = code_to_land.get(code)
        if land_km2 is None or land_km2 <= 0 or len(hits) == 0:
            rows.append({"usps": code, "land_km2": land_km2, "union_km2": 0.0, "land_ratio": 0.0})
            continue
        pieces = [areas.geometry.iloc[int(index)].intersection(geometry) for index in hits]
        pieces = [piece for piece in pieces if piece is not None and not piece.is_empty]
        if not pieces:
            rows.append({"usps": code, "land_km2": land_km2, "union_km2": 0.0, "land_ratio": 0.0})
            continue
        union = shapely.union_all(pieces) if len(pieces) > 1 else pieces[0]
        union_km2 = polygonal_area_km2(union)
        outline_km2 = polygonal_area_km2(geometry)
        rows.append({
            "usps": code,
            "land_km2": land_km2,
            "outline_km2": outline_km2,
            "union_km2": union_km2,
            "land_ratio": union_km2 / land_km2,
            "outline_ratio": union_km2 / outline_km2 if outline_km2 else None,
        })
    return pd.DataFrame(rows).sort_values("land_ratio", ascending=False)


def _require_land_ratios(ratios: pd.DataFrame) -> None:
    """Reject a best-area union that is far larger than the state outline.

    Comparing the same union with land area can exceed the limit where county
    polygons include large water bodies. That comparison is still reported.
    """
    if "outline_ratio" not in ratios.columns:
        raise ValueError("Land ratios are missing the state-outline comparison")
    outside = ratios.loc[ratios["outline_ratio"].fillna(0) >= ELECTRIC_BEST_AREA_LAND_RATIO]
    if not outside.empty:
        example = outside.sort_values("outline_ratio", ascending=False).iloc[0]
        raise ValueError(
            f"Best-area total in {example['usps']} is {float(example['outline_ratio']):.3f} times the state outline"
        )
