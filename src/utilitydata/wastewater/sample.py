"""Review sample of wastewater zones that did not receive a CWNS id."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from utilitydata.core.config import WASTEWATER_SAMPLE_SEED, WASTEWATER_SAMPLE_SIZE
from utilitydata.core.geometry import covered_fraction
from utilitydata.core.text import normalize_name
from utilitydata.wastewater.match import (
    contained_plant_ids,
    federal_link,
    split_cwns_ids,
)


def draw_unlinked(queue: pd.DataFrame) -> pd.DataFrame:
    """Draw a stable sample of unlinked zones. This is not a verification set."""
    if queue.empty:
        return queue
    ordered = queue.sort_values("assertion_id")
    count = min(WASTEWATER_SAMPLE_SIZE, len(ordered))
    picker = np.random.default_rng(WASTEWATER_SAMPLE_SEED)
    chosen = picker.choice(ordered["assertion_id"].astype(str).to_numpy(), size=count, replace=False)
    return ordered.loc[ordered["assertion_id"].astype(str).isin(set(chosen))].reset_index(drop=True)


def audit_unlinked_sample(
    sample: pd.DataFrame,
    zones: gpd.GeoDataFrame,
    sewersheds: gpd.GeoDataFrame,
    plants: gpd.GeoDataFrame,
    systems: pd.DataFrame,
) -> pd.DataFrame:
    """Recompute the federal rule for the sample.

    A sampled zone that meets the overlap or single-plant rule is a defect.
    A same-state name match is recorded for review and does not by itself link.
    """
    if sample.empty:
        return pd.DataFrame(columns=["assertion_id", "source_id", "geom_state", "name_norm", "independent_cwns_id", "independent_reason", "name_match_cwns_id", "defect"])
    shed_ids = [split_cwns_ids(value) for value in sewersheds["cwns_id"]]
    shed_geometries = list(sewersheds.geometry)
    shed_tree = shapely.STRtree(shed_geometries)
    plant_ids = [str(value) for value in plants["cwns_id"]]
    plant_tree = shapely.STRtree(list(plants.geometry)) if not plants.empty else None
    names = systems.loc[:, ["system_id", "name", "primary_state"]].copy()
    names["name_norm"] = names["name"].map(normalize_name)
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    zone_index = zones.set_index(zones["assertion_id"].astype(str))
    for record in sample.itertuples(index=False):
        assertion_id = str(record.assertion_id)
        zone = zone_index.loc[assertion_id]
        geometry = zone.geometry
        overlaps: dict[str, float] = {}
        for index in shed_tree.query(geometry, predicate="intersects"):
            fraction = covered_fraction(geometry, shed_geometries[int(index)])
            for cwns_id in shed_ids[int(index)]:
                overlaps[cwns_id] = max(overlaps.get(cwns_id, 0.0), fraction)
        contained = contained_plant_ids(geometry, plant_tree, plant_ids) if plant_tree is not None else set()
        cwns_id, reason = federal_link(overlaps, contained)
        state = zone.geom_state if zone.geom_state is not None and not (isinstance(zone.geom_state, float) and pd.isna(zone.geom_state)) else zone.declared_state
        same = names.loc[names["primary_state"].eq(state) & names["name_norm"].eq(zone.name_norm), "system_id"]
        name_match = str(same.iloc[0]) if len(same) == 1 else None
        defect = cwns_id is not None
        if defect:
            defects.append(assertion_id)
        rows.append({
            "assertion_id": assertion_id,
            "source_id": record.source_id,
            "geom_state": state,
            "name_norm": zone.name_norm,
            "independent_cwns_id": cwns_id,
            "independent_reason": reason,
            "name_match_cwns_id": name_match,
            "defect": defect,
        })
    if defects:
        raise ValueError("Unlinked wastewater zones are in CWNS: " + ", ".join(defects[:10]))
    return pd.DataFrame(rows)
