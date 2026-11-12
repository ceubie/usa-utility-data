"""Link drinking-water boundaries to systems.

The order is fixed: an override wins, then one federal PWSID already in SDWA,
then one well-formed PWSID that is not in SDWA, then a same-state name or
overlap. Anything still unresolved keeps a stable local id and a review row.
"""

import random
import secrets
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from utilitydata.core.config import (
    FEDERAL_ID_SCORE,
    IOU_AUTO_ACCEPT,
    LOCAL_ID_HEX_LENGTH,
    MATCH_SAMPLE_SEED,
    MATCH_SAMPLE_SIZE,
    NAME_AUTO_ACCEPT,
    NAME_WITH_OVERLAP,
    REVIEW_QUEUE_LIMIT,
)
from utilitydata.core.geometry import area_ratio, equal_area, union_geometries
from utilitydata.core.schema import (
    ASSERTION_COLUMNS,
    DECISION_COLUMNS,
    OVERRIDE_COLUMNS,
    PWSID_CANDIDATE_COLUMNS,
    QUEUE_COLUMNS,
    REGISTRY_COLUMNS,
    SAMPLE_COLUMNS,
    WORKING_SYSTEM_COLUMNS,
)
from utilitydata.core.system import align_systems
from utilitydata.core.text import as_string, is_missing, normalize_name, require_columns

_LOCAL_ID = rf"^SYS_LOC_[0-9a-f]{{{LOCAL_ID_HEX_LENGTH}}}$"
_STATUSES = frozenset({"active", "inactive", "unknown"})


@dataclass(frozen=True)
class ScoredCandidate:
    """One same-state candidate and the scores used to accept or queue it."""

    system_id: str
    name_score: float
    iou: float | None = None


@dataclass(frozen=True)
class MatchResult:
    """Systems, decisions, and the review artifacts for one matching run."""

    systems: pd.DataFrame
    decisions: pd.DataFrame
    queue: pd.DataFrame
    sample: pd.DataFrame
    identifiers: pd.DataFrame
    registry_rows: int


def select_auto_match(candidates: Sequence[ScoredCandidate]) -> tuple[str | None, str | None]:
    """Return the one acceptable candidate, or nothing when the row must be queued.

    A single name at or above the auto-accept cutoff wins without an overlap
    score. Otherwise exactly one candidate must clear both the lower name
    cutoff and the overlap cutoff.
    """
    highs = [item for item in candidates if item.name_score >= NAME_AUTO_ACCEPT]
    if len(highs) == 1:
        return highs[0].system_id, "name_state"
    pending = [item for item in candidates if item.name_score >= NAME_WITH_OVERLAP and item.iou is None]
    if pending:
        raise ValueError("Overlap score is missing for a candidate at or above the name floor")
    overlaps = [
        item
        for item in candidates
        if item.name_score >= NAME_WITH_OVERLAP and item.iou is not None and item.iou >= IOU_AUTO_ACCEPT
    ]
    if len(overlaps) == 1:
        return overlaps[0].system_id, "overlap"
    return None, None


def match_water(
    assertions: pd.DataFrame,
    systems: pd.DataFrame,
    *,
    geometries: pd.Series | None,
    overrides: pd.DataFrame,
    candidates: pd.DataFrame,
    registry_path: Path,
    release: str,
) -> MatchResult:
    """Match every assertion. Rows are queued or given a local id instead of being dropped."""
    require_columns(assertions, ASSERTION_COLUMNS, "boundary assertions")
    require_columns(systems, WORKING_SYSTEM_COLUMNS, "systems")
    require_columns(overrides, OVERRIDE_COLUMNS, "match overrides")
    require_columns(candidates, PWSID_CANDIDATE_COLUMNS, "PWSID candidates")
    if not release:
        raise ValueError("A release is required to match assertions")
    if assertions.empty:
        raise ValueError("No assertions to match")
    assertions = _prepare_assertions(assertions)
    systems = align_systems(systems)
    if bool(assertions["assertion_id"].duplicated().any()):
        raise ValueError("Boundary assertion ids are not unique")
    geometries = _index_geometries(geometries)
    registry = _load_registry(registry_path)
    registry_index, used_ids = _registry_index(registry)
    override_rows, shells, registry, registry_index, used_ids = _apply_overrides(
        assertions, systems, overrides, registry, registry_index, used_ids, release
    )
    if shells:
        systems = align_systems(pd.concat([systems, pd.DataFrame(shells)], ignore_index=True))
    open_rows = assertions.loc[~assertions["assertion_id"].isin(set(override_rows["assertion_id"]))].copy() if not override_rows.empty else assertions
    sdwa_ids = set(systems.loc[systems["in_federal_registry"].fillna(False), "pwsid"].dropna().astype(str))
    federal, missing, unresolved = _split_identifiers(open_rows, sdwa_ids)
    _reject_case_collisions(missing["pwsid"], sdwa_ids)
    federal_rows = _federal_decisions(federal, systems, release)
    minted_systems, minted_ids, minted_rows = _mint_absent_pwsids(missing, release)
    if not minted_systems.empty:
        systems = align_systems(pd.concat([systems, minted_systems], ignore_index=True))
    polygons = _polygons(pd.concat([federal_rows, minted_rows], ignore_index=True), geometries)
    fuzzy_rows, queue_rows, local_systems, registry = _match_unresolved(
        unresolved, systems, candidates, polygons, geometries, registry, registry_index, used_ids, release
    )
    if not local_systems.empty:
        systems = align_systems(pd.concat([systems, local_systems], ignore_index=True))
    parts = [part.loc[:, list(DECISION_COLUMNS)] for part in (override_rows, federal_rows, minted_rows, fuzzy_rows) if not part.empty]
    decisions = _finish_decisions(pd.concat(parts, ignore_index=True))
    _require_cover(assertions, decisions)
    if bool(systems["system_id"].duplicated().any()):
        raise ValueError("System ids are not unique after matching")
    queue = _finish_queue(queue_rows)
    sample = draw_match_sample(_sample_pairs(fuzzy_rows))
    _write_registry(registry_path, registry)
    return MatchResult(systems, decisions, queue, sample, minted_ids, len(registry))


def draw_match_sample(pairs: pd.DataFrame) -> pd.DataFrame:
    """Draw auto-accepted and queued pairs. The draw is not a labelled measurement."""
    require_columns(pairs, SAMPLE_COLUMNS, "match sample pairs")
    if pairs.empty:
        return pairs.loc[:, list(SAMPLE_COLUMNS)]
    rng = random.Random(MATCH_SAMPLE_SEED)
    ordered = pairs.sort_values(["assertion_id"]).reset_index(drop=True)
    buckets = [
        ordered.loc[ordered["decision"].eq("auto_accept") & ordered["method"].eq("overlap")],
        ordered.loc[ordered["decision"].eq("auto_accept") & ordered["method"].eq("name_state")],
        ordered.loc[ordered["decision"].eq("queued")],
    ]
    chosen = []
    leftovers = []
    for bucket, target in zip(buckets, (40, 80, 80), strict=True):
        picked, rest = _split_sample(bucket.reset_index(drop=True), target, rng)
        chosen.append(picked)
        leftovers.append(rest)
    short = MATCH_SAMPLE_SIZE - sum(len(frame) for frame in chosen)
    if short > 0:
        pool = pd.concat(leftovers, ignore_index=True)
        picked, _rest = _split_sample(pool, short, rng)
        chosen.append(picked)
    sample = pd.concat(chosen, ignore_index=True).head(MATCH_SAMPLE_SIZE)
    return sample.loc[:, list(SAMPLE_COLUMNS)]


def _prepare_assertions(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.loc[:, list(ASSERTION_COLUMNS)].copy()
    for column in ("assertion_id", "source_id", "sector", "zone_role", "authority", "raw_name", "name_norm", "pwsid", "pwsid_raw", "geom_state", "licence", "grain", "activity_status", "review_reason"):
        prepared[column] = as_string(prepared[column])
    prepared["name_norm"] = prepared["name_norm"].mask(prepared["name_norm"].isna(), prepared["raw_name"].map(normalize_name)).astype("string")
    return prepared


def _index_geometries(geometries: pd.Series | None) -> pd.Series | None:
    if geometries is None:
        return None
    indexed = geometries.copy()
    indexed.index = indexed.index.astype(str)
    if bool(indexed.index.duplicated().any()):
        raise ValueError("Geometry ids are not unique")
    return indexed


def _split_identifiers(frame: pd.DataFrame, sdwa_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    has_id = frame["pwsid"].notna()
    in_registry = frame["pwsid"].astype("string").isin(sdwa_ids)
    return frame.loc[has_id & in_registry].copy(), frame.loc[has_id & ~in_registry].copy(), frame.loc[~has_id].copy()


def _reject_case_collisions(pwsids: pd.Series, sdwa_ids: set[str]) -> None:
    folded: dict[str, list[str]] = defaultdict(list)
    for identifier in sdwa_ids:
        folded[identifier.casefold()].append(identifier)
    for identifier in pwsids.dropna().astype(str).unique():
        hits = folded.get(identifier.casefold(), [])
        if hits and hits != [identifier]:
            raise ValueError(f"PWSID case does not match SDWA: {identifier}")


def _federal_decisions(frame: pd.DataFrame, systems: pd.DataFrame, release: str) -> pd.DataFrame:
    if frame.empty:
        return _blank_decisions()
    decisions = pd.DataFrame({
        "assertion_id": frame["assertion_id"],
        "system_id": "SYS_PWS_" + frame["pwsid"].astype("string"),
        "method": "federal_id",
        "score": FEDERAL_ID_SCORE,
        "evidence": "pwsid=" + frame["pwsid"].astype("string"),
        "decided_by": "rule",
        "release": release,
    })
    missing = set(decisions["system_id"].astype(str)) - set(systems["system_id"].astype(str))
    if missing:
        example = min(missing)
        raise ValueError(f"Federal PWSID has no system row: {example}")
    return decisions


def _mint_absent_pwsids(frame: pd.DataFrame, release: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return pd.DataFrame(columns=list(WORKING_SYSTEM_COLUMNS)), _blank_identifiers(), _blank_decisions()
    system_rows = []
    identifier_rows = []
    for pwsid, group in frame.groupby("pwsid", sort=True):
        identifier = str(pwsid)
        system_id = f"SYS_PWS_{identifier}"
        sectors = sorted(set(group["sector"].dropna().astype(str)))
        if len(sectors) != 1:
            raise ValueError(f"PWSID {identifier} was asserted in more than one sector")
        statuses = [str(value) for value in group["activity_status"].dropna().unique()]
        unexpected = sorted(set(statuses) - _STATUSES)
        if unexpected:
            raise ValueError(f"Unmapped activity status on PWSID {identifier}: {', '.join(unexpected)}")
        system_rows.append(_new_system(
            system_id=system_id,
            sector=sectors[0],
            name=_stable_text(group["raw_name"]),
            status=statuses[0] if len(statuses) == 1 else "unknown",
            primary_state=_single_mode(group["geom_state"]),
            release=release,
            pwsid=identifier,
            name_norm=_stable_text(group["name_norm"]),
        ))
        for source_id in sorted(set(group["source_id"].dropna().astype(str))):
            identifier_rows.append({"system_id": system_id, "scheme": "pwsid", "value": identifier, "source_id": source_id})
    decisions = pd.DataFrame({
        "assertion_id": frame["assertion_id"],
        "system_id": "SYS_PWS_" + frame["pwsid"].astype("string"),
        "method": "new_entity",
        "score": pd.NA,
        "evidence": "pwsid_not_in_sdwa;pwsid=" + frame["pwsid"].astype("string"),
        "decided_by": "rule",
        "release": release,
    })
    return pd.DataFrame(system_rows), pd.DataFrame(identifier_rows), decisions


def _match_unresolved(
    frame: pd.DataFrame,
    systems: pd.DataFrame,
    pwsid_candidates: pd.DataFrame,
    polygons: dict[str, object],
    geometries: pd.Series | None,
    registry: pd.DataFrame,
    registry_index: dict[tuple[str, str | None, str], str],
    used_ids: set[str],
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return _blank_fuzzy(), _blank_queue(), pd.DataFrame(columns=list(WORKING_SYSTEM_COLUMNS)), registry
    unnamed = frame.loc[frame["name_norm"].isna()].copy()
    named = frame.loc[frame["name_norm"].notna()].copy()
    scored, summary = _score_names(named, systems)
    print(f"name candidates: {len(scored)}; names scored: {len(summary)}", flush=True)
    auto_rows, pending = _apply_unique_names(named, scored, summary, release)
    pending_rows, pending_queue = _decide_pending(pending, scored, summary, polygons, geometries, release)
    unnamed_rows, unnamed_queue = _unnamed_rows(unnamed, pwsid_candidates, release)
    fuzzy = pd.concat([auto_rows, pending_rows, unnamed_rows], ignore_index=True)
    queue = pd.concat([pending_queue, unnamed_queue], ignore_index=True)
    local_systems, registry = _assign_local_ids(fuzzy, registry, registry_index, used_ids, release)
    fuzzy = _attach_local_ids(fuzzy, registry_index)
    queue = _attach_queue_ids(queue, fuzzy)
    return fuzzy, queue, local_systems, registry


def _score_names(assertions: pd.DataFrame, systems: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = ["geom_state", "name_norm", "system_id", "candidate_name", "name_score", "rank"]
    summary_columns = ["geom_state", "name_norm", "n_at_least_95", "n_candidates"]
    if assertions.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=summary_columns)
    choices = systems.loc[systems["name_norm"].notna() & systems["primary_state"].notna(), ["system_id", "primary_state", "name", "name_norm"]]
    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    located = assertions.loc[assertions["geom_state"].notna()]
    for state, names in located.groupby("geom_state", sort=True)["name_norm"]:
        query_names = [str(name) for name in pd.unique(names.dropna())]
        pool = choices.loc[choices["primary_state"].astype(str).eq(str(state))]
        if bool(pool["system_id"].duplicated().any()):
            raise ValueError(f"Duplicate system id while scoring {state}")
        if not query_names:
            continue
        if pool.empty:
            summaries.extend({"geom_state": state, "name_norm": name, "n_at_least_95": 0, "n_candidates": 0} for name in query_names)
            continue
        choice_ids = pool["system_id"].astype(str).tolist()
        choice_names = pool["name_norm"].astype(str).tolist()
        choice_labels = pool["name"].astype("string").tolist()
        matrix = np.asarray(process.cdist(query_names, choice_names, scorer=fuzz.token_set_ratio, workers=-1), dtype=float)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.shape != (len(query_names), len(choice_names)):
            raise ValueError(f"Name score matrix for {state} has shape {matrix.shape}")
        for index, name in enumerate(query_names):
            scores = matrix[index]
            summaries.append({
                "geom_state": state,
                "name_norm": name,
                "n_at_least_95": int((scores >= NAME_AUTO_ACCEPT).sum()),
                "n_candidates": len(scores),
            })
            above = np.flatnonzero(scores >= NAME_WITH_OVERLAP)
            if len(scores) > REVIEW_QUEUE_LIMIT:
                top = np.argpartition(scores, -REVIEW_QUEUE_LIMIT)[-REVIEW_QUEUE_LIMIT:]
            else:
                top = np.arange(len(scores))
            keep = set(above.tolist()) | set(top.tolist())
            ordered = sorted(keep, key=lambda item: (-float(scores[item]), choice_ids[item]))
            for rank, choice in enumerate(ordered, start=1):
                rows.append({
                    "geom_state": state,
                    "name_norm": name,
                    "system_id": choice_ids[choice],
                    "candidate_name": choice_labels[choice],
                    "name_score": float(scores[choice]),
                    "rank": rank,
                })
        print(f"scored {state}: {len(query_names)} names, {len(choice_names)} systems", flush=True)
    return pd.DataFrame(rows, columns=columns), pd.DataFrame(summaries, columns=summary_columns)


def _apply_unique_names(assertions: pd.DataFrame, scored: pd.DataFrame, summary: pd.DataFrame, release: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    located = assertions.loc[assertions["geom_state"].notna()].copy()
    if located.empty:
        return _blank_fuzzy(), assertions.copy()
    merged = located.merge(summary, on=["geom_state", "name_norm"], how="left")
    if bool(merged["n_at_least_95"].isna().any()):
        raise ValueError("Name score summary is missing for an assertion")
    winners = summary.loc[summary["n_at_least_95"].eq(1), ["geom_state", "name_norm"]]
    winner_rows = scored.merge(winners, on=["geom_state", "name_norm"], how="inner")
    winner_rows = winner_rows.loc[winner_rows["name_score"] >= NAME_AUTO_ACCEPT]
    if bool(winner_rows.duplicated(["geom_state", "name_norm"]).any()):
        raise ValueError("More than one name candidate cleared the auto-accept cutoff")
    accepted = merged.loc[merged["n_at_least_95"].eq(1)].merge(winner_rows, on=["geom_state", "name_norm"], how="left")
    if accepted.empty:
        return _blank_fuzzy(), assertions.copy()
    if bool(accepted["system_id"].isna().any()):
        raise ValueError("A unique name score has no candidate row")
    accepted["method"] = "name_state"
    accepted["result_system_id"] = accepted["system_id"]
    accepted["candidate_system_id"] = accepted["system_id"]
    accepted["score"] = accepted["name_score"]
    accepted["iou"] = pd.NA
    accepted["decision"] = "auto_accept"
    accepted["decided_by"] = "rule"
    accepted["reason"] = pd.NA
    accepted["evidence"] = _name_evidence(accepted, "name_state")
    pending = assertions.loc[~assertions["assertion_id"].isin(set(accepted["assertion_id"]))].copy()
    return _fuzzy_frame(accepted, release), pending


def _decide_pending(
    assertions: pd.DataFrame,
    scored: pd.DataFrame,
    summary: pd.DataFrame,
    polygons: dict[str, object],
    geometries: pd.Series | None,
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if assertions.empty:
        return _blank_fuzzy(), _blank_queue()
    summary_lookup = {
        (str(row.geom_state), str(row.name_norm)): (int(row.n_at_least_95), int(row.n_candidates))
        for row in summary.itertuples(index=False)
    }
    candidate_groups: dict[tuple[str, str], pd.DataFrame] = {}
    if not scored.empty:
        for key, group in scored.groupby(["geom_state", "name_norm"], sort=False):
            candidate_groups[(str(key[0]), str(key[1]))] = group
    projected: dict[str, object] = {}
    records: list[dict[str, object]] = []
    queue_records: list[dict[str, object]] = []
    for key, group in assertions.groupby(["sector", "geom_state", "name_norm"], dropna=False, sort=False):
        _sector, state, name = key
        if is_missing(state) or is_missing(name):
            reason = "missing_geom_state" if is_missing(state) else "below_threshold"
            records.extend(_queue_records(group, None, reason, release))
            queue_records.extend(_queue_candidate_rows(group, None, reason))
            continue
        summary_key = (str(state), str(name))
        if summary_key not in summary_lookup:
            raise ValueError(f"Name score summary is missing for {state} {name}")
        n_high, n_candidates = summary_lookup[summary_key]
        pool = candidate_groups.get(summary_key, pd.DataFrame(columns=scored.columns))
        if n_candidates and pool.empty:
            raise ValueError(f"Name candidates are missing for {state} {name}")
        base = [
            ScoredCandidate(str(row.system_id), float(row.name_score), None)
            for row in pool.itertuples(index=False)
        ]
        if n_candidates == 0 or not any(item.name_score >= NAME_WITH_OVERLAP for item in base):
            reason = "no_same_state_candidate" if n_candidates == 0 else "below_threshold"
            if n_high > 1:
                reason = "ambiguous"
            records.extend(_queue_records(group, pool, reason, release))
            queue_records.extend(_queue_candidate_rows(group, pool, reason))
            continue
        flags = _area_flags(group["assertion_id"], geometries).to_numpy()
        zero = group.iloc[~flags]
        positive = group.iloc[flags]
        if not zero.empty:
            filled = _with_iou(base, {item.system_id: 0.0 for item in base})
            chosen, method = select_auto_match(filled)
            if chosen is None:
                reason = "ambiguous" if n_high > 1 else "below_threshold"
                records.extend(_queue_records(zero, pool, reason, release))
                queue_records.extend(_queue_candidate_rows(zero, pool, reason))
            else:
                records.extend(_accept_records(zero, pool, chosen, method, filled, release))
        for row in positive.itertuples(index=False):
            geometry = None if geometries is None else geometries.get(str(row.assertion_id))
            query = equal_area(geometry)
            ratios = {
                item.system_id: area_ratio(query, _projected_system(item.system_id, polygons, projected))
                for item in base
            }
            filled = _with_iou(base, ratios)
            chosen, method = select_auto_match(filled)
            one = group.loc[group["assertion_id"].eq(row.assertion_id)]
            if chosen is None:
                overlap_hits = sum(item.iou is not None and item.iou >= IOU_AUTO_ACCEPT and item.name_score >= NAME_WITH_OVERLAP for item in filled)
                reason = "ambiguous" if n_high > 1 or overlap_hits > 1 else "below_threshold"
                records.extend(_queue_records(one, pool, reason, release))
                queue_records.extend(_queue_candidate_rows(one, pool, reason))
            else:
                records.extend(_accept_records(one, pool, chosen, method, filled, release))
    fuzzy = pd.DataFrame(records)
    queue = pd.DataFrame(queue_records)
    return _fuzzy_frame(fuzzy, release) if not fuzzy.empty else _blank_fuzzy(), queue


def _unnamed_rows(frame: pd.DataFrame, candidates: pd.DataFrame, release: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return _blank_fuzzy(), _blank_queue()
    listed = _listed_candidates(candidates)
    records = []
    queue_records = []
    for row in frame.itertuples(index=False):
        reason = "unnamed_without_federal_id"
        if isinstance(row.review_reason, str) and "multiple_identifiers" in row.review_reason:
            reason = f"{reason}|multiple_identifiers"
        suffix = _suffix(row.pwsid, row.pwsid_raw, row.review_reason)
        listed_ids = listed.get(str(row.assertion_id))
        candidate_text = "" if listed_ids is None or (isinstance(listed_ids, float) and pd.isna(listed_ids)) else str(listed_ids)
        evidence = reason + suffix + (f";candidates={candidate_text}" if candidate_text and candidate_text != "<NA>" else "")
        records.append({
            "assertion_id": row.assertion_id,
            "source_id": row.source_id,
            "sector": row.sector,
            "geom_state": row.geom_state,
            "name_norm": pd.NA,
            "raw_name": row.raw_name,
            "result_system_id": pd.NA,
            "method": pd.NA,
            "score": pd.NA,
            "evidence": evidence,
            "decided_by": "pending_review",
            "decision": "unmatched",
            "candidate_system_id": pd.NA,
            "candidate_name": pd.NA,
            "name_score": pd.NA,
            "iou": pd.NA,
            "reason": reason,
            "release": release,
        })
        queue_records.append(_queue_row(row, None, reason))
    return _fuzzy_frame(pd.DataFrame(records), release), pd.DataFrame(queue_records)


def _assign_local_ids(
    fuzzy: pd.DataFrame,
    registry: pd.DataFrame,
    registry_index: dict[tuple[str, str | None, str], str],
    used_ids: set[str],
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    queued = fuzzy.loc[fuzzy["decided_by"].eq("pending_review") & fuzzy["name_norm"].notna()]
    if queued.empty:
        return pd.DataFrame(columns=list(WORKING_SYSTEM_COLUMNS)), registry
    keys = queued.loc[:, ["sector", "geom_state", "name_norm", "raw_name"]].copy()
    keys["activity_status"] = queued["activity_status"] if "activity_status" in queued.columns else pd.NA
    keys["state_key"] = keys["geom_state"].map(lambda value: "" if is_missing(value) else str(value))
    new_rows = []
    distinct = keys.loc[:, ["sector", "state_key", "name_norm"]].drop_duplicates()
    for sector, state_key, name in distinct.itertuples(index=False):
        key = (str(sector), None if state_key == "" else str(state_key), str(name))
        if key not in registry_index:
            registry_index[key] = _mint_local_id(used_ids)
            new_rows.append({"sector": key[0], "state": key[1], "name_norm": key[2], "system_id": registry_index[key], "release": release})
    if new_rows:
        registry = pd.concat([registry, pd.DataFrame(new_rows)], ignore_index=True)
        registry = _normalize_registry(registry)
        if bool(registry.duplicated(["sector", "state", "name_norm"]).any()) or bool(registry["system_id"].duplicated().any()):
            raise ValueError("Local id registry would reuse an id or a key")
    system_rows = []
    seen: set[str] = set()
    for sector, state_key, name in distinct.itertuples(index=False):
        key = (str(sector), None if state_key == "" else str(state_key), str(name))
        system_id = registry_index[key]
        if system_id in seen:
            continue
        seen.add(system_id)
        same = keys["sector"].astype(str).eq(str(sector)) & keys["state_key"].eq(state_key) & keys["name_norm"].astype(str).eq(str(name))
        observed_statuses = [str(v) for v in keys.loc[same, "activity_status"].dropna().unique() if not is_missing(v)]
        resolved_status = observed_statuses[0] if len(observed_statuses) == 1 and observed_statuses[0] in _STATUSES else "unknown"
        system_rows.append(_new_system(
            system_id=system_id,
            sector=str(sector),
            name=_stable_text(keys.loc[same, "raw_name"]),
            status=resolved_status,
            primary_state=pd.NA if state_key == "" else str(state_key),
            release=release,
            name_norm=str(name),
        ))
    return pd.DataFrame(system_rows), registry


def _attach_local_ids(fuzzy: pd.DataFrame, registry_index: dict[tuple[str, str | None, str], str]) -> pd.DataFrame:
    attached = fuzzy.copy()
    if "system_id" not in attached.columns:
        attached["system_id"] = attached.get("result_system_id")
    local = attached["decided_by"].eq("pending_review") & attached["name_norm"].notna() & attached["result_system_id"].isna()
    if not bool(local.any()):
        return attached
    subset = attached.loc[local]
    identifiers = [
        registry_index[(str(sector), None if is_missing(state) else str(state), str(name))]
        for sector, state, name in zip(subset["sector"], subset["geom_state"], subset["name_norm"], strict=True)
    ]
    attached.loc[local, "result_system_id"] = identifiers
    attached.loc[local, "system_id"] = identifiers
    attached.loc[local, "method"] = "new_entity"
    return attached


def _attach_queue_ids(queue: pd.DataFrame, fuzzy: pd.DataFrame) -> pd.DataFrame:
    if queue.empty:
        return _blank_queue()
    local = fuzzy.loc[:, ["assertion_id", "result_system_id"]].drop_duplicates("assertion_id")
    merged = queue.drop(columns=["queued_system_id"], errors="ignore").merge(local, on="assertion_id", how="left")
    merged["queued_system_id"] = merged["result_system_id"]
    return merged


def _apply_overrides(
    assertions: pd.DataFrame,
    systems: pd.DataFrame,
    overrides: pd.DataFrame,
    registry: pd.DataFrame,
    registry_index: dict[tuple[str, str | None, str], str],
    used_ids: set[str],
    release: str,
) -> tuple[pd.DataFrame, list[dict[str, object]], pd.DataFrame, dict[tuple[str, str | None, str], str], set[str]]:
    if overrides.empty:
        return _blank_decisions(), [], registry, registry_index, used_ids
    prepared = overrides.copy()
    for column in OVERRIDE_COLUMNS:
        prepared[column] = as_string(prepared[column])
    if bool(prepared["assertion_id"].isna().any()) or bool(prepared["system_id"].isna().any()):
        raise ValueError("Match overrides need an assertion id and a system id")
    if bool(prepared["assertion_id"].duplicated().any()):
        raise ValueError("Match overrides repeat an assertion id")
    missing = set(prepared["assertion_id"].astype(str)) - set(assertions["assertion_id"].astype(str))
    if missing:
        raise ValueError(f"Match override names an unknown assertion: {min(missing)}")
    prepared["decided_by"] = prepared["decided_by"].fillna("override")
    known = set(systems["system_id"].astype(str))
    shells = []
    new_registry = []
    assertion_index = assertions.set_index("assertion_id")
    for row in prepared.itertuples(index=False):
        system_id = str(row.system_id)
        if system_id in known:
            continue
        assertion = assertion_index.loc[row.assertion_id]
        pwsid = pd.NA
        in_registry = False
        if system_id.startswith("SYS_PWS_") and len(system_id) > len("SYS_PWS_"):
            pwsid = system_id[len("SYS_PWS_"):]
        shells.append(_new_system(
            system_id=system_id,
            sector=str(assertion["sector"]),
            name=assertion["raw_name"],
            status="unknown",
            primary_state=assertion["geom_state"],
            release=release,
            pwsid=pwsid,
            name_norm=assertion["name_norm"],
            in_federal_registry=in_registry,
        ))
        known.add(system_id)
        if pd.Series([system_id]).str.fullmatch(_LOCAL_ID).iloc[0]:
            key = (
                str(assertion["sector"]),
                None if is_missing(assertion["geom_state"]) else str(assertion["geom_state"]),
                str(assertion["name_norm"]) if not is_missing(assertion["name_norm"]) else "",
            )
            current = registry_index.get(key)
            if current is not None and current != system_id:
                raise ValueError(f"Match override local id conflicts with the id registry: {system_id}")
            if system_id in used_ids and current != system_id:
                raise ValueError(f"Match override reuses a local id: {system_id}")
            if current is None:
                registry_index[key] = system_id
                used_ids.add(system_id)
                new_registry.append({"sector": key[0], "state": key[1], "name_norm": key[2], "system_id": system_id, "release": release})
    if new_registry:
        registry = _normalize_registry(pd.concat([registry, pd.DataFrame(new_registry)], ignore_index=True))
    notes = prepared["notes"]
    evidence = np.where(notes.isna(), "override", "override;" + notes.astype("string"))
    decisions = pd.DataFrame({
        "assertion_id": prepared["assertion_id"],
        "system_id": prepared["system_id"],
        "method": "manual",
        "score": pd.NA,
        "evidence": evidence,
        "decided_by": prepared["decided_by"],
        "release": release,
    })
    return decisions, shells, registry, registry_index, used_ids


def _polygons(decisions: pd.DataFrame, geometries: pd.Series | None) -> dict[str, object]:
    if decisions.empty or geometries is None:
        return {}
    parts: dict[str, list] = defaultdict(list)
    for assertion_id, system_id in zip(decisions["assertion_id"].astype(str), decisions["system_id"].astype(str), strict=True):
        geometry = geometries.get(assertion_id)
        if geometry is not None and not geometry.is_empty and geometry.area > 0:
            parts[system_id].append(geometry)
    polygons = {}
    for index, (system_id, geometries_for_system) in enumerate(parts.items(), start=1):
        polygons[system_id] = geometries_for_system[0] if len(geometries_for_system) == 1 else union_geometries(geometries_for_system)
        if index % 5000 == 0:
            print(f"system polygons: {index}", flush=True)
    return polygons


def _area_flags(assertion_ids: pd.Series, geometries: pd.Series | None) -> pd.Series:
    if geometries is None:
        return pd.Series(False, index=assertion_ids.index)
    flags = []
    for assertion_id in assertion_ids.astype(str):
        geometry = geometries.get(assertion_id)
        flags.append(geometry is not None and not geometry.is_empty and geometry.area > 0)
    return pd.Series(flags, index=assertion_ids.index)


def _with_iou(candidates: list[ScoredCandidate], ratios: dict[str, float]) -> list[ScoredCandidate]:
    filled = []
    for item in candidates:
        iou = ratios.get(item.system_id, 0.0) if item.name_score >= NAME_WITH_OVERLAP else item.iou
        filled.append(ScoredCandidate(item.system_id, item.name_score, iou))
    return filled


def _projected_system(system_id: str, polygons: dict[str, object], cache: dict[str, object]):
    if system_id not in cache:
        cache[system_id] = equal_area(polygons.get(system_id))
    return cache[system_id]


def _queue_records(group: pd.DataFrame, pool: pd.DataFrame | None, reason: str, release: str) -> list[dict[str, object]]:
    top = None if pool is None or pool.empty else pool.sort_values(["rank", "system_id"]).iloc[0]
    records = []
    for row in group.itertuples(index=False):
        full_reason = _with_flags(reason, row.review_reason)
        records.append({
            "assertion_id": row.assertion_id,
            "source_id": row.source_id,
            "sector": row.sector,
            "geom_state": row.geom_state,
            "name_norm": row.name_norm,
            "raw_name": row.raw_name,
            "result_system_id": pd.NA,
            "method": "new_entity",
            "score": None if top is None else float(top.name_score),
            "evidence": _provisional_evidence(top, row),
            "decided_by": "pending_review",
            "decision": "queued",
            "candidate_system_id": None if top is None else top.system_id,
            "candidate_name": None if top is None else top.candidate_name,
            "name_score": None if top is None else float(top.name_score),
            "iou": pd.NA,
            "reason": full_reason,
            "release": release,
        })
    return records


def _queue_candidate_rows(group: pd.DataFrame, pool: pd.DataFrame | None, reason: str) -> list[dict[str, object]]:
    ranked = pd.DataFrame(columns=["system_id", "candidate_name", "name_score", "rank"]) if pool is None else pool.loc[pool["rank"] <= REVIEW_QUEUE_LIMIT]
    rows = []
    for assertion in group.itertuples(index=False):
        full_reason = _with_flags(reason, assertion.review_reason)
        if ranked.empty:
            rows.append(_queue_row(assertion, None, full_reason))
            continue
        for candidate in ranked.itertuples(index=False):
            rows.append(_queue_row(assertion, candidate, full_reason))
    return rows


def _accept_records(group, pool, chosen: str, method: str, filled: list[ScoredCandidate], release: str) -> list[dict[str, object]]:
    selected = next(item for item in filled if item.system_id == chosen)
    label = pool.loc[pool["system_id"].astype(str).eq(chosen)]
    candidate_name = None if label.empty else label.iloc[0]["candidate_name"]
    records = []
    for row in group.itertuples(index=False):
        records.append({
            "assertion_id": row.assertion_id,
            "source_id": row.source_id,
            "sector": row.sector,
            "geom_state": row.geom_state,
            "name_norm": row.name_norm,
            "raw_name": row.raw_name,
            "result_system_id": chosen,
            "method": method,
            "score": selected.name_score,
            "evidence": _choice_evidence(method, selected, chosen) + _suffix(row.pwsid, row.pwsid_raw, row.review_reason),
            "decided_by": "rule",
            "decision": "auto_accept",
            "candidate_system_id": chosen,
            "candidate_name": candidate_name,
            "name_score": selected.name_score,
            "iou": pd.NA if selected.iou is None else selected.iou,
            "reason": pd.NA,
            "release": release,
        })
    return records


def _fuzzy_frame(frame: pd.DataFrame, release: str) -> pd.DataFrame:
    if frame.empty:
        return _blank_fuzzy()
    out = frame.copy()
    out["system_id"] = out["result_system_id"]
    out["release"] = release
    return out


def _sample_pairs(fuzzy: pd.DataFrame) -> pd.DataFrame:
    if fuzzy.empty:
        return pd.DataFrame(columns=list(SAMPLE_COLUMNS))
    pairs = fuzzy.loc[fuzzy["decision"].isin(["auto_accept", "queued"]) & fuzzy["candidate_system_id"].notna()].copy()
    if pairs.empty:
        return pd.DataFrame(columns=list(SAMPLE_COLUMNS))
    return pd.DataFrame({
        "assertion_id": pairs["assertion_id"],
        "source_id": pairs["source_id"],
        "geom_state": pairs["geom_state"],
        "assertion_name": pairs["raw_name"],
        "candidate_system_id": pairs["candidate_system_id"],
        "candidate_name": pairs["candidate_name"],
        "name_score": pairs["name_score"],
        "iou": pairs["iou"],
        "decision": pairs["decision"],
        "method": pairs["method"],
        "result_system_id": pairs["result_system_id"],
    })


def _split_sample(frame: pd.DataFrame, count: int, rng: random.Random) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty or count <= 0:
        return frame.iloc[0:0], frame
    if len(frame) <= count:
        return frame, frame.iloc[0:0]
    picked = np.zeros(len(frame), dtype=bool)
    picked[rng.sample(range(len(frame)), count)] = True
    return frame.iloc[picked], frame.iloc[~picked]


def _finish_decisions(frame: pd.DataFrame) -> pd.DataFrame:
    finished = frame.loc[:, list(DECISION_COLUMNS)].copy()
    for column in ("assertion_id", "system_id", "method", "evidence", "decided_by", "release"):
        finished[column] = finished[column].astype("string")
    finished["score"] = pd.to_numeric(finished["score"], errors="coerce").astype("Float64")
    return finished.reset_index(drop=True)


def _finish_queue(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _blank_queue()
    finished = frame.copy()
    if "queued_system_id" not in finished.columns:
        finished["queued_system_id"] = pd.NA
    finished = finished.loc[:, list(QUEUE_COLUMNS)]
    for column in ("assertion_id", "source_id", "candidate_system_id", "geom_state", "name_norm", "queued_system_id", "reason"):
        finished[column] = finished[column].astype("string")
    finished["rank"] = pd.to_numeric(finished["rank"], errors="coerce").astype("Int64")
    finished["name_score"] = pd.to_numeric(finished["name_score"], errors="coerce").astype("Float64")
    finished["iou"] = pd.to_numeric(finished["iou"], errors="coerce").astype("Float64")
    return finished.sort_values(["assertion_id", "rank"], na_position="last").reset_index(drop=True)


def _require_cover(assertions: pd.DataFrame, decisions: pd.DataFrame) -> None:
    if bool(decisions["assertion_id"].duplicated().any()):
        raise ValueError("Match decisions repeat an assertion")
    left = set(assertions["assertion_id"].astype(str))
    right = set(decisions["assertion_id"].astype(str))
    if left != right:
        raise ValueError(f"Match decisions do not cover assertions: missing {len(left - right)}, extra {len(right - left)}")


def _load_registry(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(REGISTRY_COLUMNS))
    frame = pd.read_parquet(path)
    require_columns(frame, REGISTRY_COLUMNS, "id registry")
    frame = _normalize_registry(frame)
    if bool(frame.duplicated(["sector", "state", "name_norm"]).any()):
        raise ValueError("id registry repeats a sector, state, and name")
    if bool(frame["system_id"].duplicated().any()):
        raise ValueError("id registry reuses a local system id")
    if not bool(frame["system_id"].str.fullmatch(_LOCAL_ID).fillna(False).all()):
        raise ValueError("id registry has a system id that is not a local id")
    return frame


def _write_registry(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _normalize_registry(frame).to_parquet(path, index=False)


def _normalize_registry(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.loc[:, list(REGISTRY_COLUMNS)].copy()
    for column in REGISTRY_COLUMNS:
        normalized[column] = normalized[column].astype("string")
    return normalized.reset_index(drop=True)


def _registry_index(frame: pd.DataFrame) -> tuple[dict[tuple[str, str | None, str], str], set[str]]:
    index: dict[tuple[str, str | None, str], str] = {}
    used: set[str] = set()
    for row in frame.itertuples(index=False):
        key = (str(row.sector), None if is_missing(row.state) else str(row.state), str(row.name_norm))
        index[key] = str(row.system_id)
        used.add(str(row.system_id))
    return index, used


def _mint_local_id(used: set[str]) -> str:
    if LOCAL_ID_HEX_LENGTH % 2:
        raise ValueError("Local id hex length must be even")
    for _attempt in range(100):
        identifier = "SYS_LOC_" + secrets.token_hex(LOCAL_ID_HEX_LENGTH // 2)
        if identifier not in used:
            used.add(identifier)
            return identifier
    raise ValueError("Could not mint a local system id")


def _new_system(
    *,
    system_id: str,
    sector: object,
    name: object,
    status: str,
    primary_state: object,
    release: str,
    pwsid: object = pd.NA,
    name_norm: object = pd.NA,
    in_federal_registry: bool = False,
) -> dict[str, object]:
    return {
        "system_id": system_id,
        "sector": sector,
        "name": name,
        "status": status,
        "system_type": pd.NA,
        "primary_state": primary_state,
        "population_served": pd.NA,
        "service_connections": pd.NA,
        "customers": pd.NA,
        "sales_mwh": pd.NA,
        "owner_org_id": pd.NA,
        "operator_org_id": pd.NA,
        "in_federal_registry": in_federal_registry,
        "first_seen_release": release,
        "last_seen_release": release,
        "pwsid": pwsid,
        "name_norm": name_norm,
        "owner_type": pd.NA,
        "owner_type_code": pd.NA,
    }


def _blank_decisions() -> pd.DataFrame:
    return pd.DataFrame(columns=list(DECISION_COLUMNS))


def _blank_identifiers() -> pd.DataFrame:
    return pd.DataFrame(columns=["system_id", "scheme", "value", "source_id"])


def _blank_queue() -> pd.DataFrame:
    return pd.DataFrame(columns=list(QUEUE_COLUMNS))


def _blank_fuzzy() -> pd.DataFrame:
    return pd.DataFrame(columns=list(DECISION_COLUMNS) + ["decision", "candidate_system_id", "candidate_name", "name_score", "iou", "raw_name", "source_id", "sector", "geom_state", "name_norm", "result_system_id"])


def _name_evidence(frame: pd.DataFrame, method: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="string")
    score = frame["name_score"].map(lambda value: _format_number(float(value))).astype("string")
    base = "name_score=" + score + ";candidate=" + frame["result_system_id"].astype("string")
    if method == "overlap":
        base = "iou=" + frame["iou"].map(lambda value: _format_number(float(value))) + ";" + base
    suffix = [
        _suffix(pwsid, raw, review)
        for pwsid, raw, review in zip(frame["pwsid"], frame["pwsid_raw"], frame["review_reason"], strict=True)
    ]
    return base + pd.Series(suffix, index=frame.index)


def _choice_evidence(method: str, selected: ScoredCandidate, system_id: str) -> str:
    text = f"name_score={_format_number(selected.name_score)};candidate={system_id}"
    if method == "overlap" and selected.iou is not None:
        return f"iou={_format_number(selected.iou)};{text}"
    return text


def _provisional_evidence(top, row) -> str:
    if top is None:
        base = "provisional;no_same_state_candidate"
    else:
        base = f"provisional;best_name_score={_format_number(float(top.name_score))};candidate={top.system_id}"
    return base + _suffix(row.pwsid, row.pwsid_raw, row.review_reason)


def _suffix(pwsid, raw, review) -> str:
    parts = []
    if is_missing(pwsid) and not is_missing(raw):
        parts.append(f"raw={raw}")
    if isinstance(review, str) and "multiple_identifiers" in review:
        parts.append("multiple_identifiers")
    if not parts:
        return ""
    return ";" + ";".join(parts)


def _with_flags(reason: str, review) -> str:
    if isinstance(review, str) and "multiple_identifiers" in review and "multiple_identifiers" not in reason:
        return f"{reason}|multiple_identifiers"
    return reason


def _queue_row(assertion, candidate, reason: str) -> dict[str, object]:
    return {
        "assertion_id": assertion.assertion_id,
        "source_id": assertion.source_id,
        "rank": pd.NA if candidate is None else int(candidate.rank),
        "candidate_system_id": pd.NA if candidate is None else candidate.system_id,
        "name_score": pd.NA if candidate is None else float(candidate.name_score),
        "iou": pd.NA,
        "geom_state": assertion.geom_state,
        "name_norm": assertion.name_norm,
        "queued_system_id": pd.NA,
        "reason": reason,
    }


def _listed_candidates(candidates: pd.DataFrame) -> dict[str, str]:
    if candidates.empty:
        return {}
    work = candidates.dropna(subset=["candidate"]).copy()
    if work.empty:
        return {}
    if "ordinal" in work.columns:
        work = work.sort_values(["assertion_id", "ordinal"])
    else:
        work = work.sort_values(["assertion_id", "candidate"])
    grouped = work.groupby("assertion_id")["candidate"].agg(lambda values: ",".join(str(value) for value in values))
    return {str(key): str(value) for key, value in grouped.items()}


def _stable_text(series: pd.Series):
    values = sorted({str(value) for value in series.dropna().tolist() if not is_missing(value)})
    if not values:
        return pd.NA
    return values[0]


def _single_mode(series: pd.Series):
    present = series.dropna()
    if present.empty:
        return pd.NA
    counts = present.astype(str).value_counts()
    if int((counts == counts.iloc[0]).sum()) != 1:
        return pd.NA
    return counts.index[0]


def _format_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")
