"""Choose reviewed state and local service areas. Draft and empty geometry stay unread."""

from __future__ import annotations

import pandas as pd

from utilitydata.registry import Layer, Source

BUILDABLE = frozenset({"collected", "partial_geometry", "nonspatial"})
UNBUILDABLE = frozenset({"draft", "no_geometry"})
LOCAL_AUTHORITIES = frozenset({"state_regulator", "utility_direct"})


def select_local_zones(
    sources: list[Source],
    layers: pd.DataFrame,
    *,
    sector: str,
    authorities: frozenset[str] = LOCAL_AUTHORITIES,
) -> tuple[list[tuple[Source, Layer, str]], list[str], list[str]]:
    """Return service areas with an accepted authority, drafts left unread, and unbuildable rows left unread.

    By default only state and utility layers are zones, and a reviewed federal
    compilation is not. A sector with no federal boundary file passes the
    authorities it accepts. A draft source is not opened. A snapshot status of
    draft or no_geometry is not opened.
    """
    jobs: list[tuple[Source, Layer, str]] = []
    drafts: list[str] = []
    skipped: list[str] = []
    for source in sources:
        candidates = [
            layer
            for layer in source.layers
            if layer.sector == sector and layer.grain == "service_area"
        ]
        if not candidates:
            continue
        if not source.reviewed:
            drafts.append(source.source_id)
            continue
        local = [
            layer
            for layer in candidates
            if isinstance(layer.authority, str) and layer.authority in authorities
        ]
        for layer in local:
            status = _status(layers, source.source_id, layer.layer)
            if status in UNBUILDABLE:
                skipped.append(source.source_id)
                continue
            if status not in BUILDABLE:
                raise ValueError(f"{source.source_id} {layer.layer} has status {status}")
            jobs.append((source, layer, status))
    return jobs, sorted(set(drafts)), sorted(set(skipped))


def require_buildable(layers: pd.DataFrame, source_id: str, layer_name: str) -> str:
    """Return a buildable snapshot status. Draft and empty geometry raise."""
    status = _status(layers, source_id, layer_name)
    if status in UNBUILDABLE or status not in BUILDABLE:
        raise ValueError(f"{source_id} {layer_name} has status {status}")
    return status


def _status(layers: pd.DataFrame, source_id: str, layer_name: str) -> str:
    match = layers[(layers["source_id"] == source_id) & (layers["layer"] == layer_name)]
    if len(match) != 1:
        raise ValueError(f"Snapshot layer row missing for {source_id} {layer_name}")
    return str(match.iloc[0]["status"])
