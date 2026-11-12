"""EIA-861 retail sales, entity codes, and electric systems.

Bundled and delivery rows are the retail extract. Energy-only rows are
competitive supply and are rejected instead of added. An EIA entity code that
is not in the config map fails the build.
"""

from __future__ import annotations

import pandas as pd

from utilitydata.core.config import (
    EIA_ADJUSTMENT_NAME_PREFIX,
    EIA_ENERGY_ONLY_SERVICE_TYPE,
    EIA_ENTITY_TYPE,
    EIA_NONUTILITY_IDS,
    EIA_RETAIL_SERVICE_TYPES,
    EIA_WITHHELD_NAME,
)
from utilitydata.core.schema import (
    IDENTIFIER_COLUMNS,
    ORGANIZATION_COLUMNS,
    SYSTEM_COLUMNS,
)
from utilitydata.core.text import normalize_name, require_columns
from utilitydata.electric.schema import (
    CODE_COLUMNS,
    ENTITY_COLUMNS,
    REJECT_COLUMNS,
    SALES_COLUMNS,
    SYSTEM_STATE_COLUMNS,
)


def electric_system_id(utility_id: int) -> str:
    """Return the stable system id. There is no state suffix."""
    return f"SYS_EIA_{int(utility_id)}"


def require_entity_type(code: str) -> str:
    """Map one EIA entity code. An unmapped code fails the build."""
    try:
        return EIA_ENTITY_TYPE[code]
    except KeyError as exc:
        raise ValueError(f"Unmapped EIA entity code {code!r}") from exc


def split_sales(
    frame: pd.DataFrame,
    *,
    known_states: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Split the sales table into the current retail extract, prior years, and rejects.

    The current extract is the latest ``report_date``. Prior years are kept in
    the history frame. Every input row is in exactly one of the three results.
    """
    require_columns(frame, SALES_COLUMNS, "EIA-861 sales")
    latest = frame["report_date"].max()
    if pd.isna(latest):
        raise ValueError("EIA-861 sales has no report date")
    prior = frame.loc[frame["report_date"] != latest].copy()
    current = frame.loc[frame["report_date"] == latest].copy()
    reasons = current.apply(lambda row: _sales_reason(row, known_states), axis=1)
    unexpected = sorted({reason for reason in reasons if reason == "unmapped_service_type"})
    if unexpected:
        raise ValueError("Unmapped EIA service type in the latest sales extract")
    rejected = current.loc[reasons.notna()].copy()
    rejected["reason"] = reasons.loc[reasons.notna()].to_numpy()
    kept = current.loc[reasons.isna()].copy()
    kept, missing = _reject_missing_measures(kept)
    rejected = pd.concat([rejected, missing], ignore_index=True)
    rejects = _sales_rejects(rejected)
    if len(prior) + len(kept) + len(rejects) != len(frame):
        raise ValueError("EIA-861 sales rows do not reconcile")
    counts = {
        "input_rows": len(frame),
        "prior_rows": len(prior),
        "retail_rows": len(kept),
        "reject_rows": len(rejects),
        "report_date": str(pd.Timestamp(latest).date()),
    }
    return kept, prior, rejects, counts


def aggregate_retail(kept: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sum bundled and delivery rows by utility and by utility-state."""
    require_columns(kept, SALES_COLUMNS, "retail sales")
    if kept.empty:
        raise ValueError("The bundled and delivery extract has no rows")
    by_state = (
        kept.groupby(["utility_id_eia", "state", "report_date"], dropna=False)
        .agg(customers=("customers", _sum_measures), sales_mwh=("sales_mwh", _sum_measures), utility_name_eia=("utility_name_eia", "first"))
        .reset_index()
    )
    by_utility = (
        by_state.groupby("utility_id_eia", dropna=False)
        .agg(customers=("customers", _sum_measures), sales_mwh=("sales_mwh", _sum_measures), utility_name_eia=("utility_name_eia", "first"), report_date=("report_date", "max"))
        .reset_index()
    )
    if by_utility["customers"].isna().any() or by_utility["sales_mwh"].isna().any():
        raise ValueError("A retail utility is missing customers or sales after aggregation")
    return by_utility, by_state


def direct_service_utilities(
    frame: pd.DataFrame,
    *,
    years: int,
    mwh_per_customer: float,
) -> pd.DataFrame:
    """Return utilities whose retail sales per customer exceed the limit in every measured year.

    Only the last ``years`` report dates and only bundled and delivery rows
    count. A year with no customers or no sales is not measured; a utility needs
    at least one measured year to be listed.
    """
    require_columns(frame, SALES_COLUMNS, "EIA-861 sales")
    columns = ["utility_id_eia", "years_measured", "min_mwh_per_customer"]
    retail = frame.loc[
        frame["service_type"].isin(EIA_RETAIL_SERVICE_TYPES)
        & frame["utility_id_eia"].notna()
        & ~frame["utility_id_eia"].isin(EIA_NONUTILITY_IDS)
    ]
    recent = sorted(retail["report_date"].dropna().unique())[-years:]
    yearly = (
        retail.loc[retail["report_date"].isin(recent)]
        .groupby(["utility_id_eia", "report_date"])
        .agg(customers=("customers", _sum_measures), sales_mwh=("sales_mwh", _sum_measures))
        .reset_index()
    )
    measured = yearly.loc[yearly["customers"].gt(0) & yearly["sales_mwh"].notna()].copy()
    if measured.empty:
        return pd.DataFrame(columns=columns)
    measured["ratio"] = measured["sales_mwh"] / measured["customers"]
    summary = measured.groupby("utility_id_eia").agg(years_measured=("ratio", "size"), min_mwh_per_customer=("ratio", "min")).reset_index()
    listed = summary.loc[summary["min_mwh_per_customer"].gt(mwh_per_customer)].copy()
    listed["utility_id_eia"] = listed["utility_id_eia"].astype(int)
    return listed.loc[:, columns].sort_values("utility_id_eia").reset_index(drop=True)


def entity_types_for_year(frame: pd.DataFrame, report_date: str) -> pd.DataFrame:
    """Return the sales-year entity code. A code outside the map fails the build."""
    require_columns(frame, CODE_COLUMNS, "EIA-860 utility codes")
    current = frame.loc[frame["report_date"].astype(str).str.slice(0, 10) == report_date]
    rows: list[dict[str, object]] = []
    for utility_id, group in current.groupby("utility_id_eia", dropna=False):
        codes = sorted({str(value) for value in group["entity_type"].dropna().tolist()})
        if len(codes) > 1:
            raise ValueError(f"Conflicting EIA entity codes for {utility_id}: {', '.join(codes)}")
        code = codes[0] if codes else None
        org_type = require_entity_type(code) if code is not None else None
        rows.append({"utility_id_eia": int(utility_id), "entity_type": code, "org_type": org_type})
    return pd.DataFrame(rows, columns=["utility_id_eia", "entity_type", "org_type"])


def build_systems(
    entities: pd.DataFrame,
    retail: pd.DataFrame,
    by_state: pd.DataFrame,
    codes: pd.DataFrame,
    *,
    release: str,
    source_id: str,
    code_source_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build one system per EIA utility, state rows, and organizations."""
    require_columns(entities, ENTITY_COLUMNS, "EIA utilities")
    if entities["utility_id_eia"].duplicated().any():
        raise ValueError("EIA utility ids are not unique")
    retail_ids = set(retail["utility_id_eia"].astype(int))
    entity_ids = set(entities["utility_id_eia"].astype(int))
    missing = retail.loc[~retail["utility_id_eia"].astype(int).isin(entity_ids | set(EIA_NONUTILITY_IDS)), ["utility_id_eia", "utility_name_eia"]]
    usable = pd.concat([
        entities.loc[~entities["utility_id_eia"].astype(int).isin(EIA_NONUTILITY_IDS), ["utility_id_eia", "utility_name_eia"]],
        missing,
    ], ignore_index=True)
    if usable["utility_id_eia"].astype(int).duplicated().any():
        raise ValueError("EIA utility ids are not unique after adding retail respondents")
    retail_lookup = retail.set_index(retail["utility_id_eia"].astype(int))
    code_lookup = codes.set_index(codes["utility_id_eia"].astype(int)) if not codes.empty else pd.DataFrame(columns=["entity_type", "org_type"])
    system_rows: list[dict[str, object]] = []
    identifier_rows: list[dict[str, object]] = []
    organization_rows: list[dict[str, object]] = []
    code_rejects: list[dict[str, object]] = []
    for record in usable.itertuples(index=False):
        utility_id = int(record.utility_id_eia)
        system_id = electric_system_id(utility_id)
        active = utility_id in retail_ids
        customers = sales_mwh = None
        name = record.utility_name_eia
        if active:
            customers = retail_lookup.at[utility_id, "customers"]
            sales_mwh = retail_lookup.at[utility_id, "sales_mwh"]
            name = retail_lookup.at[utility_id, "utility_name_eia"] or name
        org_id = None
        if utility_id in code_lookup.index and code_lookup.at[utility_id, "entity_type"] is not None:
            org_id = f"ORG_EIA_{utility_id}"
            organization_rows.append({
                "org_id": org_id,
                "name": name,
                "name_norm": normalize_name(name),
                "state": None,
                "owner_type": code_lookup.at[utility_id, "org_type"],
                "owner_type_code": code_lookup.at[utility_id, "entity_type"],
                "government_unit_id": None,
                "sector": "electric",
                "source_id": code_source_id,
            })
        elif active:
            code_rejects.append({
                "table_name": "core_eia860__scd_utilities",
                "utility_id_eia": utility_id,
                "state": None,
                "reason": "missing_entity_type",
                "raw_name": name,
            })
        system_rows.append({
            "system_id": system_id,
            "sector": "electric",
            "name": name,
            "status": "active" if active else "inactive",
            "system_type": "retail" if active else None,
            "primary_state": None,
            "population_served": None,
            "service_connections": None,
            "customers": customers,
            "sales_mwh": sales_mwh,
            "owner_org_id": org_id,
            "operator_org_id": None,
            "in_federal_registry": True,
            "first_seen_release": release,
            "last_seen_release": release,
        })
        identifier_rows.append({
            "system_id": system_id,
            "scheme": "eia_utility",
            "value": str(utility_id),
            "source_id": source_id,
        })
    systems = pd.DataFrame(system_rows)
    states = _system_states(by_state, systems)
    primary = states.sort_values(["customers", "sales_mwh", "state"], ascending=[False, False, True], na_position="last")
    primary = primary.drop_duplicates("system_id", keep="first").set_index("system_id")["state"]
    systems["primary_state"] = systems["system_id"].map(primary)
    organizations = pd.DataFrame(organization_rows)
    if not organizations.empty:
        organizations["state"] = organizations["org_id"].map(systems.drop_duplicates("owner_org_id").set_index("owner_org_id")["primary_state"])
    systems = systems.loc[:, list(SYSTEM_COLUMNS)]
    identifiers = pd.DataFrame(identifier_rows).loc[:, list(IDENTIFIER_COLUMNS)]
    if organizations.empty:
        organizations = pd.DataFrame(columns=list(ORGANIZATION_COLUMNS))
    else:
        organizations = organizations.loc[:, list(ORGANIZATION_COLUMNS)]
    state_frame = states.loc[:, list(SYSTEM_STATE_COLUMNS)] if not states.empty else pd.DataFrame(columns=list(SYSTEM_STATE_COLUMNS))
    return systems, identifiers, state_frame, organizations, pd.DataFrame(code_rejects, columns=list(REJECT_COLUMNS))


def _sales_reason(row: pd.Series, known_states: set[str]) -> str | None:
    utility_id = row["utility_id_eia"]
    if pd.notna(utility_id) and int(utility_id) in EIA_NONUTILITY_IDS:
        return "nonutility_respondent"
    name = normalize_name(row["utility_name_eia"]) or ""
    if name == EIA_WITHHELD_NAME:
        return "withheld_respondent"
    if name.startswith(EIA_ADJUSTMENT_NAME_PREFIX):
        return "eia_adjustment_row"
    service_type = row["service_type"]
    if service_type is None or (not isinstance(service_type, str) and pd.isna(service_type)) or str(service_type).strip() == "":
        return "null_service_type"
    text = str(service_type).strip()
    if text == EIA_ENERGY_ONLY_SERVICE_TYPE:
        return "energy_only_supplier"
    if text not in EIA_RETAIL_SERVICE_TYPES:
        return "unmapped_service_type"
    state = row["state"]
    if state is None or (not isinstance(state, str) and pd.isna(state)) or str(state).strip().upper() not in known_states:
        return "unrecognized_state"
    return None


def _reject_missing_measures(kept: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    totals = kept.groupby("utility_id_eia").agg(customers=("customers", _sum_measures), sales_mwh=("sales_mwh", _sum_measures))
    missing_ids = set(totals.index[(totals["customers"].isna()) | (totals["sales_mwh"].isna())])
    if not missing_ids:
        return kept, kept.iloc[0:0].copy()
    missing = kept.loc[kept["utility_id_eia"].isin(missing_ids)].copy()
    missing["reason"] = "missing_customers_and_sales"
    return kept.loc[~kept["utility_id_eia"].isin(missing_ids)].copy(), missing


def _sales_rejects(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=list(REJECT_COLUMNS))
    return pd.DataFrame({
        "table_name": "core_eia861__yearly_sales",
        "utility_id_eia": frame["utility_id_eia"],
        "state": frame["state"],
        "reason": frame["reason"],
        "raw_name": frame["utility_name_eia"],
    })


def _sum_measures(series: pd.Series) -> float | None:
    present = series.dropna()
    if present.empty:
        return None
    return float(present.sum())


def _system_states(by_state: pd.DataFrame, systems: pd.DataFrame) -> pd.DataFrame:
    active = set(systems.loc[systems["status"].eq("active"), "system_id"])
    rows = []
    for record in by_state.itertuples(index=False):
        system_id = electric_system_id(int(record.utility_id_eia))
        if system_id not in active:
            continue
        rows.append({
            "system_id": system_id,
            "utility_id_eia": int(record.utility_id_eia),
            "state": record.state,
            "customers": record.customers,
            "sales_mwh": record.sales_mwh,
            "report_date": pd.Timestamp(record.report_date).date().isoformat(),
        })
    return pd.DataFrame(rows, columns=list(SYSTEM_STATE_COLUMNS))
