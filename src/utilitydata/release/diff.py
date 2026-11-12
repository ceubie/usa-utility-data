"""Compare two releases: systems added, removed, or renamed, and boundaries whose area moved."""

from dataclasses import dataclass

import pandas as pd

from utilitydata.bronze.gate import exceeds_relative_drift
from utilitydata.core.config import REFRESH_AREA_DRIFT
from utilitydata.core.text import require_columns


@dataclass(frozen=True)
class SystemDiff:
    """System ids added, removed, or renamed between two releases."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    renamed: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class BoundaryDiff:
    """One boundary whose area moved by more than the refresh threshold."""

    service_area_id: str
    previous_area: float
    current_area: float


@dataclass(frozen=True)
class ReleaseDiff:
    """Changes between two releases. This is not itself a release."""

    systems: SystemDiff
    boundaries: tuple[BoundaryDiff, ...]
    areas_added: tuple[str, ...]
    areas_removed: tuple[str, ...]


def diff_release(
    previous_systems: pd.DataFrame,
    current_systems: pd.DataFrame,
    previous_areas: pd.DataFrame,
    current_areas: pd.DataFrame,
    *,
    area_drift: float = REFRESH_AREA_DRIFT,
) -> ReleaseDiff:
    """Compare system identity and boundary area. A missing named column raises."""
    systems = _systems(previous_systems, current_systems)
    boundaries, added, removed = _areas(previous_areas, current_areas, area_drift)
    return ReleaseDiff(systems, boundaries, added, removed)


def _systems(previous: pd.DataFrame, current: pd.DataFrame) -> SystemDiff:
    require_columns(previous, ("system_id", "name"), "previous systems")
    require_columns(current, ("system_id", "name"), "current systems")
    before = _identity(previous, "previous systems")
    after = _identity(current, "current systems")
    added = tuple(sorted(set(after) - set(before)))
    removed = tuple(sorted(set(before) - set(after)))
    renamed = tuple(sorted((system_id, before[system_id], after[system_id]) for system_id in set(before) & set(after) if before[system_id] != after[system_id]))
    return SystemDiff(added, removed, renamed)


def _areas(previous: pd.DataFrame, current: pd.DataFrame, threshold: float) -> tuple[tuple[BoundaryDiff, ...], tuple[str, ...], tuple[str, ...]]:
    require_columns(previous, ("service_area_id", "area_km2"), "previous boundaries")
    require_columns(current, ("service_area_id", "area_km2"), "current boundaries")
    before = _area_index(previous, "previous boundaries")
    after = _area_index(current, "current boundaries")
    changed = []
    for service_area_id in sorted(set(before) & set(after)):
        old = before[service_area_id]
        new = after[service_area_id]
        if exceeds_relative_drift(old, new, threshold):
            changed.append(BoundaryDiff(service_area_id, old, new))
    added = tuple(sorted(set(after) - set(before)))
    removed = tuple(sorted(set(before) - set(after)))
    return tuple(changed), added, removed


def _identity(frame: pd.DataFrame, label: str) -> dict[str, str]:
    if frame["system_id"].duplicated().any():
        raise ValueError(f"{label} has a duplicated system_id")
    if frame["system_id"].isna().any() or frame["name"].isna().any():
        raise ValueError(f"{label} has a missing system_id or name")
    identities = {}
    for system_id, name in zip(frame["system_id"], frame["name"], strict=True):
        if not isinstance(name, str) or not name:
            raise ValueError(f"{label} has a missing system name")
        identities[str(system_id)] = name
    return identities


def _area_index(frame: pd.DataFrame, label: str) -> dict[str, float]:
    if frame["service_area_id"].duplicated().any():
        raise ValueError(f"{label} has a duplicated service_area_id")
    if frame["service_area_id"].isna().any() or frame["area_km2"].isna().any():
        raise ValueError(f"{label} has a missing service_area_id or area")
    areas = {}
    for service_area_id, area in zip(frame["service_area_id"], frame["area_km2"], strict=True):
        if isinstance(area, bool) or not isinstance(area, (int, float)):
            raise TypeError(f"{label} area is not numeric")
        areas[str(service_area_id)] = float(area)
    return areas
