"""CWNS flow and population rows.

The total flow row is the row whose flow type is the configured total value.
A later component row is not a substitute. Population prefers the total
receiving-treatment row when that type is present, and otherwise keeps the
only row. Several remaining rows are rejected instead of keeping the last one.
"""

from __future__ import annotations

import pandas as pd

from utilitydata.core.config import (
    CWNS_POPULATION_TYPES,
    CWNS_PREFERRED_POPULATION_TYPE,
    CWNS_TOTAL_FLOW_TYPE,
)
from utilitydata.core.text import require_columns


def select_total_flow(
    frame: pd.DataFrame,
    *,
    id_column: str,
    type_column: str,
    value_column: str,
    total_value: str = CWNS_TOTAL_FLOW_TYPE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep one total-flow row per id. Component rows are counted, not silently dropped."""
    require_columns(frame, (id_column, type_column, value_column), "flow")
    if not total_value:
        raise ValueError("Total flow type is not named")
    if total_value not in set(frame[type_column].dropna()):
        raise ValueError(f"{type_column} has no {total_value!r} row")
    kept_indexes: list[object] = []
    dispositions: list[dict[str, object]] = []
    for identifier, group in frame.groupby(id_column, dropna=False, sort=False):
        matches = group.index[group[type_column].eq(total_value)].tolist()
        if len(matches) == 1:
            kept_indexes.append(matches[0])
            reason = None
        elif len(matches) == 0:
            reason = "missing_total_flow"
        else:
            reason = "ambiguous_total_flow"
        for index in group.index:
            if reason is None and index == matches[0]:
                continue
            dispositions.append({
                "id": identifier,
                "flow_type": group.at[index, type_column],
                "reason": "component_flow" if reason is None else reason,
            })
    kept = frame.loc[kept_indexes].reset_index(drop=True)
    rejected = pd.DataFrame(dispositions, columns=["id", "flow_type", "reason"])
    if len(kept) + len(rejected) != len(frame):
        raise ValueError("Flow rows do not reconcile")
    if not kept.empty and not bool(kept[type_column].eq(total_value).all()):
        raise ValueError("A kept flow row is not the total flow type")
    return kept, rejected


def select_population(
    frame: pd.DataFrame,
    *,
    id_column: str,
    type_column: str,
    value_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep the total receiving-treatment row, or the only row. Do not keep the last of several."""
    require_columns(frame, (id_column, type_column, value_column), "population")
    observed = {value for value in frame[type_column].tolist() if value is not None and not (isinstance(value, float) and pd.isna(value)) and value != ""}
    unexpected = sorted(observed - CWNS_POPULATION_TYPES)
    if unexpected or bool(frame[type_column].isna().any()) or bool(frame[type_column].eq("").any()):
        detail = ", ".join(unexpected) if unexpected else "null"
        raise ValueError(f"Unmapped population type: {detail}")
    kept_indexes: list[object] = []
    dispositions: list[dict[str, object]] = []
    for identifier, group in frame.groupby(id_column, dropna=False, sort=False):
        preferred = group.index[group[type_column].eq(CWNS_PREFERRED_POPULATION_TYPE)].tolist()
        if len(preferred) == 1:
            chosen = preferred[0]
            reason = None
        elif len(preferred) > 1 or len(group) != 1:
            chosen = None
            reason = "ambiguous_population"
        else:
            chosen = group.index[0]
            reason = None
        if chosen is not None:
            kept_indexes.append(chosen)
        for index in group.index:
            if chosen is not None and index == chosen:
                continue
            dispositions.append({
                "id": identifier,
                "population_type": group.at[index, type_column],
                "reason": "other_population_type" if reason is None else reason,
            })
    kept = frame.loc[kept_indexes].reset_index(drop=True)
    rejected = pd.DataFrame(dispositions, columns=["id", "population_type", "reason"])
    if len(kept) + len(rejected) != len(frame):
        raise ValueError("Population rows do not reconcile")
    return kept, rejected
