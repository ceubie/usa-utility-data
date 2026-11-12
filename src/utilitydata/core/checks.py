"""Done-when checks for the drinking-water core."""

import pandas as pd

from utilitydata.core.config import BLOCKED_CASES
from utilitydata.core.schema import DECISION_COLUMNS, MANIFEST_COLUMNS
from utilitydata.core.text import require_columns


def require_decision_coverage(assertions: pd.DataFrame, decisions: pd.DataFrame) -> None:
    """Every assertion has one decision, and every decision names an assertion."""
    require_columns(assertions, ("assertion_id",), "assertions")
    require_columns(decisions, DECISION_COLUMNS, "match decisions")
    if bool(decisions["assertion_id"].isna().any()) or bool(decisions["assertion_id"].duplicated().any()):
        raise ValueError("Match decisions are missing an assertion id or repeat one")
    left = set(assertions["assertion_id"].astype(str))
    right = set(decisions["assertion_id"].astype(str))
    if left != right:
        raise ValueError(f"Match decisions do not cover assertions: missing {len(left - right)}, extra {len(right - left)}")


def federal_conflicts(assertions: pd.DataFrame, decisions: pd.DataFrame, override_ids: set[str]) -> pd.DataFrame:
    """Boundaries whose single federal PWSID was linked to some other system."""
    require_columns(assertions, ("assertion_id", "pwsid"), "assertions")
    require_columns(decisions, ("assertion_id", "system_id"), "match decisions")
    merged = assertions[["assertion_id", "pwsid"]].merge(decisions[["assertion_id", "system_id"]], on="assertion_id", how="inner")
    checked = merged.loc[merged["pwsid"].notna() & ~merged["assertion_id"].isin(override_ids)].copy()
    checked["expected"] = "SYS_PWS_" + checked["pwsid"].astype("string")
    return checked.loc[checked["system_id"].astype("string").ne(checked["expected"])]


def require_federal_links(assertions: pd.DataFrame, decisions: pd.DataFrame, override_ids: set[str]) -> None:
    """Raise when a single federal PWSID points at a different system."""
    conflicts = federal_conflicts(assertions, decisions, override_ids)
    if not conflicts.empty:
        example = conflicts["assertion_id"].iloc[0]
        raise ValueError(f"{len(conflicts)} federal PWSID boundaries link to a different system, for example {example}")


def cross_state_matches(assertions: pd.DataFrame, decisions: pd.DataFrame, systems: pd.DataFrame) -> pd.DataFrame:
    """Name and overlap links whose system state is not the boundary's geom_state."""
    require_columns(assertions, ("assertion_id", "geom_state"), "assertions")
    require_columns(decisions, ("assertion_id", "system_id", "method"), "match decisions")
    require_columns(systems, ("system_id", "primary_state"), "systems")
    named = decisions.loc[decisions["method"].isin(["name_state", "overlap"])]
    merged = named.merge(assertions[["assertion_id", "geom_state"]], on="assertion_id", how="left")
    merged = merged.merge(systems[["system_id", "primary_state"]], on="system_id", how="left")
    local = decisions.loc[decisions["system_id"].fillna("").astype(str).str.startswith("SYS_LOC_")]
    local = local.merge(assertions[["assertion_id", "geom_state"]], on="assertion_id", how="left")
    local = local.merge(systems[["system_id", "primary_state"]], on="system_id", how="left")
    combined = pd.concat([merged, local], ignore_index=True)
    if combined.empty:
        return combined
    left = combined["primary_state"].astype("string").fillna("")
    right = combined["geom_state"].astype("string").fillna("")
    return combined.loc[left.ne(right)]


def require_same_state(assertions: pd.DataFrame, decisions: pd.DataFrame, systems: pd.DataFrame) -> None:
    """Raise when a name or overlap link crosses a state line."""
    crossed = cross_state_matches(assertions, decisions, systems)
    if not crossed.empty:
        example = crossed["assertion_id"].iloc[0]
        raise ValueError(f"{len(crossed)} name matches cross a state line, for example {example}")


def require_service_systems(service_areas: pd.DataFrame, systems: pd.DataFrame) -> None:
    """Every service area system exists in the system table."""
    require_columns(service_areas, ("system_id",), "service areas")
    require_columns(systems, ("system_id",), "systems")
    missing = set(service_areas["system_id"].astype(str)) - set(systems["system_id"].astype(str))
    if missing:
        example = min(missing)
        raise ValueError(f"{len(missing)} service areas name a missing system, for example {example}")


def source_count_gaps(assertions: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Per-source assertion counts that differ from match decisions."""
    require_columns(assertions, ("assertion_id", "source_id"), "assertions")
    require_columns(decisions, ("assertion_id",), "match decisions")
    silver = assertions.groupby("source_id", dropna=False).size().rename("silver")
    linked = decisions[["assertion_id"]].merge(assertions[["assertion_id", "source_id"]], on="assertion_id", how="left")
    decided = linked.groupby("source_id", dropna=False).size().rename("decisions")
    counts = pd.concat([silver, decided], axis=1).fillna(0).astype(int)
    return counts.loc[counts["silver"].ne(counts["decisions"])]


def require_source_counts(assertions: pd.DataFrame, decisions: pd.DataFrame) -> None:
    """Raise when a source's assertion count does not reconcile."""
    gaps = source_count_gaps(assertions, decisions)
    if not gaps.empty:
        source_id = str(gaps.index[0])
        raise ValueError(f"Assertion counts do not reconcile, for example {source_id}")


def require_buildable_sources(manifest: pd.DataFrame, source_ids: set[str]) -> None:
    """Draft and empty-geometry snapshot rows are not core inputs."""
    require_columns(manifest, MANIFEST_COLUMNS, "snapshot manifest")
    blocked = manifest["status"].isin(["draft", "no_geometry"]) & manifest["source_id"].isin(source_ids)
    if bool(blocked.any()):
        examples = ", ".join(sorted(set(manifest.loc[blocked, "source_id"].astype(str)))[:5])
        raise ValueError(f"Draft or empty-geometry sources were consumed: {examples}")


def acceptance_blockers(sources: list, consumed: set[str]) -> list[dict[str, object]]:
    """Record acceptance cases whose required sources are still unreviewed.

    Consuming a required source that is still unreviewed raises. The case list
    lives in the config; this function does not special-case a source id.
    """
    by_id = {source.source_id: source for source in sources}
    reports: list[dict[str, object]] = []
    for case in BLOCKED_CASES:
        rows = []
        blocked = False
        for source_id in case.required_source_ids:
            source = by_id.get(source_id)
            if source is None:
                raise ValueError(f"Acceptance case source is not in the registry: {source_id}")
            was_consumed = source_id in consumed
            if was_consumed and not source.reviewed:
                raise ValueError(f"An unreviewed acceptance source was consumed: {source_id}")
            if not source.reviewed or not was_consumed:
                blocked = True
            rows.append({"source_id": source_id, "reviewed": bool(source.reviewed), "consumed": was_consumed})
        reports.append({
            "case_id": case.case_id,
            "status": "blocked" if blocked else "ready",
            "reason": case.reason if blocked else "Required sources are reviewed and present in this core build.",
            "sources": rows,
        })
    return reports
