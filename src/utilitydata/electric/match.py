"""Link electric zones that have no EIA utility id.

Candidates are utilities whose EIA-861 counties the zone overlaps. A link
requires the configured HIFLD overlap and name similarity, and otherwise an
exact normalized name in the same state. Anything else stays on the review
queue. The thresholds are starting values and are not calibrated.
"""

from __future__ import annotations

import pandas as pd
import shapely
from rapidfuzz import fuzz

from utilitydata.core.config import (
    ELECTRIC_HIFLD_OVERLAP,
    ELECTRIC_NAME_SIMILARITY,
    ELECTRIC_THRESHOLDS_CALIBRATED,
)
from utilitydata.core.geometry import covered_fraction
from utilitydata.core.text import normalize_name
from utilitydata.electric.schema import DECISION_COLUMNS, QUEUE_COLUMNS

RULE = "rule"


def zone_overlap(zone: object, territory: object) -> float:
    """Return the share of the zone area covered by the territory."""
    return covered_fraction(zone, territory)


def area_is_eligible(covered: set[str], reported: set[str]) -> bool:
    """Keep a polygon only when it does not add counties beyond the EIA-861 list.

    An empty cover is not eligible when the utility reported counties, so a
    misplaced polygon cannot outrank the county footprint.
    """
    if not reported:
        return True
    return bool(covered) and covered <= reported


def match_zones(
    zones: pd.DataFrame,
    geometries: pd.Series,
    *,
    county_geometries: list[object],
    county_index: list[str],
    counties_by_utility: dict[int, set[str]],
    utilities_by_county: dict[str, set[int]],
    names: dict[int, str],
    states: dict[int, set[str]],
    hifld_by_utility: dict[int, object],
    system_by_utility: dict[int, str],
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match zones that do not already carry an EIA utility id."""
    if ELECTRIC_THRESHOLDS_CALIBRATED:
        raise ValueError("Electric thresholds are marked calibrated without a recorded measurement")
    decisions: list[dict[str, object]] = []
    queue: list[dict[str, object]] = []
    if zones.empty:
        return _frames(decisions, queue)
    if len(county_geometries) != len(county_index):
        raise ValueError("County geometries and ids are not aligned")
    tree = shapely.STRtree(county_geometries)
    for record in zones.itertuples(index=False):
        geometry = geometries.get(record.assertion_id)
        if geometry is None:
            queue.append(_queue_row(record, None, None, None, "missing_geometry"))
            decisions.append(_decision(record.assertion_id, None, "review_queue", None, "missing_geometry", release))
            continue
        hits = tree.query(geometry, predicate="intersects")
        candidate_ids: set[int] = set()
        for index in hits:
            geoid = county_index[int(index)]
            candidate_ids.update(utilities_by_county.get(geoid, ()))
        scored = _score_candidates(record, geometry, candidate_ids, names, states, hifld_by_utility, counties_by_utility)
        choice, reason = _choose(scored)
        if choice is None:
            top = scored[0] if scored else None
            queue.append(_queue_row(
                record,
                None if top is None else system_by_utility.get(top[0]),
                None if top is None else top[1],
                None if top is None else top[2],
                reason,
            ))
            decisions.append(_decision(record.assertion_id, None, "review_queue", None if top is None else top[1], reason, release))
            continue
        utility_id, name_score, overlap, method = choice
        system_id = system_by_utility[utility_id]
        evidence = f"name_score={name_score:.1f};overlap={overlap:.3f};utility_id_eia={utility_id}"
        decisions.append(_decision(record.assertion_id, system_id, method, name_score, evidence, release))
    return _frames(decisions, queue)


def _score_candidates(
    record: object,
    geometry: object,
    candidate_ids: set[int],
    names: dict[int, str],
    states: dict[int, set[str]],
    hifld_by_utility: dict[int, object],
    counties_by_utility: dict[int, set[str]],
) -> list[tuple[int, float, float, bool]]:
    zone_name = normalize_name(record.raw_name)
    geom_state = record.geom_state
    scored: list[tuple[int, float, float, bool]] = []
    for utility_id in sorted(candidate_ids):
        if utility_id not in counties_by_utility:
            continue
        candidate_name = names.get(utility_id)
        name_score = float(fuzz.token_set_ratio(zone_name or "", candidate_name or ""))
        territory = hifld_by_utility.get(utility_id)
        overlap = zone_overlap(geometry, territory) if territory is not None else 0.0
        same_state = geom_state is not None and geom_state in states.get(utility_id, set())
        exact = bool(zone_name) and zone_name == normalize_name(candidate_name) and same_state
        scored.append((utility_id, name_score, overlap, exact))
    scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return scored


def _choose(scored: list[tuple[int, float, float, bool]]) -> tuple[tuple[int, float, float, str] | None, str]:
    if not scored:
        return None, "no_county_candidate"
    overlap_hits = [
        item for item in scored
        if item[2] >= ELECTRIC_HIFLD_OVERLAP and item[1] >= ELECTRIC_NAME_SIMILARITY
    ]
    if len(overlap_hits) == 1:
        utility_id, name_score, overlap, _exact = overlap_hits[0]
        return (utility_id, name_score, overlap, "hifld_overlap_and_name"), "hifld_overlap_and_name"
    if len(overlap_hits) > 1:
        return None, "ambiguous_hifld_overlap"
    exact_hits = [item for item in scored if item[3]]
    if len(exact_hits) == 1:
        utility_id, name_score, overlap, _exact = exact_hits[0]
        return (utility_id, name_score, overlap, "exact_name_state"), "exact_name_state"
    if len(exact_hits) > 1:
        return None, "ambiguous_exact_name"
    return None, "below_threshold"


def _decision(assertion_id: object, system_id: object, method: str, score: object, evidence: str, release: str) -> dict[str, object]:
    return {
        "assertion_id": assertion_id,
        "system_id": system_id,
        "method": method,
        "score": score,
        "evidence": evidence,
        "decided_by": RULE,
        "release": release,
    }


def _queue_row(record: object, system_id: object, name_score: object, overlap: object, reason: str) -> dict[str, object]:
    return {
        "assertion_id": record.assertion_id,
        "source_id": record.source_id,
        "candidate_system_id": system_id,
        "name_score": name_score,
        "overlap": overlap,
        "geom_state": record.geom_state,
        "name_norm": normalize_name(record.raw_name),
        "reason": reason,
    }


def _frames(decisions: list[dict[str, object]], queue: list[dict[str, object]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    decision_frame = pd.DataFrame(decisions, columns=list(DECISION_COLUMNS))
    queue_frame = pd.DataFrame(queue, columns=list(QUEUE_COLUMNS))
    return decision_frame, queue_frame
