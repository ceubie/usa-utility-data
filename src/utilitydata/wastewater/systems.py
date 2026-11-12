"""One wastewater system per CWNS id, owned by the responsible authority."""

from __future__ import annotations

import hashlib

import pandas as pd

from utilitydata.core.config import (
    CWNS_INFRASTRUCTURE_SECTOR,
    CWNS_OWNER_TYPE,
    CWNS_REVIEW_STATUS,
)
from utilitydata.core.schema import (
    IDENTIFIER_COLUMNS,
    ORGANIZATION_COLUMNS,
    SYSTEM_COLUMNS,
)
from utilitydata.core.text import as_string, normalize_name, require_columns
from utilitydata.wastewater.match import cwns_system_id


def build_systems(
    facilities: pd.DataFrame,
    *,
    source_id: str,
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return systems, identifiers, organizations, and facility rejects.

    Stormwater and nonpoint rows are rejected with a reason. An owner is the
    responsible authority, so several plants can share one organization.
    """
    require_columns(
        facilities,
        (
            "cwns_id",
            "facility_name",
            "state",
            "infrastructure_type",
            "owner_type",
            "review_status",
            "authority_name",
            "responsible_entity",
        ),
        "CWNS facilities",
    )
    if not source_id or not release:
        raise ValueError("Wastewater systems need a source and a release")
    if bool(facilities["cwns_id"].duplicated().any()):
        raise ValueError("CWNS id is duplicated")
    reasons: list[str | None] = []
    for record in facilities.itertuples(index=False):
        reasons.append(_facility_reason(record))
    classified = facilities.copy()
    classified["reject_reason"] = reasons
    rejected = classified.loc[classified["reject_reason"].notna(), ["cwns_id", "facility_name", "reject_reason"]]
    rejected = rejected.rename(columns={"reject_reason": "reason", "facility_name": "raw_name"})
    rejected["table_name"] = "FACILITIES"
    kept = classified.loc[classified["reject_reason"].isna()].copy()
    if len(kept) + len(rejected) != len(facilities):
        raise ValueError("CWNS facility rows do not reconcile")
    kept["system_id"] = kept["cwns_id"].map(cwns_system_id)
    kept["name_norm"] = kept["facility_name"].map(normalize_name)
    kept["status"] = kept["review_status"].map(CWNS_REVIEW_STATUS)
    organizations, owner_ids = _organizations(kept, source_id)
    systems = pd.DataFrame({
        "system_id": kept["system_id"],
        "sector": "wastewater",
        "name": as_string(kept["facility_name"]),
        "status": kept["status"].astype("string"),
        "system_type": as_string(kept["infrastructure_type"]),
        "primary_state": as_string(kept["state"]).str.upper(),
        "population_served": pd.Series(pd.NA, index=kept.index, dtype="Int64"),
        "service_connections": pd.Series(pd.NA, index=kept.index, dtype="Int64"),
        "customers": pd.Series(pd.NA, index=kept.index, dtype="Float64"),
        "sales_mwh": pd.Series(pd.NA, index=kept.index, dtype="Float64"),
        "owner_org_id": kept["system_id"].map(owner_ids).astype("string"),
        "operator_org_id": pd.Series(pd.NA, index=kept.index, dtype="string"),
        "in_federal_registry": True,
        "first_seen_release": release,
        "last_seen_release": release,
    })
    identifiers = pd.DataFrame({
        "system_id": systems["system_id"],
        "scheme": "cwns_id",
        "value": kept["cwns_id"].astype("string"),
        "source_id": source_id,
    })
    return (
        systems.loc[:, list(SYSTEM_COLUMNS)].reset_index(drop=True),
        identifiers.loc[:, list(IDENTIFIER_COLUMNS)].reset_index(drop=True),
        organizations,
        rejected.reset_index(drop=True),
    )


def _facility_reason(record: object) -> str | None:
    infrastructure = CWNS_INFRASTRUCTURE_SECTOR.get(str(record.infrastructure_type))
    if infrastructure is None:
        raise ValueError(f"Unmapped CWNS infrastructure type: {record.infrastructure_type}")
    if infrastructure != "wastewater":
        return "outside_wastewater_sector"
    if str(record.review_status) not in CWNS_REVIEW_STATUS:
        raise ValueError(f"Unmapped CWNS review status: {record.review_status}")
    if record.owner_type is not None and not pd.isna(record.owner_type) and str(record.owner_type) not in CWNS_OWNER_TYPE:
        raise ValueError(f"Unmapped CWNS owner type: {record.owner_type}")
    if not record.cwns_id or len(str(record.cwns_id)) != 11 or not str(record.cwns_id).isdigit():
        return "invalid_cwns_id"
    return None


def _organizations(facilities: pd.DataFrame, source_id: str) -> tuple[pd.DataFrame, dict[str, str]]:
    owner_ids: dict[str, str] = {}
    organizations: dict[str, dict[str, object]] = {}
    named = facilities["authority_name"].notna() & facilities["responsible_entity"].eq("Y")
    for record in facilities.loc[named].itertuples(index=False):
        name_norm = normalize_name(record.authority_name)
        state = None if record.state is None or pd.isna(record.state) else str(record.state).upper()
        if not name_norm or not state:
            continue
        org_id = wastewater_org_id(state, name_norm)
        owner_type = None if record.owner_type is None or pd.isna(record.owner_type) else CWNS_OWNER_TYPE[str(record.owner_type)]
        current = organizations.get(org_id)
        owner_ids[str(record.system_id)] = org_id
        if current is not None:
            if not _same_owner(current["owner_type"], owner_type):
                current["owner_type"] = pd.NA
                current["owner_type_code"] = pd.NA
            continue
        organizations[org_id] = {
            "org_id": org_id,
            "name": str(record.authority_name),
            "name_norm": name_norm,
            "state": state,
            "owner_type": owner_type,
            "owner_type_code": None if record.owner_type is None or pd.isna(record.owner_type) else str(record.owner_type),
            "government_unit_id": pd.NA,
            "sector": "wastewater",
            "source_id": source_id,
        }
    frame = pd.DataFrame(list(organizations.values()), columns=list(ORGANIZATION_COLUMNS))
    if frame.empty:
        frame = pd.DataFrame(columns=list(ORGANIZATION_COLUMNS))
    for column in ORGANIZATION_COLUMNS:
        frame[column] = frame[column].astype("string")
    return frame.sort_values("org_id").reset_index(drop=True), owner_ids


def _same_owner(left: object, right: object) -> bool:
    left_missing = left is None or pd.isna(left)
    right_missing = right is None or pd.isna(right)
    if left_missing or right_missing:
        return bool(left_missing and right_missing)
    return left == right


def wastewater_org_id(state: str, name_norm: str) -> str:
    """Return a stable organization id for one authority in one state."""
    digest = hashlib.sha256(f"wastewater|{state}|{name_norm}".encode()).hexdigest()[:12]
    return f"ORG_WW_{state}_{digest}"
