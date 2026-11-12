"""Match facilities across identifier types. Thresholds are starting values."""

from __future__ import annotations

import math

import pandas as pd
import shapely
from pyproj import Geod
from rapidfuzz import fuzz

from utilitydata.core.config import (
    FACILITY_MATCH_DISTANCE_M,
    FACILITY_NAME_GROUP_LIMIT,
    FACILITY_NAME_SIMILARITY,
)
from utilitydata.core.text import require_columns
from utilitydata.cross.schema import MATCH_COLUMNS, empty_frame

_GEOD = Geod(ellps="WGS84")
_REQUIRED = (
    "facility_id",
    "sector",
    "source_id",
    "name_norm",
    "state",
    "longitude",
    "latitude",
)


def classify_facility_pair(
    sector_a: str,
    sector_b: str,
    distance_m: float | None,
    name_score: float,
) -> tuple[str, str]:
    """Return match, review, or unmatched for one facility pair.

    A match requires the same sector, a distance of 500 meters or less, and
    name similarity of 85 or more. A same-sector pair that misses one of those
    tests is reviewed. Different sectors do not match.
    """
    if sector_a != sector_b:
        return "unmatched", "different_sector"
    known_distance = distance_m is not None and math.isfinite(distance_m)
    within = known_distance and float(distance_m) <= FACILITY_MATCH_DISTANCE_M
    named = name_score >= FACILITY_NAME_SIMILARITY
    if within and named:
        return "match", "distance_and_name"
    if within and not named:
        return "review", "name_below_similarity"
    if named and not within:
        if known_distance:
            return "review", "beyond_match_distance"
        return "review", "distance_unknown"
    return "unmatched", "outside_distance_and_name"


def match_facilities(facilities: pd.DataFrame) -> pd.DataFrame:
    """Match named facilities from different sources. Rows are not dropped."""
    require_columns(facilities, _REQUIRED, "facilities")
    if bool(facilities["facility_id"].duplicated().any()):
        raise ValueError("Facility ids are not unique")
    named = facilities.loc[facilities["name_norm"].notna() & facilities["sector"].notna()].copy()
    if named.empty:
        return empty_frame(MATCH_COLUMNS)
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    _spatial_pairs(named, rows, seen)
    _name_pairs(named, rows, seen)
    decisions = pd.DataFrame(rows, columns=list(MATCH_COLUMNS)) if rows else empty_frame(MATCH_COLUMNS)
    decisions = _downgrade_ambiguous(decisions)
    unexpected = set(decisions["decision"].dropna()) - {"match", "review"}
    if unexpected:
        raise ValueError("Unexpected facility decision: " + ", ".join(sorted(unexpected)))
    return decisions.reset_index(drop=True)


def geodesic_meters(longitude_a: float, latitude_a: float, longitude_b: float, latitude_b: float) -> float:
    """Return the WGS84 distance in meters between two points."""
    _forward, _back, distance = _GEOD.inv(longitude_a, latitude_a, longitude_b, latitude_b)
    return abs(float(distance))


def _spatial_pairs(named: pd.DataFrame, rows: list[dict[str, object]], seen: set[tuple[str, str]]) -> None:
    located = named.loc[named["longitude"].notna() & named["latitude"].notna()]
    for _sector, group in located.groupby("sector", dropna=False):
        if len(group) < 2:
            continue
        group = group.reset_index(drop=True)
        points = shapely.points(group["longitude"].to_numpy(dtype=float), group["latitude"].to_numpy(dtype=float))
        tree = shapely.STRtree(points)
        hits = tree.query(points, predicate="dwithin", distance=0.02)
        if len(hits) == 0:
            continue
        for left, right in zip(hits[0], hits[1], strict=True):
            if int(left) >= int(right):
                continue
            _consider(group.iloc[int(left)], group.iloc[int(right)], rows, seen)


def _name_pairs(named: pd.DataFrame, rows: list[dict[str, object]], seen: set[tuple[str, str]]) -> None:
    blocked = named.loc[named["state"].notna() & named["name_norm"].notna()]
    for (_sector, _state, _name), group in blocked.groupby(["sector", "state", "name_norm"], dropna=False):
        if group["source_id"].nunique() < 2:
            continue
        if len(group) > FACILITY_NAME_GROUP_LIMIT:
            _queue_name_group(group, rows, seen)
            continue
        records = list(group.itertuples(index=False))
        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                if left.source_id == right.source_id:
                    continue
                _consider(left, right, rows, seen)


def _queue_name_group(group: pd.DataFrame, rows: list[dict[str, object]], seen: set[tuple[str, str]]) -> None:
    """Account for every facility in a name group that is too large to pair."""
    label = "group:" + "|".join(str(group.iloc[0][column]) for column in ("sector", "state", "name_norm"))
    for record in group.itertuples(index=False):
        key = (str(record.facility_id), label)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "facility_id_a": record.facility_id,
            "facility_id_b": label,
            "sector": record.sector,
            "source_id_a": record.source_id,
            "source_id_b": pd.NA,
            "distance_m": pd.NA,
            "name_score": 100.0,
            "decision": "review",
            "reason": "name_group_not_pairwise",
        })


def _consider(left: object, right: object, rows: list[dict[str, object]], seen: set[tuple[str, str]]) -> None:
    if left.source_id == right.source_id or left.sector != right.sector:
        return
    key = tuple(sorted((str(left.facility_id), str(right.facility_id))))
    if key in seen:
        return
    distance = _distance(left, right)
    score = float(fuzz.token_set_ratio(str(left.name_norm), str(right.name_norm)))
    decision, reason = classify_facility_pair(str(left.sector), str(right.sector), distance, score)
    if decision == "unmatched":
        return
    seen.add(key)
    rows.append({
        "facility_id_a": left.facility_id,
        "facility_id_b": right.facility_id,
        "sector": left.sector,
        "source_id_a": left.source_id,
        "source_id_b": right.source_id,
        "distance_m": pd.NA if distance is None else distance,
        "name_score": score,
        "decision": decision,
        "reason": reason,
    })


def _distance(left: object, right: object) -> float | None:
    if _intersects(left, right):
        return 0.0
    if any(pd.isna(value) for value in (left.longitude, left.latitude, right.longitude, right.latitude)):
        return None
    return geodesic_meters(float(left.longitude), float(left.latitude), float(right.longitude), float(right.latitude))


def _intersects(left: object, right: object) -> bool:
    geometry_a = getattr(left, "geometry", None)
    geometry_b = getattr(right, "geometry", None)
    if geometry_a is None or geometry_b is None:
        return False
    try:
        return bool(geometry_a.intersects(geometry_b))
    except (TypeError, ValueError):
        return False


def _downgrade_ambiguous(decisions: pd.DataFrame) -> pd.DataFrame:
    matched = decisions.loc[decisions["decision"].eq("match")]
    if matched.empty:
        return decisions
    counts = pd.concat([matched["facility_id_a"], matched["facility_id_b"]], ignore_index=True).value_counts()
    ambiguous = set(counts.loc[counts.gt(1)].index.astype(str))
    if not ambiguous:
        return decisions
    mask = decisions["decision"].eq("match") & (
        decisions["facility_id_a"].astype(str).isin(ambiguous) | decisions["facility_id_b"].astype(str).isin(ambiguous)
    )
    decisions.loc[mask, "decision"] = "review"
    decisions.loc[mask, "reason"] = "ambiguous_facility_match"
    return decisions
