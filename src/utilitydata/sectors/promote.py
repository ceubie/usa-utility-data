"""Reclassify a reviewed collection source that the freeze still marks draft.

Empty-geometry rows stay empty-geometry. An unreviewed source is not promoted.
Each promotion first copies the snapshot tables under promotion_backups/.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from utilitydata.bronze.snapshot import (
    _inspect_arcgis,
    _inspect_archived_layers,
    _inspect_csv_layers,
    _inspect_vector_layers,
)
from utilitydata.registry import Source
from utilitydata.sectors.zones import BUILDABLE

PROMOTION_BACKUPS = "promotion_backups"

LAYER_FIELDS = (
    "source_id",
    "relative_path",
    "archive_member",
    "layer",
    "feature_count",
    "geometry_count",
    "status",
)


def promote_reviewed_collection(
    home: Path,
    quarter: str,
    sources: list[Source],
    source_ids: set[str],
) -> list[str]:
    """Inspect named reviewed sources and replace a draft snapshot status."""
    snapshot = home / "snapshots" / quarter
    layer_path = snapshot / "layers.parquet"
    manifest_path = snapshot / "manifest.parquet"
    frozen = snapshot / "files"
    if not layer_path.is_file() or not manifest_path.is_file():
        raise ValueError("Snapshot tables are missing")
    layer_schema = pq.read_schema(layer_path)
    manifest_schema = pq.read_schema(manifest_path)
    layer_rows = pq.read_table(layer_path).to_pylist()
    manifest_rows = pq.read_table(manifest_path).to_pylist()
    selected = [source for source in sources if source.source_id in source_ids]
    if len(selected) != len(source_ids):
        found = {source.source_id for source in selected}
        missing = sorted(source_ids - found)
        raise ValueError(f"Sources to promote are not in the registry: {', '.join(missing)}")
    promoted: list[str] = []
    with tempfile.TemporaryDirectory(prefix="utilitydata-promote-") as staging_name:
        staging = Path(staging_name)
        for source in selected:
            if not source.reviewed or source.storage != "collection":
                raise ValueError(f"{source.source_id} cannot be promoted")
            existing = [row for row in layer_rows if row["source_id"] == source.source_id]
            if any(row["status"] == "no_geometry" for row in existing):
                raise ValueError(f"{source.source_id} has no geometry and stays unread")
            declared = {layer.layer for layer in source.layers}
            if existing and declared == {row["layer"] for row in existing} and all(row["status"] in BUILDABLE for row in existing):
                continue
            if source.driver == "arcgis":
                details, arc_status = _inspect_arcgis(source, frozen)
                inspected = [{
                    "source_id": source.source_id,
                    "relative_path": source.paths[0],
                    "archive_member": None,
                    "layer": source.layers[0].layer,
                    "feature_count": details["__feature_count"],
                    "geometry_count": details["__geometry_count"],
                    "status": arc_status,
                }]
            else:
                inspected = (
                    _inspect_csv_layers(source, frozen)
                    + _inspect_archived_layers(source, frozen, staging)
                    + _inspect_vector_layers(source, frozen)
                )
            if not inspected or {row["layer"] for row in inspected} != declared:
                raise ValueError(f"{source.source_id} inspection did not match its declared layers")
            if any(row["status"] not in BUILDABLE for row in inspected):
                raise ValueError(f"{source.source_id} inspection is not buildable")
            layer_rows = [row for row in layer_rows if row["source_id"] != source.source_id]
            layer_rows.extend(inspected)
            matched = False
            for row in manifest_rows:
                if row["source_id"] == source.source_id:
                    row["status"] = "collected"
                    matched = True
            if not matched:
                raise ValueError(f"Snapshot manifest row missing for {source.source_id}")
            promoted.append(source.source_id)
    if promoted:
        _back_up(snapshot, (layer_path, manifest_path), promoted)
        pq.write_table(pa.Table.from_pylist(layer_rows, schema=layer_schema), layer_path)
        pq.write_table(pa.Table.from_pylist(manifest_rows, schema=manifest_schema), manifest_path)
    return sorted(promoted)


def _back_up(snapshot: Path, tables: tuple[Path, ...], promoted: list[str]) -> Path:
    """Copy the snapshot tables as they were before this promotion. A backup is never overwritten."""
    backup = snapshot / PROMOTION_BACKUPS / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True)
    for table in tables:
        shutil.copy2(table, backup / table.name)
    (backup / "promoted.json").write_text(json.dumps(sorted(promoted), indent=2) + "\n", encoding="utf-8")
    return backup
