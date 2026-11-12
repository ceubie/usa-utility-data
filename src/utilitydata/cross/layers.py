"""Read reviewed facility and network layers. Draft and empty geometry stay closed."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import CRS

from utilitydata.core.spatial_io import reproject_geoms
from utilitydata.core.text import require_columns
from utilitydata.registry import Layer, Source
from utilitydata.sectors.tables import snapshot_path
from utilitydata.sectors.zones import BUILDABLE, UNBUILDABLE, require_buildable
from utilitydata.silver.boundaries import required_columns
from utilitydata.silver.geometry import DESTINATION, read_arcgis_features

# Logical attribute names that locate a row of a CSV table.
COORDINATE_FIELDS = ("longitude", "latitude")


@dataclass(frozen=True)
class LayerJob:
    """One reviewed layer whose snapshot status is buildable."""

    source: Source
    layer: Layer
    status: str


def select_layers(
    sources: list[Source],
    layers: pd.DataFrame,
    *,
    grain: str | None = None,
    attribute: str | None = None,
) -> tuple[list[LayerJob], list[dict[str, object]]]:
    """Return buildable layers and the layers left unread.

    ``grain`` and ``attribute`` select layers. Unreviewed, draft, and
    empty-geometry layers are returned in the skipped list and are not opened.
    """
    if grain is None and attribute is None:
        raise ValueError("Choose a layer grain or attribute")
    if grain is not None and grain not in {"facility", "network"}:
        raise ValueError(f"Unknown layer grain {grain}")
    require_columns(layers, ("source_id", "layer", "status"), "snapshot layers")
    jobs: list[LayerJob] = []
    skipped: list[dict[str, object]] = []
    for source in sources:
        selected = [
            layer
            for layer in source.layers
            if (grain is None or layer.grain == grain) and (attribute is None or attribute in layer.attribute_fields)
        ]
        if not selected:
            continue
        if not source.reviewed:
            for layer in selected:
                skipped.append(_skip(source, layer, "unreviewed", "unreviewed"))
            continue
        for layer in selected:
            status = _status(layers, source.source_id, layer.layer)
            if status in UNBUILDABLE:
                skipped.append(_skip(source, layer, status, status))
                continue
            if status not in BUILDABLE:
                raise ValueError(f"{source.source_id} {layer.layer} has status {status}")
            jobs.append(LayerJob(source, layer, status))
    return jobs, skipped


def read_layer(
    home: Path,
    quarter: str,
    job: LayerJob,
    layers: pd.DataFrame,
) -> tuple[pd.DataFrame, list | None]:
    """Read one selected layer. A draft or empty-geometry status raises before the file is used."""
    if not job.source.reviewed:
        raise ValueError(f"Refusing to read unreviewed source {job.source.source_id}")
    status = require_buildable(layers, job.source.source_id, job.layer.layer)
    if job.layer.layer.lower().endswith(".csv"):
        frame = _read_csv(home, quarter, job)
        geometries = csv_points(frame, job)
    elif job.source.driver == "arcgis":
        attributes, geometries, crs = read_arcgis_features(snapshot_path(home, quarter, job.source.paths[0]))
        frame = _frame_from_attributes(attributes, job)
        geometries = to_wgs84(geometries, crs, job)
    else:
        raise ValueError(f"No reader for {job.source.source_id} {job.layer.layer}")
    expected = _expected_count(layers, job)
    if len(frame) != expected or status != job.status:
        raise ValueError(
            f"{job.source.source_id} {job.layer.layer} read {len(frame)} rows "
            f"but the snapshot records {expected} with status {status}"
        )
    return frame, geometries


def to_wgs84(geometries: np.ndarray, crs: CRS | None, job: LayerJob) -> list:
    """Reproject geometries to EPSG:4326. Empty inputs stay empty."""
    if crs is None:
        raise ValueError(f"{job.source.source_id} {job.layer.layer} has no CRS")
    incoming = np.asarray(geometries, dtype=object)
    empty = shapely.from_wkt("POINT EMPTY")
    filled = np.array([empty if geometry is None else geometry for geometry in incoming], dtype=object)
    projected = shapely.make_valid(reproject_geoms(filled, crs, DESTINATION))
    output: list = []
    for geometry in projected:
        if geometry is None or shapely.is_empty(geometry):
            output.append(None)
        else:
            output.append(geometry)
    if len(output) != len(incoming):
        raise ValueError(f"{job.source.source_id} {job.layer.layer} lost geometries")
    return output


def csv_points(frame: pd.DataFrame, job: LayerJob) -> list | None:
    """Build points from the declared ``longitude`` and ``latitude`` columns.

    A table that declares neither column has no geometry. Declaring only one
    raises. A blank coordinate leaves that row without a point; text that is
    not a number, or a value outside the valid range, raises. Coordinates are
    read as decimal degrees and are not reprojected.
    """
    declared = [name for name in COORDINATE_FIELDS if name in job.layer.attribute_fields]
    if not declared:
        return None
    if len(declared) != len(COORDINATE_FIELDS):
        raise ValueError(f"{job.source.source_id} {job.layer.layer} declares only {declared[0]}")
    label = f"{job.source.source_id} {job.layer.layer}"
    values = {}
    for logical, limit in zip(COORDINATE_FIELDS, (180.0, 90.0), strict=True):
        column = job.layer.attribute_fields[logical]
        text = frame[column].astype("string").str.strip()
        number = pd.to_numeric(text, errors="coerce")
        if bool((text.notna() & text.ne("") & number.isna()).any()):
            raise ValueError(f"{label} {column} is not numeric")
        if bool((number.abs() > limit).any()):
            raise ValueError(f"{label} {column} is outside the valid range")
        values[logical] = number
    located = values["longitude"].notna() & values["latitude"].notna()
    points: list = [None] * len(frame)
    built = shapely.points(
        values["longitude"][located].to_numpy(dtype=float),
        values["latitude"][located].to_numpy(dtype=float),
    )
    for position, point in zip(np.flatnonzero(located.to_numpy()), built, strict=True):
        points[int(position)] = point
    return points


def _read_csv(home, quarter: str, job: LayerJob) -> pd.DataFrame:
    columns = sorted(required_columns(job.layer))
    archive = snapshot_path(home, quarter, job.source.paths[0])
    if archive.suffix.lower() == ".csv" and job.layer.layer == archive.name:
        header = pd.read_csv(archive, nrows=0, encoding="utf-8-sig").columns
        missing = [column for column in columns if column not in header]
        if missing:
            raise ValueError(f"{job.source.source_id} {job.layer.layer} is missing columns: {', '.join(missing)}")
        frame = pd.read_csv(archive, dtype="string", encoding="utf-8-sig", usecols=columns, keep_default_na=False)
    elif zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            if job.layer.layer not in bundle.namelist():
                raise ValueError(f"Missing archive member {job.layer.layer}")
            header = pd.read_csv(bundle.open(job.layer.layer), nrows=0, encoding="utf-8-sig").columns
            missing = [column for column in columns if column not in header]
            if missing:
                raise ValueError(f"{job.source.source_id} {job.layer.layer} is missing columns: {', '.join(missing)}")
            frame = pd.read_csv(
                bundle.open(job.layer.layer),
                dtype="string",
                encoding="utf-8-sig",
                usecols=columns,
                keep_default_na=False,
            )
    else:
        raise ValueError(f"No reader for {job.source.source_id} {job.layer.layer}")
    frame = frame.replace({"": pd.NA})
    return frame.loc[:, columns]


def _frame_from_attributes(attributes: list[dict], job: LayerJob) -> pd.DataFrame:
    columns = sorted(required_columns(job.layer))
    for record in attributes:
        missing = [column for column in columns if column not in record]
        if missing:
            raise ValueError(f"{job.source.source_id} {job.layer.layer} is missing columns: {', '.join(missing)}")
    if not attributes:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame.from_records(attributes, columns=columns)


def _expected_count(layers: pd.DataFrame, job: LayerJob) -> int:
    match = layers[(layers["source_id"] == job.source.source_id) & (layers["layer"] == job.layer.layer)]
    if len(match) != 1 or pd.isna(match.iloc[0]["feature_count"]):
        raise ValueError(f"Snapshot feature count missing for {job.source.source_id} {job.layer.layer}")
    return int(match.iloc[0]["feature_count"])


def _status(layers: pd.DataFrame, source_id: str, layer_name: str) -> str:
    match = layers[(layers["source_id"] == source_id) & (layers["layer"] == layer_name)]
    if len(match) != 1:
        raise ValueError(f"Snapshot layer row missing for {source_id} {layer_name}")
    return str(match.iloc[0]["status"])


def _skip(source: Source, layer: Layer, status: str, reason: str) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "layer": layer.layer,
        "status": status,
        "reason": reason,
        "state": layer.state_fixed,
        "facility_level": layer.facility_level,
        "grain": layer.grain,
        "out_of_scope": source.out_of_scope,
    }
