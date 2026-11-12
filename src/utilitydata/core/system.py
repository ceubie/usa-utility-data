"""Public water systems, one row for every SDWA PWSID."""

import pandas as pd

from utilitydata.core.config import (
    ACTIVITY_STATUS,
    MISSING_ACTIVITY_STATUS,
    OWNER_TYPE,
    WHOLESALER_CODES,
)
from utilitydata.core.schema import (
    EVIDENCE_COLUMNS,
    IDENTIFIER_COLUMNS,
    SDWA_COLUMNS,
    SYSTEM_COLUMNS,
    WORKING_SYSTEM_COLUMNS,
)
from utilitydata.core.text import as_string, normalize_name, require_columns, state_code


def build_systems_from_sdwa(frame: pd.DataFrame, *, release: str, source_id: str, sector: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return working systems, pwsid identifiers, and raw SDWA evidence.

    Inactive systems stay. An activity or wholesaler code outside the config map
    raises. An owner code outside the map is kept and is not assigned a type.
    """
    require_columns(frame, SDWA_COLUMNS, "SDWA public water systems")
    if not release:
        raise ValueError("A release is required to build systems")
    if not source_id or not sector:
        raise ValueError("SDWA systems need a source id and a sector")
    pwsid = as_string(frame["PWSID"])
    if bool(pwsid.isna().any()):
        raise ValueError("SDWA PWSID is null")
    if bool(pwsid.duplicated().any()):
        raise ValueError("SDWA PWSID is duplicated")
    status = _map_activity(frame["PWS_ACTIVITY_CODE"])
    wholesaler = _raw_wholesaler(frame["IS_WHOLESALER_IND"])
    owner_code = as_string(frame["OWNER_TYPE_CODE"])
    name = as_string(frame["PWS_NAME"])
    systems = pd.DataFrame({
        "system_id": "SYS_PWS_" + pwsid,
        "sector": sector,
        "name": name,
        "status": status,
        "system_type": as_string(frame["PWS_TYPE_CODE"]),
        "primary_state": state_code(frame["STATE_CODE"]),
        "population_served": _integers(frame["POPULATION_SERVED_COUNT"], "POPULATION_SERVED_COUNT"),
        "service_connections": _integers(frame["SERVICE_CONNECTIONS_COUNT"], "SERVICE_CONNECTIONS_COUNT"),
        "customers": pd.Series(pd.NA, index=frame.index, dtype="Float64"),
        "sales_mwh": pd.Series(pd.NA, index=frame.index, dtype="Float64"),
        "owner_org_id": pd.Series(pd.NA, index=frame.index, dtype="string"),
        "operator_org_id": pd.Series(pd.NA, index=frame.index, dtype="string"),
        "in_federal_registry": True,
        "first_seen_release": release,
        "last_seen_release": release,
        "pwsid": pwsid,
        "name_norm": name.map(normalize_name).astype("string"),
        "owner_type": owner_code.map(OWNER_TYPE).astype("string"),
        "owner_type_code": owner_code,
    })
    if bool(systems["system_id"].duplicated().any()):
        raise ValueError("SDWA system ids are not unique")
    identifiers = pd.DataFrame({
        "system_id": systems["system_id"],
        "scheme": "pwsid",
        "value": pwsid,
        "source_id": source_id,
    })
    evidence = pd.DataFrame({
        "system_id": systems["system_id"],
        "activity_code": as_string(frame["PWS_ACTIVITY_CODE"]),
        "wholesaler_indicator": wholesaler,
        "owner_type_code": owner_code,
    })
    return (
        align_systems(systems),
        identifiers.loc[:, list(IDENTIFIER_COLUMNS)].reset_index(drop=True),
        evidence.loc[:, list(EVIDENCE_COLUMNS)].reset_index(drop=True),
    )


def _map_activity(series: pd.Series) -> pd.Series:
    codes = as_string(series)
    unknown = codes.dropna()
    unexpected = sorted(set(unknown) - set(ACTIVITY_STATUS))
    if unexpected:
        raise ValueError(f"Unmapped SDWA activity codes: {', '.join(unexpected)}")
    mapped = codes.map(ACTIVITY_STATUS).astype("string")
    return mapped.mask(codes.isna(), MISSING_ACTIVITY_STATUS)


def _raw_wholesaler(series: pd.Series) -> pd.Series:
    codes = as_string(series)
    unexpected = sorted(set(codes.dropna()) - set(WHOLESALER_CODES))
    if unexpected:
        raise ValueError(f"Unmapped SDWA wholesaler codes: {', '.join(unexpected)}")
    return codes


def public_systems(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the published system columns, in order."""
    require_columns(frame, SYSTEM_COLUMNS, "systems")
    return frame.loc[:, list(SYSTEM_COLUMNS)].reset_index(drop=True)


def preserve_first_seen(systems: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Keep the earliest release recorded for a system id that already exists."""
    require_columns(previous, ("system_id", "first_seen_release"), "previous systems")
    require_columns(systems, ("system_id", "first_seen_release"), "systems")
    lookup = previous.drop_duplicates("system_id").set_index("system_id")["first_seen_release"]
    seen = systems["system_id"].map(lookup)
    updated = systems.copy()
    updated["first_seen_release"] = seen.fillna(updated["first_seen_release"]).astype("string")
    return updated


def align_systems(frame: pd.DataFrame) -> pd.DataFrame:
    """Give a working system frame stable nullable dtypes."""
    require_columns(frame, WORKING_SYSTEM_COLUMNS, "systems")
    aligned = frame.loc[:, list(WORKING_SYSTEM_COLUMNS)].copy()
    text = [
        "system_id",
        "sector",
        "name",
        "status",
        "system_type",
        "primary_state",
        "owner_org_id",
        "operator_org_id",
        "first_seen_release",
        "last_seen_release",
        "pwsid",
        "name_norm",
        "owner_type",
        "owner_type_code",
    ]
    for column in text:
        aligned[column] = aligned[column].astype("string")
    aligned["population_served"] = pd.to_numeric(aligned["population_served"]).astype("Int64")
    aligned["service_connections"] = pd.to_numeric(aligned["service_connections"]).astype("Int64")
    aligned["customers"] = pd.to_numeric(aligned["customers"]).astype("Float64")
    aligned["sales_mwh"] = pd.to_numeric(aligned["sales_mwh"]).astype("Float64")
    aligned["in_federal_registry"] = aligned["in_federal_registry"].astype("boolean")
    return aligned.reset_index(drop=True)


def _integers(series: pd.Series, label: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    present = series.notna()
    if bool((present & numeric.isna()).any()):
        raise ValueError(f"Non-numeric SDWA value in {label}")
    if bool((numeric.notna() & (numeric != numeric.round())).any()):
        raise ValueError(f"Non-integral SDWA value in {label}")
    return numeric.round().astype("Int64")
