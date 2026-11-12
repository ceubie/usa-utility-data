"""Decide whether a refreshed source may replace the last good snapshot."""

from collections.abc import Sequence
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from utilitydata.core.config import REFRESH_AREA_DRIFT, REFRESH_COUNT_DRIFT


@dataclass(frozen=True)
class Measurement:
    """Counts and fields measured from one copy of a source."""

    feature_count: int | None
    area: float | None
    fields: frozenset[str]
    outside_state: int = 0
    spatial: bool = False


def exceeds_relative_drift(previous: float, current: float, threshold: float) -> bool:
    """Return whether the move is larger than the configured share of the baseline."""
    if threshold < 0:
        raise ValueError("Drift threshold cannot be negative")
    if previous < 0 or current < 0:
        raise ValueError("Count and area cannot be negative")
    if previous == 0:
        return current != 0
    return abs(current - previous) / previous > threshold


def count_outside_state(geometries: Sequence[BaseGeometry | None], state: BaseGeometry) -> int:
    """Count shapes that miss the expected state. A missing shape raises."""
    outside = 0
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            raise ValueError("A shape is missing; it was not dropped")
        if not geometry.intersects(state):
            outside += 1
    return outside


def evaluate_gate(
    previous: Measurement,
    current: Measurement,
    mapped_fields: frozenset[str],
    *,
    count_drift: float = REFRESH_COUNT_DRIFT,
    area_drift: float = REFRESH_AREA_DRIFT,
) -> tuple[str, ...]:
    """Return the reasons a source must keep its last good bytes."""
    failures: list[str] = []
    failures.extend(_count_failure(previous.feature_count, current.feature_count, count_drift))
    failures.extend(_area_failure(previous.area, current.area, area_drift))
    missing = sorted(mapped_fields - current.fields)
    if missing:
        failures.append("mapped field disappeared: " + ", ".join(missing))
    if current.outside_state < 0:
        raise ValueError("Outside-state count cannot be negative")
    if current.outside_state:
        failures.append(f"{current.outside_state} shapes fall outside the expected state")
    return tuple(failures)


def _count_failure(previous: int | None, current: int | None, threshold: float) -> tuple[str, ...]:
    if previous is None and current is None:
        return ()
    if previous is None or current is None:
        return ("feature count is missing",)
    if exceeds_relative_drift(float(previous), float(current), threshold):
        return (f"feature count moved from {previous} to {current}",)
    return ()


def _area_failure(previous: float | None, current: float | None, threshold: float) -> tuple[str, ...]:
    if previous is None and current is None:
        return ()
    if previous is None or current is None:
        return ("total area is missing",)
    if exceeds_relative_drift(previous, current, threshold):
        return (f"total area moved from {previous} to {current}",)
    return ()
