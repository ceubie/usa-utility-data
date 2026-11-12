"""Link a state or local wastewater zone to one CWNS id.

A zone links when its area overlaps one CWNS sewershed by the configured
fraction, or, failing that, when it contains exactly one CWNS treatment plant.
Two qualifying sewersheds, or two plants, stay on the review queue. The
overlap fraction is a starting value and is not calibrated.
"""

from __future__ import annotations

from collections.abc import Mapping

import geopandas as gpd
import pandas as pd
import shapely

from utilitydata.core.config import (
    WASTEWATER_SEWERSHED_OVERLAP,
    WASTEWATER_THRESHOLDS_CALIBRATED,
)
from utilitydata.core.geometry import covered_fraction
from utilitydata.core.schema import DECISION_COLUMNS


def split_cwns_ids(value: object) -> list[str]:
    """Split a sewershed id list. The saved separator is a semicolon."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError("CWNS id is missing")
    parts = [part.strip() for part in str(value).split(";")]
    if not parts or any(len(part) != 11 or not part.isdigit() for part in parts):
        raise ValueError(f"CWNS id is not an 11-digit identifier: {value}")
    return parts


def cwns_system_id(cwns_id: str) -> str:
    """Return the stable system id for one CWNS id."""
    if len(cwns_id) != 11 or not cwns_id.isdigit():
        raise ValueError(f"CWNS id is not an 11-digit identifier: {cwns_id}")
    return f"SYS_CWNS_{cwns_id}"


def federal_link(overlaps: Mapping[str, float], contained: set[str]) -> tuple[str | None, str]:
    """Choose one CWNS id, or a review reason when the zone does not qualify."""
    if WASTEWATER_THRESHOLDS_CALIBRATED:
        raise ValueError("Wastewater thresholds are marked calibrated without a recorded measurement")
    hits = sorted(cwns_id for cwns_id, fraction in overlaps.items() if fraction >= WASTEWATER_SEWERSHED_OVERLAP)
    if len(hits) == 1:
        return hits[0], "sewershed_overlap"
    if len(hits) > 1:
        return None, "ambiguous_sewershed_overlap"
    plants = sorted(contained)
    if len(plants) == 1:
        return plants[0], "single_contained_plant"
    if len(plants) > 1:
        return None, "multiple_contained_plants"
    return None, "no_federal_link"


def contained_plant_ids(zone: object, plant_tree: shapely.STRtree, plant_ids: list[str]) -> set[str]:
    """Return CWNS ids of treatment plants the zone contains."""
    if zone is None or shapely.is_empty(zone):
        return set()
    hits = plant_tree.query(zone, predicate="contains")
    return {plant_ids[int(index)] for index in hits}


def link_zones(
    zones: gpd.GeoDataFrame,
    sewersheds: gpd.GeoDataFrame,
    plants: gpd.GeoDataFrame,
    *,
    release: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Link every zone once. Unlinked zones are queued with a reason."""
    decisions: list[dict[str, object]] = []
    queue: list[dict[str, object]] = []
    if zones.empty:
        return _frames(decisions, queue)
    shed_ids = [split_cwns_ids(value) for value in sewersheds["cwns_id"]]
    shed_geometries = list(sewersheds.geometry)
    shed_tree = shapely.STRtree(shed_geometries)
    plant_ids = [str(value) for value in plants["cwns_id"]]
    plant_tree = shapely.STRtree(list(plants.geometry)) if not plants.empty else None
    for record in zones.itertuples(index=False):
        geometry = record.geometry
        if geometry is None or shapely.is_empty(geometry):
            decisions.append(_decision(record.assertion_id, None, "review_queue", None, "missing_geometry", release))
            queue.append(_queue(record, "missing_geometry", None, None))
            continue
        overlaps: dict[str, float] = {}
        for index in shed_tree.query(geometry, predicate="intersects"):
            fraction = covered_fraction(geometry, shed_geometries[int(index)])
            for cwns_id in shed_ids[int(index)]:
                overlaps[cwns_id] = max(overlaps.get(cwns_id, 0.0), fraction)
        contained = contained_plant_ids(geometry, plant_tree, plant_ids) if plant_tree is not None else set()
        cwns_id, reason = federal_link(overlaps, contained)
        if cwns_id is None:
            top = max(overlaps.items(), key=lambda item: item[1]) if overlaps else None
            decisions.append(_decision(record.assertion_id, None, "review_queue", None if top is None else top[1], reason, release))
            queue.append(_queue(record, reason, None if top is None else top[0], None if top is None else top[1]))
            continue
        system_id = cwns_system_id(cwns_id)
        fraction = overlaps.get(cwns_id)
        evidence = f"cwns_id={cwns_id};overlap={0.0 if fraction is None else fraction:.3f};plants={len(contained)}"
        score = WASTEWATER_SEWERSHED_OVERLAP if reason == "sewershed_overlap" else 100.0
        decisions.append(_decision(record.assertion_id, system_id, reason, score, evidence, release))
    if len(decisions) != len(zones):
        raise ValueError("Wastewater link decisions do not cover every zone")
    return _frames(decisions, queue)


def _decision(assertion_id: object, system_id: object, method: str, score: object, evidence: str, release: str) -> dict[str, object]:
    return {
        "assertion_id": assertion_id,
        "system_id": system_id,
        "method": method,
        "score": score,
        "evidence": evidence,
        "decided_by": "rule",
        "release": release,
    }


def _queue(record: object, reason: str, cwns_id: object, overlap: object) -> dict[str, object]:
    return {
        "assertion_id": record.assertion_id,
        "source_id": record.source_id,
        "geom_state": record.geom_state,
        "name_norm": record.name_norm,
        "reason": reason,
        "candidate_cwns_id": cwns_id,
        "overlap": overlap,
    }


def _frames(decisions: list[dict[str, object]], queue: list[dict[str, object]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        pd.DataFrame(decisions, columns=list(DECISION_COLUMNS)),
        pd.DataFrame(queue, columns=["assertion_id", "source_id", "geom_state", "name_norm", "reason", "candidate_cwns_id", "overlap"]),
    )
