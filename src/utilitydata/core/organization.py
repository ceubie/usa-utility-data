"""Owners from the SDWA owner code, with exact local-government name links."""

import hashlib
import re

import pandas as pd

from utilitydata.core.schema import (
    GOVERNMENT_COLUMNS,
    ORGANIZATION_COLUMNS,
    WORKING_SYSTEM_COLUMNS,
)
from utilitydata.core.system import align_systems
from utilitydata.core.text import (
    as_string,
    is_missing,
    normalize_name,
    require_columns,
    state_code,
)

_CENSUS_ID = re.compile(r"[A-Za-z0-9_-]+")


def link_organizations(
    systems: pd.DataFrame,
    government_units: pd.DataFrame,
    *,
    sdwa_source_id: str,
    government_source_id: str,
    sector: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Attach owner organizations. A local name links only when one government unit matches.

    An owner code outside the config map does not become a government unit, and a
    local name that is missing or ambiguous does not borrow one.
    """
    require_columns(systems, WORKING_SYSTEM_COLUMNS, "systems")
    if not sdwa_source_id or not government_source_id or not sector:
        raise ValueError("Organization links need source ids and a sector")
    index, ambiguous = _government_index(government_units)
    local = systems["owner_type"].eq("local") & systems["primary_state"].notna() & systems["name_norm"].notna()
    matched = systems.loc[local, ["system_id", "primary_state", "name_norm", "name"]].merge(
        index,
        left_on=["primary_state", "name_norm"],
        right_on=["state", "name_norm"],
        how="inner",
    )
    if bool(matched["system_id"].duplicated().any()):
        raise ValueError("A system matched more than one government unit")
    organizations: dict[str, dict[str, object]] = {}
    owner_ids: dict[str, str] = {}
    for row in matched.itertuples(index=False):
        org_id = government_org_id(str(row.government_unit_id))
        owner_ids[str(row.system_id)] = org_id
        organizations.setdefault(org_id, _organization(
            org_id=org_id,
            name=row.unit_name,
            name_norm=row.name_norm,
            state=row.state,
            owner_type="local",
            owner_type_code="L",
            government_unit_id=str(row.government_unit_id),
            sector=sector,
            source_id=government_source_id,
        ))
    remaining = systems.loc[~systems["system_id"].isin(owner_ids)].sort_values("system_id")
    named = remaining["owner_type"].notna() & remaining["primary_state"].notna() & remaining["name_norm"].notna()
    for row in remaining.loc[named].itertuples(index=False):
        org_id = owned_org_id(str(row.owner_type), str(row.primary_state), str(row.name_norm))
        owner_ids[str(row.system_id)] = org_id
        organizations.setdefault(org_id, _organization(
            org_id=org_id,
            name=row.name,
            name_norm=row.name_norm,
            state=row.primary_state,
            owner_type=row.owner_type,
            owner_type_code=row.owner_type_code,
            government_unit_id=pd.NA,
            sector=sector,
            source_id=sdwa_source_id,
        ))
    loose = remaining.loc[~named]
    has_owner = loose["owner_type"].notna() | loose["owner_type_code"].notna()
    for row in loose.loc[has_owner].itertuples(index=False):
        org_id = f"ORG_SYS_{row.system_id}"
        owner_ids[str(row.system_id)] = org_id
        organizations.setdefault(org_id, _organization(
            org_id=org_id,
            name=row.name,
            name_norm=row.name_norm,
            state=row.primary_state,
            owner_type=row.owner_type,
            owner_type_code=row.owner_type_code,
            government_unit_id=pd.NA,
            sector=sector,
            source_id=sdwa_source_id,
        ))
    updated = systems.copy()
    updated["owner_org_id"] = updated["system_id"].map(owner_ids).astype("string")
    orgs = pd.DataFrame(list(organizations.values()), columns=list(ORGANIZATION_COLUMNS))
    if orgs.empty:
        orgs = pd.DataFrame(columns=list(ORGANIZATION_COLUMNS))
    orgs = orgs.sort_values("org_id").reset_index(drop=True)
    for column in ORGANIZATION_COLUMNS:
        orgs[column] = orgs[column].astype("string")
    return align_systems(updated), orgs, {
        "government_matches": len(matched),
        "ambiguous_government_names": ambiguous,
    }


def government_org_id(census_id: str) -> str:
    """Return the organization id for one Census government-unit id."""
    if not _CENSUS_ID.fullmatch(census_id):
        raise ValueError(f"Government unit id is not usable: {census_id}")
    return f"ORG_GOV_{census_id}"


def owned_org_id(owner_type: str, state: str, name_norm: str) -> str:
    """Stable organization id for an owner that is not a matched government unit."""
    token = hashlib.sha256(f"{owner_type}|{state}|{name_norm}".encode()).hexdigest()[:16]
    return f"ORG_OWN_{token}"


def unique_government_index(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Return one row per state and name that identifies a single government unit.

    A name shared by more than one unit in a state is counted and omitted.
    """
    return _government_index(frame)


def _government_index(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    require_columns(frame, GOVERNMENT_COLUMNS, "government units")
    work = pd.DataFrame({
        "government_unit_id": as_string(frame["CENSUS_ID_PID6"]),
        "unit_name": as_string(frame["UNIT_NAME"]),
        "state": state_code(frame["STATE"]),
    })
    work["name_norm"] = work["unit_name"].map(normalize_name).astype("string")
    work = work.dropna(subset=["government_unit_id", "name_norm", "state"])
    if work.empty:
        return pd.DataFrame(columns=["state", "name_norm", "government_unit_id", "unit_name"]), 0
    counts = work.groupby(["state", "name_norm"], dropna=False)["government_unit_id"].nunique()
    ambiguous = int((counts > 1).sum())
    unique_keys = counts[counts.eq(1)].reset_index()[["state", "name_norm"]]
    unique = work.merge(unique_keys, on=["state", "name_norm"], how="inner")
    unique = unique.sort_values(["state", "name_norm", "unit_name", "government_unit_id"])
    index = unique.groupby(["state", "name_norm"], as_index=False, dropna=False).first()
    return index.loc[:, ["state", "name_norm", "government_unit_id", "unit_name"]], ambiguous


def _organization(**fields: object) -> dict[str, object]:
    if any(name not in fields for name in ORGANIZATION_COLUMNS):
        missing = [name for name in ORGANIZATION_COLUMNS if name not in fields]
        raise ValueError(f"Organization is missing fields: {', '.join(missing)}")
    if is_missing(fields["org_id"]):
        raise ValueError("Organization id is missing")
    return {name: fields[name] for name in ORGANIZATION_COLUMNS}
