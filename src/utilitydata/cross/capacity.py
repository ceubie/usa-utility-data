"""Sum unit capacity. A plant total repeated on each unit is rejected."""

from __future__ import annotations

import math

import pandas as pd

from utilitydata.core.config import UNIT_CAPACITY_KW_PER_MW
from utilitydata.core.text import require_columns


def resolve_plant_capacity(units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return facility capacity and the rejected plant totals.

    Capacity is the sum of unit ratings. ``turbine_count`` is not a multiplier.
    A plant total present on a unit row is rejected and is not added again.
    """
    require_columns(units, ("facility_id", "unit_capacity_mw"), "facility units")
    facility_ids = units["facility_id"]
    unit_capacity = pd.to_numeric(units["unit_capacity_mw"], errors="coerce")
    if bool((units["unit_capacity_mw"].notna() & unit_capacity.isna()).any()):
        raise ValueError("Unit capacity is not numeric")
    sums = unit_capacity.groupby(facility_ids, dropna=False).sum(min_count=1)
    incomplete = set(facility_ids.loc[unit_capacity.isna()].unique())
    if incomplete:
        sums.loc[sums.index.isin(incomplete)] = pd.NA
    capacity = sums.rename("capacity_mw").reset_index()
    rejects = _plant_total_rejects(units)
    _reject_repeated_total(units, capacity, rejects)
    return capacity, rejects


def capacity_equality(units: pd.DataFrame) -> dict[str, object]:
    """Compare the unit sum with the sum of project capacities and the plant field."""
    require_columns(units, ("facility_id", "unit_capacity_mw"), "facility units")
    capacity, rejects = resolve_plant_capacity(units)
    project = capacity["capacity_mw"]
    known = project.dropna()
    published = None if known.empty else float(math.fsum(float(value) for value in known))
    project_sum = published
    once, repeated, differences = _plant_field_totals(units, capacity)
    equal = published is not None and project_sum is not None and _close(published, project_sum)
    plant_equal = None if once is None or published is None else _close(published, once)
    return {
        "projects": int(capacity["facility_id"].nunique()),
        "units": len(units),
        "capacity_mw": published,
        "sum_of_project_capacity_mw": project_sum,
        "equal": equal,
        "source_plant_capacity_mw": once,
        "source_plant_capacity_equals_unit_sum": plant_equal,
        "repeated_plant_row_sum_mw": repeated,
        "capacity_rejects": len(rejects),
        "plant_capacity_differences": differences,
    }


def kilowatts_to_megawatts(series: pd.Series) -> pd.Series:
    """Convert kilowatts to megawatts. Nulls stay null."""
    numeric = pd.to_numeric(series, errors="coerce")
    if bool((series.notna() & numeric.isna()).any()):
        raise ValueError("Unit capacity in kilowatts is not numeric")
    return numeric / UNIT_CAPACITY_KW_PER_MW


def _plant_total_rejects(units: pd.DataFrame) -> pd.DataFrame:
    columns = ["facility_id", "source_feature_id", "plant_capacity_mw", "reason"]
    if "plant_capacity_mw" not in units.columns or not bool(units["plant_capacity_mw"].notna().any()):
        return pd.DataFrame(columns=columns)
    plant = pd.to_numeric(units["plant_capacity_mw"], errors="coerce")
    if bool((units["plant_capacity_mw"].notna() & plant.isna()).any()):
        raise ValueError("Plant capacity is not numeric")
    distinct = plant.groupby(units["facility_id"], dropna=False).nunique(dropna=True)
    repeated = units.loc[plant.notna(), ["facility_id"]].copy()
    repeated["plant_capacity_mw"] = plant.loc[plant.notna()].to_numpy()
    repeated["source_feature_id"] = (
        units.loc[plant.notna(), "source_feature_id"].to_numpy()
        if "source_feature_id" in units.columns
        else pd.NA
    )
    repeated["reason"] = repeated["facility_id"].map(
        lambda facility_id: "inconsistent_plant_capacity" if int(distinct.at[facility_id]) > 1 else "repeated_plant_total"
    )
    return repeated.loc[:, columns].reset_index(drop=True)


def _reject_repeated_total(units: pd.DataFrame, capacity: pd.DataFrame, rejects: pd.DataFrame) -> None:
    """Raise when the published sum is the plant total repeated once per unit."""
    if rejects.empty or "plant_capacity_mw" not in units.columns:
        return
    published = capacity["capacity_mw"].dropna()
    if published.empty:
        return
    published_sum = float(math.fsum(float(value) for value in published))
    plant = pd.to_numeric(units["plant_capacity_mw"], errors="coerce")
    repeated = plant.dropna()
    if repeated.empty or len(units) <= capacity["facility_id"].nunique():
        return
    repeated_sum = float(math.fsum(float(value) for value in repeated))
    distinct = plant.groupby(units["facility_id"], dropna=False).nunique(dropna=True)
    consistent = distinct.eq(1)
    once_values = plant.groupby(units["facility_id"], dropna=False).min().loc[consistent].dropna()
    if once_values.empty:
        return
    once_sum = float(math.fsum(float(value) for value in once_values))
    if not _close(once_sum, repeated_sum) and _close(published_sum, repeated_sum):
        raise ValueError("Capacity repeated the plant total once per unit")


def _plant_field_totals(units: pd.DataFrame, capacity: pd.DataFrame) -> tuple[float | None, float | None, list[dict[str, object]]]:
    if "plant_capacity_mw" not in units.columns or not bool(units["plant_capacity_mw"].notna().any()):
        return None, None, []
    plant = pd.to_numeric(units["plant_capacity_mw"], errors="coerce")
    repeated_values = plant.dropna()
    repeated = None if repeated_values.empty else float(math.fsum(float(value) for value in repeated_values))
    distinct = plant.groupby(units["facility_id"], dropna=False).nunique(dropna=True)
    consistent = distinct.eq(1)
    once_series = plant.groupby(units["facility_id"], dropna=False).min().loc[consistent].dropna()
    once = None if once_series.empty else float(math.fsum(float(value) for value in once_series))
    unit_sums = capacity.set_index("facility_id")["capacity_mw"]
    names = units.groupby("facility_id", dropna=False)["name"].first() if "name" in units.columns else None
    differences: list[dict[str, object]] = []
    for facility_id, plant_value in once_series.items():
        unit_value = unit_sums.get(facility_id)
        if unit_value is None or pd.isna(unit_value) or _close(float(plant_value), float(unit_value)):
            continue
        row: dict[str, object] = {
            "facility_id": facility_id,
            "unit_capacity_mw": float(unit_value),
            "plant_capacity_mw": float(plant_value),
        }
        if names is not None:
            row["name"] = None if pd.isna(names.get(facility_id)) else str(names.get(facility_id))
        differences.append(row)
    return once, repeated, differences


def _close(left: float, right: float) -> bool:
    scale = max(1.0, abs(left), abs(right))
    return abs(left - right) <= 1e-6 * scale
