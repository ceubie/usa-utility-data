"""Dissolve boundary parts and choose one best serving area per system."""

import hashlib

import geopandas as gpd
import pandas as pd

from utilitydata.core.config import AUTHORITY_RANK, BEST_ROLES, NONSERVING_ROLES
from utilitydata.core.geometry import polygonal_area_km2, union_geometries
from utilitydata.core.schema import SERVICE_AREA_COLUMNS
from utilitydata.core.text import is_missing, require_columns

PART_COLUMNS = (
    "system_id",
    "sector",
    "zone_role",
    "source_id",
    "authority",
    "grain",
    "source_vintage_date",
    "licence",
    "footprint_verified",
    "geometry",
)


def assemble_service_areas(parts: pd.DataFrame) -> gpd.GeoDataFrame:
    """Union parts that share a system, role, source, and authority, then mark the best area.

    Only active retail and certified franchise areas compete. Authority order comes
    from the config, and a newer vintage breaks a remaining tie. On-site, wholesale,
    planned, watershed, not-served, and review-required areas never win.
    """
    require_columns(parts, PART_COLUMNS, "service area parts")
    if parts.empty:
        raise ValueError("Service area build received no parts")
    if bool(parts["system_id"].isna().any()):
        raise ValueError("Service area part is missing a system id")
    if any(_missing_geometry(geometry) for geometry in parts["geometry"]):
        raise ValueError("Service area part is missing geometry")
    has_representation = "boundary_representation" in parts.columns
    rows: list[dict[str, object]] = []
    grouped = parts.groupby(["system_id", "zone_role", "source_id", "authority"], dropna=False, sort=False)
    for index, (key, group) in enumerate(grouped, start=1):
        system_id, zone_role, source_id, authority = key
        geometries = list(group["geometry"])
        if len(geometries) >= 5000:
            print(f"union {len(geometries)} parts for {system_id}", flush=True)
        geometry = union_geometries(geometries)
        row: dict[str, object] = {
            "service_area_id": _service_area_id(system_id, zone_role, source_id, authority),
            "system_id": system_id,
            "sector": _one(group["sector"], "sector"),
            "zone_role": zone_role,
            "source_id": source_id,
            "authority": authority,
            "grain": _grain(group["grain"]),
            "source_vintage_date": _newest(group["source_vintage_date"]),
            "is_best": False,
            "part_count": len(group),
            "area_km2": polygonal_area_km2(geometry),
            "footprint_verified": _footprint(group["footprint_verified"]),
            "licence": _one(group["licence"], "licence"),
            "geometry": geometry,
        }
        if has_representation:
            row["boundary_representation"] = _representation_group(group["boundary_representation"])
        rows.append(row)
        if index % 20000 == 0:
            print(f"service areas: {index} groups", flush=True)
    frame = pd.DataFrame(rows)
    if bool(frame["service_area_id"].duplicated().any()):
        raise ValueError("Service area ids collided")
    marked = mark_best(frame)
    output_columns = list(SERVICE_AREA_COLUMNS) + (["boundary_representation"] if has_representation else [])
    geo = gpd.GeoDataFrame(marked.loc[:, output_columns], geometry="geometry", crs="EPSG:4326")
    return geo.sort_values(["system_id", "zone_role", "source_id", "service_area_id"], na_position="last").reset_index(drop=True)


def mark_best(frame: pd.DataFrame) -> pd.DataFrame:
    """Set is_best on at most one eligible area per system."""
    require_columns(frame, ("system_id", "zone_role", "authority", "source_vintage_date", "source_id", "service_area_id"), "service areas")
    marked = frame.copy()
    marked["is_best"] = False
    eligible = marked["zone_role"].isin(BEST_ROLES) & marked["authority"].isin(AUTHORITY_RANK)
    if bool(eligible.any()):
        ranks = {name: position for position, name in enumerate(AUTHORITY_RANK)}
        subset = marked.loc[eligible].copy()
        subset["_authority_rank"] = subset["authority"].map(ranks)
        subset = subset.sort_values(
            ["system_id", "_authority_rank", "source_vintage_date", "source_id", "service_area_id"],
            ascending=[True, True, False, True, True],
            na_position="last",
            kind="mergesort",
        )
        winners = subset.groupby("system_id", sort=False).head(1).index
        marked.loc[winners, "is_best"] = True
    _reject_bad_best(marked)
    return marked


def _missing_geometry(geometry: object) -> bool:
    return geometry is None or geometry is pd.NA


def _reject_bad_best(frame: pd.DataFrame) -> None:
    best = frame.loc[frame["is_best"].fillna(False)]
    if best.empty:
        return
    if bool(best["zone_role"].isna().any()) or bool(best["zone_role"].isin(NONSERVING_ROLES).any()):
        raise ValueError("A non-serving role was marked as the best service area")
    if not bool(best["zone_role"].isin(BEST_ROLES).all()):
        raise ValueError("A best service area is outside the serving roles")
    if int(best.groupby("system_id").size().max()) > 1:
        raise ValueError("More than one best service area was selected for a system")


def _service_area_id(system_id: object, zone_role: object, source_id: object, authority: object) -> str:
    token = "|".join(_token(part) for part in (system_id, zone_role, source_id, authority))
    return "SA_" + hashlib.sha256(token.encode()).hexdigest()[:16]


def _token(value: object) -> str:
    if is_missing(value):
        return ""
    return str(value)


def _one(series: pd.Series, label: str):
    values = [value for value in series.dropna().unique().tolist() if not is_missing(value)]
    if len(values) > 1:
        raise ValueError(f"A service area has more than one {label}")
    if not values:
        return pd.NA
    return values[0]


def _grain(series: pd.Series) -> str | None:
    values = sorted({str(value) for value in series.dropna().tolist() if not is_missing(value)})
    if not values:
        return None
    return "|".join(values)


def _newest(series: pd.Series):
    present = series.dropna()
    if present.empty:
        return pd.NaT
    return present.max()


def _representation_group(series: pd.Series) -> str:
    values = sorted({str(value) for value in series.dropna().tolist() if not is_missing(value)})
    if not values:
        return "unknown"
    if len(values) == 1:
        return values[0]
    return "mixed"


def _footprint(series: pd.Series):
    if bool(series.isna().all()):
        return pd.NA
    if bool((series == False).any()):
        return False
    if bool(series.isna().any()):
        return pd.NA
    if bool((series == True).all()):
        return True
    return pd.NA
