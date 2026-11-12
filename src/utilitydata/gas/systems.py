"""One natural-gas system per PHMSA operator and operating state."""

from __future__ import annotations

import pandas as pd

from utilitydata.core.schema import (
    IDENTIFIER_COLUMNS,
    ORGANIZATION_COLUMNS,
    SYSTEM_COLUMNS,
)
from utilitydata.core.text import as_string, normalize_name, require_columns
from utilitydata.gas.match import phmsa_system_id


def build_gas_systems(
    decade: pd.DataFrame,
    operators: pd.DataFrame,
    *,
    source_id: str,
    release: str,
    known_states: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Build systems from the latest report year.

    ``operating_state`` is the service state. The office state is not an input.
    Earlier report years are counted and are not dropped.
    """
    require_columns(decade, ("operator_id_phmsa", "operating_state", "report_date"), "PHMSA distribution")
    require_columns(operators, ("operator_id_phmsa", "operator_name_phmsa", "report_date"), "PHMSA operators")
    if not source_id or not release:
        raise ValueError("Gas systems need a source and a release")
    latest = decade["report_date"].max()
    if pd.isna(latest):
        raise ValueError("PHMSA distribution has no report date")
    current = decade.loc[decade["report_date"].eq(latest)].copy()
    prior = len(decade) - len(current)
    reasons = [_state_reason(state, known_states) for state in current["operating_state"]]
    current["reason"] = reasons
    invalid = current.loc[current["reason"].notna()]
    valid = current.loc[current["reason"].isna()]
    names = _latest_names(operators, latest)
    missing_name = ~valid["operator_id_phmsa"].isin(set(names.index))
    unnamed = valid.loc[missing_name].copy()
    unnamed["reason"] = "unknown_operator"
    valid = valid.loc[~missing_name]
    grouped = valid.groupby(["operator_id_phmsa", "operating_state"], sort=False).size().reset_index(name="detail_rows")
    systems = pd.DataFrame({
        "operator_id": grouped["operator_id_phmsa"].map(_operator_int),
        "state": grouped["operating_state"].astype("string").str.upper(),
    })
    systems["system_id"] = [phmsa_system_id(int(operator_id), str(state)) for operator_id, state in zip(systems["operator_id"], systems["state"], strict=True)]
    systems["name"] = systems["operator_id"].map(names)
    systems["name_norm"] = systems["name"].map(normalize_name)
    if bool(systems["system_id"].duplicated().any()):
        raise ValueError("PHMSA system ids are not unique")
    published = pd.DataFrame({
        "system_id": systems["system_id"],
        "sector": "natural_gas",
        "name": as_string(systems["name"]),
        "status": "active",
        "system_type": "distribution",
        "primary_state": systems["state"],
        "population_served": pd.Series(pd.NA, index=systems.index, dtype="Int64"),
        "service_connections": pd.Series(pd.NA, index=systems.index, dtype="Int64"),
        "customers": pd.Series(pd.NA, index=systems.index, dtype="Float64"),
        "sales_mwh": pd.Series(pd.NA, index=systems.index, dtype="Float64"),
        "owner_org_id": systems["operator_id"].map(lambda value: f"ORG_PHMSA_{int(value)}").astype("string"),
        "operator_org_id": pd.Series(pd.NA, index=systems.index, dtype="string"),
        "in_federal_registry": True,
        "first_seen_release": release,
        "last_seen_release": release,
    })
    identifiers = pd.DataFrame({
        "system_id": published["system_id"],
        "scheme": "phmsa_operator",
        "value": systems["operator_id"].astype("string"),
        "source_id": source_id,
    })
    organizations = _organizations(systems, source_id)
    rejects = pd.concat([
        invalid.loc[:, ["operator_id_phmsa", "operating_state", "reason"]],
        unnamed.loc[:, ["operator_id_phmsa", "operating_state", "reason"]],
    ], ignore_index=True)
    if len(valid) + len(invalid) + len(unnamed) != len(current) or prior + len(current) != len(decade):
        raise ValueError("PHMSA distribution rows do not reconcile")
    counts = {
        "input_rows": len(decade),
        "latest_rows": len(current),
        "prior_rows": prior,
        "reject_rows": len(rejects),
        "systems": len(published),
        "report_date": str(pd.Timestamp(latest).date()),
    }
    return (
        published.loc[:, list(SYSTEM_COLUMNS)].reset_index(drop=True),
        identifiers.loc[:, list(IDENTIFIER_COLUMNS)].reset_index(drop=True),
        organizations,
        rejects,
        counts,
    )


def _state_reason(state: object, known_states: set[str]) -> str | None:
    if state is None or (not isinstance(state, str) and pd.isna(state)):
        return "missing_operating_state"
    text = str(state).strip().upper()
    if text not in known_states:
        return "unknown_operating_state"
    return None


def _operator_int(value: object) -> int:
    if isinstance(value, bool) or pd.isna(value):
        raise ValueError("PHMSA operator id is missing")
    number = int(value)
    if number < 0:
        raise ValueError("PHMSA operator id is negative")
    return number


def _latest_names(operators: pd.DataFrame, latest: object) -> pd.Series:
    current = operators.loc[operators["report_date"].eq(latest), ["operator_id_phmsa", "operator_name_phmsa"]]
    if current.empty:
        current = operators.loc[operators["report_date"].eq(operators["report_date"].max()), ["operator_id_phmsa", "operator_name_phmsa"]]
    names = current.groupby("operator_id_phmsa")["operator_name_phmsa"].nunique(dropna=False)
    if bool((names > 1).any()):
        raise ValueError("A PHMSA operator has more than one name in the latest report")
    return current.drop_duplicates("operator_id_phmsa").set_index("operator_id_phmsa")["operator_name_phmsa"]


def _organizations(systems: pd.DataFrame, source_id: str) -> pd.DataFrame:
    rows = []
    seen: set[int] = set()
    for record in systems.itertuples(index=False):
        operator_id = int(record.operator_id)
        if operator_id in seen:
            continue
        seen.add(operator_id)
        rows.append({
            "org_id": f"ORG_PHMSA_{operator_id}",
            "name": record.name,
            "name_norm": record.name_norm,
            "state": pd.NA,
            "owner_type": pd.NA,
            "owner_type_code": pd.NA,
            "government_unit_id": pd.NA,
            "sector": "natural_gas",
            "source_id": source_id,
        })
    frame = pd.DataFrame(rows, columns=list(ORGANIZATION_COLUMNS))
    for column in ORGANIZATION_COLUMNS:
        frame[column] = frame[column].astype("string")
    return frame.sort_values("org_id").reset_index(drop=True)
