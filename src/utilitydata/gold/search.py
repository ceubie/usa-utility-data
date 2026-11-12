"""Search rows for water-system names, alternate names, and identifiers."""

from __future__ import annotations

import pandas as pd

from utilitydata.core.text import as_string, require_columns
from utilitydata.gold.schema import SEARCH_COLUMNS
from utilitydata.gold.text import search_key

NORTH_ST_PAUL = ("North St. Paul", "CITY OF NORTH ST PAUL - (MN)")
_NAME_SCHEME = "name"


def build_entity_search(
    systems: pd.DataFrame,
    identifiers: pd.DataFrame,
    assertions: pd.DataFrame,
    organizations: pd.DataFrame,
    *,
    state_codes: set[str],
    federal_licence: str,
    licence_by_source: dict[str, str],
) -> pd.DataFrame:
    """Build one search row per name, alternate name, and identifier.

    Federal system names use the Safe Drinking Water Act licence. A label drawn
    from more than one licence stays ``unknown`` so it is not treated as shareable.
    """
    require_columns(systems, ("system_id", "name", "primary_state", "in_federal_registry", "owner_org_id"), "systems")
    require_columns(identifiers, ("system_id", "scheme", "value", "source_id"), "identifiers")
    require_columns(assertions, ("system_id", "label", "licence", "source_id"), "assertion names")
    require_columns(organizations, ("org_id", "name", "source_id"), "organizations")
    rows: list[pd.DataFrame] = []
    primary = _primary_rows(systems, federal_licence, state_codes)
    primary = _fill_local_licence(primary, assertions)
    rows.append(primary)
    rows.append(_alternate_rows(assertions, primary, state_codes, "alternate_name"))
    rows.append(_organization_rows(systems, organizations, licence_by_source, primary, state_codes))
    rows.append(_identifier_rows(identifiers, systems, licence_by_source))
    frame = pd.concat([frame for frame in rows if not frame.empty], ignore_index=True)
    frame = _collapse_licences(frame)
    if bool(frame.duplicated(["entity_id", "label_role", "label", "scheme"]).any()):
        raise ValueError("Entity search keys are not unique")
    missing_norm = frame["label"].notna() & frame["search_norm"].isna()
    if bool(missing_norm.any()):
        examples = frame.loc[missing_norm, "label"].head(5).tolist()
        raise ValueError(f"A search label has no search key, for example {examples!r}")
    return frame.loc[:, list(SEARCH_COLUMNS)].sort_values(
        ["entity_id", "label_role", "label", "scheme"], kind="mergesort"
    ).reset_index(drop=True)


def resolve_entities(frame: pd.DataFrame, query: str, *, state_codes: set[str]) -> set[str]:
    """Return the systems whose name key or identifier equals the query."""
    require_columns(frame, SEARCH_COLUMNS, "entity search")
    key = search_key(query, state_codes=state_codes)
    names = frame.loc[frame["scheme"].eq(_NAME_SCHEME) & frame["search_norm"].eq(key), "entity_id"]
    identifiers = frame.loc[frame["scheme"].ne(_NAME_SCHEME) & frame["label"].eq(query.strip()), "entity_id"]
    return set(names.dropna().astype(str)) | set(identifiers.dropna().astype(str))


def north_st_paul_status(frame: pd.DataFrame, *, state_codes: set[str]) -> dict[str, object]:
    """Report whether both North St. Paul labels are present and resolve together."""
    labels = set(frame.loc[frame["scheme"].eq(_NAME_SCHEME), "label"].dropna().astype(str))
    present = {text: text in labels for text in NORTH_ST_PAUL}
    if not all(present.values()):
        missing = [text for text, found in present.items() if not found]
        return {"present": present, "resolved_to_one_system": None, "missing_labels": missing}
    found = [resolve_entities(frame, text, state_codes=state_codes) for text in NORTH_ST_PAUL]
    return {
        "present": present,
        "resolved_to_one_system": len(found[0]) == 1 and found[0] == found[1],
        "entity_ids": sorted(found[0]),
        "missing_labels": [],
    }


def _primary_rows(systems: pd.DataFrame, federal_licence: str, state_codes: set[str]) -> pd.DataFrame:
    named = systems.loc[systems["name"].notna(), ["system_id", "name", "primary_state", "in_federal_registry"]].copy()
    named["label"] = as_string(named["name"])
    named = named.loc[named["label"].notna()]
    named["entity_id"] = named["system_id"]
    named["kind"] = "system"
    named["state"] = as_string(named["primary_state"])
    named["label_role"] = "primary_name"
    named["scheme"] = _NAME_SCHEME
    named["search_norm"] = named["label"].map(lambda value: search_key(value, state_codes=state_codes))
    named["licence"] = named["in_federal_registry"].map(lambda federal: federal_licence if bool(federal) else pd.NA)
    return named.loc[:, list(SEARCH_COLUMNS)]


def _alternate_rows(
    assertions: pd.DataFrame,
    primary: pd.DataFrame,
    state_codes: set[str],
    role: str,
) -> pd.DataFrame:
    if assertions.empty:
        return pd.DataFrame(columns=list(SEARCH_COLUMNS))
    frame = assertions.copy()
    frame["label"] = as_string(frame["label"])
    frame = frame.loc[frame["label"].notna() & frame["system_id"].notna()]
    known = primary.loc[:, ["entity_id", "label"]].rename(columns={"label": "primary_label"})
    frame = frame.merge(known, left_on="system_id", right_on="entity_id", how="left")
    frame = frame.loc[frame["primary_label"].isna() | frame["label"].ne(frame["primary_label"])]
    frame["entity_id"] = frame["system_id"]
    frame["kind"] = "system"
    frame["state"] = pd.NA
    frame["label_role"] = role
    frame["scheme"] = _NAME_SCHEME
    frame["search_norm"] = frame["label"].map(lambda value: search_key(value, state_codes=state_codes))
    states = primary.loc[:, ["entity_id", "state"]]
    frame = frame.drop(columns=["state"]).merge(states, on="entity_id", how="left")
    return frame.loc[:, ["entity_id", "kind", "state", "label", "label_role", "search_norm", "scheme", "licence"]]


def _organization_rows(
    systems: pd.DataFrame,
    organizations: pd.DataFrame,
    licence_by_source: dict[str, str],
    primary: pd.DataFrame,
    state_codes: set[str],
) -> pd.DataFrame:
    linked = systems.loc[systems["owner_org_id"].notna(), ["system_id", "owner_org_id", "primary_state"]]
    if linked.empty or organizations.empty:
        return pd.DataFrame(columns=list(SEARCH_COLUMNS))
    orgs = organizations.rename(columns={"name": "label"})
    merged = linked.merge(orgs, left_on="owner_org_id", right_on="org_id", how="left")
    if bool(merged["org_id"].isna().any()):
        example = merged.loc[merged["org_id"].isna(), "owner_org_id"].iloc[0]
        raise ValueError(f"System owner has no organization: {example}")
    merged["licence"] = merged["source_id"].map(licence_by_source)
    if bool(merged["licence"].isna().any()):
        raise ValueError("An organization source has no licence")
    merged["label"] = as_string(merged["label"])
    merged = merged.loc[merged["label"].notna()]
    return _alternate_rows(
        merged.rename(columns={"system_id": "system_id"})[["system_id", "label", "licence", "source_id"]],
        primary,
        state_codes,
        "alternate_name",
    )


def _identifier_rows(
    identifiers: pd.DataFrame,
    systems: pd.DataFrame,
    licence_by_source: dict[str, str],
) -> pd.DataFrame:
    frame = identifiers.copy()
    frame["value"] = as_string(frame["value"])
    frame["scheme"] = as_string(frame["scheme"])
    frame = frame.loc[frame["value"].notna() & frame["scheme"].notna()]
    frame["licence"] = frame["source_id"].map(licence_by_source)
    if bool(frame["licence"].isna().any()):
        raise ValueError("An identifier source has no licence")
    states = systems.loc[:, ["system_id", "primary_state"]].rename(columns={"system_id": "entity_id", "primary_state": "state"})
    frame["entity_id"] = frame["system_id"]
    frame = frame.merge(states, on="entity_id", how="left")
    frame["kind"] = "system"
    frame["label"] = frame["value"]
    frame["label_role"] = "identifier"
    frame["search_norm"] = frame["label"]
    frame["state"] = as_string(frame["state"])
    return frame.loc[:, list(SEARCH_COLUMNS)]


def _fill_local_licence(primary: pd.DataFrame, assertions: pd.DataFrame) -> pd.DataFrame:
    """Give a non-federal name the licence of its assertions when they agree."""
    filled = primary.copy()
    missing = filled["licence"].isna()
    if not bool(missing.any()) or assertions.empty:
        filled["licence"] = filled["licence"].fillna("unknown")
        return filled
    known = assertions.dropna(subset=["licence"])
    counts = known.groupby("system_id")["licence"].nunique()
    single = counts[counts.eq(1)]
    chosen = known.drop_duplicates("system_id").set_index("system_id")["licence"]
    local = missing & filled["entity_id"].isin(single.index)
    filled.loc[local, "licence"] = filled.loc[local, "entity_id"].map(chosen)
    filled["licence"] = filled["licence"].fillna("unknown")
    return filled


def _collapse_licences(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    keys = ["entity_id", "label_role", "label", "scheme"]
    frame = frame.copy()
    frame["licence"] = frame["licence"].astype("string")
    counts = frame.groupby(keys, dropna=False)["licence"].nunique(dropna=True)
    if bool((counts == 0).any()):
        raise ValueError("A search label has no licence")
    mixed = counts[counts > 1].reset_index()
    if not mixed.empty:
        mixed["_mixed"] = True
        frame = frame.merge(mixed[keys + ["_mixed"]], on=keys, how="left")
        frame.loc[frame["_mixed"].fillna(False), "licence"] = "unknown"
        frame = frame.drop(columns=["_mixed"])
    frame = frame.sort_values("licence", na_position="last", kind="mergesort")
    return frame.drop_duplicates(keys)
