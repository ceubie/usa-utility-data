"""Drinking-water Silver assertions from the frozen snapshot.

Reviewed water layers are the only inputs. Draft sources are listed and not
read. Every feature becomes an assertion or a reject, and both sides are counted.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Never, NoReturn

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely
from pyproj import CRS

from utilitydata.bronze.archive import materialize_archive_member
from utilitydata.core.config import DEFAULT_QUARTER
from utilitydata.registry import FieldMap, Layer, Source, load_registry
from utilitydata.sectors.promote import promote_reviewed_collection
from utilitydata.sectors.tables import snapshot_path
from utilitydata.silver.geometry import (
    DESTINATION,
    containing_state_codes,
    hilbert_distances,
    prepare_geometries,
    read_arcgis_features,
    read_vector_features,
    representative_longitude_latitude,
    reproject_geoms,
)
from utilitydata.silver.ids import PwsidResult, normalize_pwsid
from utilitydata.silver.tables import SYSTEMS_MEMBER, TABLE_NAMES, load_sdwa_tables

BUILDABLE = frozenset({"collected", "partial_geometry", "nonspatial"})
# Files that hold exactly one layer, so the layer is not addressed by name.
SINGLE_LAYER_SUFFIXES = frozenset({".geojson", ".json", ".shp"})
QUARTER = re.compile(r"^[0-9]{4}-Q[1-4]$")
_YEAR = re.compile(r"^\d{4}$")
_QUARTER_TEXT = re.compile(r"^(\d{4})Q([1-4])$")
_MONTH_DAY_YEAR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_YEAR_MONTH_DAY = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DIGITS = re.compile(r"^\d{10,13}$")
NullPolicy = Literal["reject", "unknown", "review_required"]

ASSERTION_COLUMNS = [
    "assertion_id",
    "source_id",
    "source_layer",
    "source_feature_id",
    "sector",
    "zone_role",
    "authority",
    "raw_name",
    "name_norm",
    "pwsid",
    "declared_state",
    "geom_state",
    "source_vintage_date",
    "licence",
    "area_km2",
    "geometry_hash",
    "grain",
    "boundary_representation",
    "pwsid_raw",
    "pwsid_exception",
    "needs_review",
    "review_reason",
    "state_mismatch",
    "footprint_verified",
    "activity_status",
]
ATTRIBUTE_COLUMNS = [
    "record_id",
    "source_id",
    "source_layer",
    "source_feature_id",
    "sector",
    "grain",
    "raw_name",
    "name_norm",
    "pwsid",
    "pwsid_raw",
    "pwsid_exception",
    "declared_state",
    "source_vintage_date",
    "licence",
    "needs_review",
    "review_reason",
    "activity_status",
]
REJECT_COLUMNS = ["source_id", "source_layer", "source_feature_id", "reason", "sector", "raw_name", "pwsid_raw"]
CANDIDATE_COLUMNS = ["assertion_id", "source_id", "source_layer", "source_feature_id", "source_field", "ordinal", "candidate", "federal_id"]


@dataclass(frozen=True)
class LayerJob:
    source: Source
    layer: Layer
    relative_path: str
    feature_count: int
    status: str


@dataclass
class LayerRows:
    assertions: list[dict]
    geometries: list[object]
    rejects: list[dict]
    candidates: list[dict]
    attributes: list[dict]


def build_water_silver(home: Path, registry_dir: Path, *, quarter: str = DEFAULT_QUARTER) -> dict[str, object]:
    """Build drinking-water Silver for one frozen snapshot quarter."""
    if not QUARTER.fullmatch(quarter):
        raise ValueError("Water quarter must be formatted YYYY-QN")
    snapshot = home / "snapshots" / quarter
    output = home / "silver" / quarter
    sources = load_registry(registry_dir, require_reviewed=False)
    promoted = promote_reviewed_collection(home, quarter, sources, reviewed_water_collection_ids(sources))
    layer_table = pd.read_parquet(snapshot / "layers.parquet")
    jobs, drafts = select_water_jobs(sources, layer_table)
    _require_layer_agreement(sources, layer_table)
    known_states = _known_states(output / "ref_state.parquet")
    output.mkdir(parents=True, exist_ok=True)

    written: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    layer_reports: list[dict[str, object]] = []
    table_counts, sdwis_counts = _build_csv_tables(home, quarter, output, jobs, written, rejected, layer_reports)
    state_geometries, state_codes = _load_state_regions(home, sources, output / "ref_state.parquet")

    assertion_frames: list[pd.DataFrame] = []
    assertion_geometries: list[np.ndarray] = []
    attribute_frames: list[pd.DataFrame] = []
    reject_frames: list[pd.DataFrame] = []
    candidate_frames: list[pd.DataFrame] = []
    grouped: dict[tuple[str, str], list[LayerJob]] = {}
    for job in jobs:
        if job.layer.layer.lower().endswith(".csv"):
            continue
        if job.layer.archive_member:
            grouped.setdefault((job.relative_path, job.layer.archive_member), []).append(job)
            continue
        _consume_job(
            job,
            _read_unarchived_job(home, quarter, job),
            known_states,
            sdwis_counts,
            state_geometries,
            state_codes,
            written,
            rejected,
            layer_reports,
            assertion_frames,
            assertion_geometries,
            attribute_frames,
            reject_frames,
            candidate_frames,
        )
    for (relative, member), members in grouped.items():
        with _extracted_member(snapshot_path(home, quarter, relative), member) as extracted:
            for job in members:
                _consume_job(
                    job,
                    _read_vector_job(extracted, job),
                    known_states,
                    sdwis_counts,
                    state_geometries,
                    state_codes,
                    written,
                    rejected,
                    layer_reports,
                    assertion_frames,
                    assertion_geometries,
                    attribute_frames,
                    reject_frames,
                    candidate_frames,
                )

    assertions = _concat(assertion_frames, ASSERTION_COLUMNS)
    geometries = np.concatenate(assertion_geometries) if assertion_geometries else np.array([], dtype=object)
    if len(assertions) != len(geometries):
        raise ValueError("Assertion rows and geometries diverged")
    boundary_path = output / "boundary_assertion.parquet"
    _write_boundaries(assertions, geometries, boundary_path)
    attributes = _concat(attribute_frames, ATTRIBUTE_COLUMNS)
    rejects = _concat(reject_frames, REJECT_COLUMNS)
    candidates = _concat(candidate_frames, CANDIDATE_COLUMNS)
    if not attributes.empty:
        attributes.to_parquet(output / "water_attribute.parquet", index=False)
    rejects.to_parquet(output / "rejects.parquet", index=False)
    candidates.to_parquet(output / "pwsid_candidate.parquet", index=False)
    _reconcile(jobs, written, rejected)
    report = _acceptance_report(
        output,
        boundary_path,
        assertions,
        rejects,
        candidates,
        table_counts,
        layer_reports,
        drafts,
        quarter,
    )
    report["promoted_sources"] = promoted
    (output / "water_silver_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def reviewed_water_collection_ids(sources: list[Source]) -> set[str]:
    """Return reviewed collection sources that declare a spatial or attribute water layer.

    A source reviewed after the snapshot was frozen still carries the draft
    status in the snapshot tables. Its saved files are inspected again before
    the build reads them, in the same way as the other sector builds.
    """
    return {
        source.source_id
        for source in sources
        if source.reviewed
        and source.storage == "collection"
        and any(layer.sector == "water" for layer in source.layers)
    }


def select_water_jobs(sources: list[Source], layers: pd.DataFrame) -> tuple[list[LayerJob], list[str]]:
    """Return reviewed water work and the draft water sources left unbuilt."""
    jobs: list[LayerJob] = []
    drafts: list[str] = []
    for source in sources:
        water_layers = [layer for layer in source.layers if layer.sector == "water"]
        if not water_layers:
            continue
        if not source.reviewed:
            drafts.append(source.source_id)
            continue
        if len(source.paths) != 1:
            raise ValueError(f"{source.source_id} needs one snapshot path")
        for layer in water_layers:
            match = layers[(layers["source_id"] == source.source_id) & (layers["layer"] == layer.layer)]
            if len(match) != 1:
                raise ValueError(f"Snapshot layer row missing for {source.source_id} {layer.layer}")
            status = str(match.iloc[0]["status"])
            if status not in BUILDABLE:
                raise ValueError(f"{source.source_id} {layer.layer} has status {status}")
            jobs.append(LayerJob(source, layer, source.paths[0], int(match.iloc[0]["feature_count"]), status))
    return jobs, sorted(drafts)


def build_layer_rows(
    *,
    source_id: str,
    licence: str | None,
    layer: Layer,
    attributes: list[dict],
    geometries: np.ndarray | None,
    source_crs: CRS | None,
    sdwis_counts: Mapping[str, int],
    known_states: set[str],
    state_geometries: np.ndarray | None = None,
    state_codes: np.ndarray | None = None,
    spatial: bool,
) -> LayerRows:
    """Turn one layer's features into assertions or rejects without dropping a row."""
    columns = required_columns(layer)
    if layer.state_fixed and layer.state_fixed not in known_states:
        raise ValueError(f"Fixed state {layer.state_fixed} is not in ref_state")
    role_lookup = {tuple(case.values): case.role for case in layer.role_matrix.cases} if layer.role_matrix else {}
    prepared_geometries = hashes = areas = keep = None
    if spatial:
        if geometries is None or source_crs is None:
            raise ValueError(f"{source_id} {layer.layer} is spatial but has no geometry input")
        if len(geometries) != len(attributes):
            raise ValueError(f"{source_id} {layer.layer} geometry count does not match its features")
        prepared_geometries, hashes, areas, keep = prepare_geometries(geometries, source_crs)
    elif geometries is not None and any(geometry is not None and not shapely.is_empty(geometry) for geometry in geometries):
        raise ValueError(f"{source_id} {layer.layer} is nonspatial but contains geometry")

    assertions: list[dict] = []
    kept_geometries: list[object] = []
    mailings: list[str | None] = []
    rejects: list[dict] = []
    candidates: list[dict] = []
    attribute_rows: list[dict] = []
    seen: set[str] = set()
    pwsid_field = layer.id_fields.get("pwsid")
    for index, record in enumerate(attributes):
        missing = sorted(name for name in columns if name not in record)
        if missing:
            raise ValueError(f"Missing attribute in {source_id}: {', '.join(missing)}")
        feature_id = _feature_id(record, layer, index)
        if feature_id in seen:
            raise ValueError(f"Duplicate feature id {feature_id} in {source_id} {layer.layer}")
        seen.add(feature_id)
        interpreted = _interpret(record, layer, role_lookup, known_states, sdwis_counts)
        if spatial and keep is not None and not bool(keep[index]):
            rejects.append(_reject(source_id, layer, feature_id, "empty_geometry", interpreted))
            continue
        if interpreted["reject_reason"]:
            rejects.append(_reject(source_id, layer, feature_id, str(interpreted["reject_reason"]), interpreted))
            continue
        identifier = f"{source_id}|{layer.layer}|{feature_id}"
        if spatial:
            assertions.append(_assertion_row(identifier, source_id, licence, layer, feature_id, interpreted, hashes[index], areas[index]))
            kept_geometries.append(prepared_geometries[index])
            mailings.append(_mailing_state(record, layer, known_states))
        else:
            attribute_rows.append(_attribute_row(identifier, source_id, licence, layer, feature_id, interpreted))
        _append_candidates(candidates, identifier, source_id, layer.layer, feature_id, pwsid_field, interpreted)
    if spatial and state_geometries is not None and state_codes is not None and kept_geometries:
        codes = containing_state_codes(np.array(kept_geometries, dtype=object), state_geometries, state_codes)
        for row, code, mailing in zip(assertions, codes, mailings, strict=True):
            _apply_geom_state(row, None if code is None else str(code), layer, mailing_state=mailing)
    if len(assertions) + len(attribute_rows) + len(rejects) != len(attributes):
        raise ValueError(f"Row accounting failed for {source_id} {layer.layer}")
    return LayerRows(assertions, kept_geometries, rejects, candidates, attribute_rows)


def required_columns(layer: Layer) -> set[str]:
    """Return the exact source column names declared for a layer."""
    names = set(layer.id_fields.values())
    names.update(layer.attribute_fields.values())
    for name in (layer.name_field, layer.state_field, layer.vintage_field, layer.mailing_state_field):
        if name:
            names.add(name)
    for mapping in (layer.role_field, layer.status_field, layer.wholesaler_field):
        if mapping is not None:
            names.add(mapping.field)
    if isinstance(layer.authority, FieldMap):
        names.add(layer.authority.field)
    if isinstance(layer.boundary_representation, FieldMap):
        names.add(layer.boundary_representation.field)
    if layer.role_matrix is not None:
        names.update(layer.role_matrix.fields)
    return names


def parse_vintage(value: object) -> date | None:
    """Parse a registry vintage without treating zero, blank, or null as a guessed date."""
    if _is_null(value) or isinstance(value, bool):
        if isinstance(value, bool):
            raise ValueError(f"Unrecognized vintage {value!r}")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return _numeric_vintage(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if _DIGITS.fullmatch(text):
            return _numeric_vintage(int(text))
        if _YEAR.fullmatch(text):
            return date(int(text), 1, 1)
        quarter = _QUARTER_TEXT.fullmatch(text)
        if quarter:
            return date(int(quarter.group(1)), (int(quarter.group(2)) - 1) * 3 + 1, 1)
        month_day = _MONTH_DAY_YEAR.fullmatch(text)
        if month_day:
            return _safe_date(int(month_day.group(3)), int(month_day.group(1)), int(month_day.group(2)), value)
        year_month = _YEAR_MONTH_DAY.fullmatch(text)
        if year_month:
            return _safe_date(int(year_month.group(1)), int(year_month.group(2)), int(year_month.group(3)), value)
        iso = _ISO_DATE.match(text)
        if iso:
            return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), value)
    raise ValueError(f"Unrecognized vintage {value!r}")


def geoparquet_metadata_present(path: Path) -> bool:
    """Return whether GeoPandas recognizes the file as GeoParquet with geometry metadata."""
    schema = pq.read_schema(path)
    raw = schema.metadata.get(b"geo") if schema.metadata else None
    if not raw:
        return False
    metadata = json.loads(raw)
    if "geometry" not in (metadata.get("columns") or {}):
        return False
    frame = gpd.read_parquet(path)
    return frame.crs is not None and frame.geometry.name == "geometry" and not frame.geometry.isna().all()


def _build_csv_tables(
    home: Path,
    quarter: str,
    output: Path,
    jobs: list[LayerJob],
    written: Counter[str],
    rejected: Counter[str],
    layer_reports: list[dict[str, object]],
) -> tuple[dict[str, int], Counter[str]]:
    grouped: dict[str, dict[str, set[str]]] = {}
    pwsid_column = None
    csv_jobs = [job for job in jobs if job.layer.layer.lower().endswith(".csv")]
    for job in csv_jobs:
        grouped.setdefault(job.relative_path, {})[job.layer.layer] = required_columns(job.layer)
        if job.layer.layer == SYSTEMS_MEMBER and "pwsid" in job.layer.id_fields:
            column = job.layer.id_fields["pwsid"]
            if pwsid_column not in {None, column}:
                raise ValueError("SDWA PWSID columns disagree")
            pwsid_column = column
    if csv_jobs and not pwsid_column:
        raise ValueError("Reviewed SDWA systems table does not name a PWSID column")
    counts: dict[str, int] = {}
    identifiers: Counter[str] = Counter()
    for relative, members in grouped.items():
        part, found = load_sdwa_tables(snapshot_path(home, quarter, relative), members, output, pwsid_column=str(pwsid_column))
        counts.update(part)
        identifiers.update(found)
    for job in csv_jobs:
        table_name = TABLE_NAMES[job.layer.layer]
        count = counts[table_name]
        if count != job.feature_count:
            raise ValueError(f"{job.source.source_id} {job.layer.layer}: wrote {count}, snapshot has {job.feature_count}")
        written[job.source.source_id] += count
        layer_reports.append(_layer_report(job, count, 0))
    return counts, identifiers


def _consume_job(
    job: LayerJob,
    loaded: tuple[list[dict], np.ndarray | None, CRS | None],
    known_states: set[str],
    sdwis_counts: Mapping[str, int],
    state_geometries: np.ndarray,
    state_codes: np.ndarray,
    written: Counter[str],
    rejected: Counter[str],
    layer_reports: list[dict[str, object]],
    assertion_frames: list[pd.DataFrame],
    assertion_geometries: list[np.ndarray],
    attribute_frames: list[pd.DataFrame],
    reject_frames: list[pd.DataFrame],
    candidate_frames: list[pd.DataFrame],
) -> None:
    attributes, geometries, source_crs = loaded
    if len(attributes) != job.feature_count:
        raise ValueError(f"{job.source.source_id} {job.layer.layer}: read {len(attributes)} features, snapshot has {job.feature_count}")
    spatial = job.status != "nonspatial"
    print(f"building {job.source.source_id} {job.layer.layer}: {job.feature_count} features", flush=True)
    rows = build_layer_rows(
        source_id=job.source.source_id,
        licence=job.source.licence,
        layer=job.layer,
        attributes=attributes,
        geometries=geometries,
        source_crs=source_crs,
        sdwis_counts=sdwis_counts,
        known_states=known_states,
        state_geometries=state_geometries if spatial else None,
        state_codes=state_codes if spatial else None,
        spatial=spatial,
    )
    produced = len(rows.assertions) + len(rows.attributes)
    written[job.source.source_id] += produced
    rejected[job.source.source_id] += len(rows.rejects)
    layer_reports.append(_layer_report(job, produced, len(rows.rejects)))
    if rows.assertions:
        assertion_frames.append(pd.DataFrame(rows.assertions, columns=ASSERTION_COLUMNS))
        assertion_geometries.append(np.array(rows.geometries, dtype=object))
    if rows.attributes:
        attribute_frames.append(pd.DataFrame(rows.attributes, columns=ATTRIBUTE_COLUMNS))
    if rows.rejects:
        reject_frames.append(pd.DataFrame(rows.rejects, columns=REJECT_COLUMNS))
    if rows.candidates:
        candidate_frames.append(pd.DataFrame(rows.candidates, columns=CANDIDATE_COLUMNS))


def _read_unarchived_job(home: Path, quarter: str, job: LayerJob) -> tuple[list[dict], np.ndarray, CRS]:
    """Read saved ArcGIS pages or one standalone vector file."""
    path = snapshot_path(home, quarter, job.relative_path)
    if job.source.driver == "arcgis":
        return read_arcgis_features(path)
    if path.suffix.lower() in SINGLE_LAYER_SUFFIXES | {".gpkg"}:
        return _read_vector_job(path, job)
    raise ValueError(f"No reader for {job.source.source_id} {job.layer.layer}")


def _read_vector_job(path: Path, job: LayerJob) -> tuple[list[dict], np.ndarray, CRS]:
    layer_name = None if path.suffix.lower() in SINGLE_LAYER_SUFFIXES else job.layer.layer
    frame, geometries, crs = read_vector_features(str(path), layer_name, feature_id_field=job.layer.id_fields.get("feature_id"))
    missing = sorted(required_columns(job.layer) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing columns in {job.source.source_id}: {', '.join(missing)}")
    return frame.to_dict("records"), geometries, crs


def _interpret(
    record: dict,
    layer: Layer,
    role_lookup: dict[tuple, str],
    known_states: set[str],
    sdwis_counts: Mapping[str, int],
) -> dict[str, object]:
    reject_reason, zone_role = _zone_role(record, layer, role_lookup)
    authority_reason, authority = _authority(record, layer)
    if reject_reason is None:
        reject_reason = authority_reason
    rep_reason, representation = _representation(record, layer)
    if reject_reason is None:
        reject_reason = rep_reason
    status_reason, activity = _activity(record, layer)
    if reject_reason is None:
        reject_reason = status_reason
    raw_name = _raw_name(record.get(layer.name_field)) if layer.name_field else None
    reviews: list[str] = []
    if layer.on_missing_name == "preserve_and_review" and raw_name is None:
        reviews.append("missing_name")
    if zone_role == "review_required":
        reviews.append("registry_review_role")
    if activity == "unknown":
        reviews.append("unknown_status")
    elif activity == "inactive":
        reviews.append("inactive_system")
    declared = _declared_state(record, layer, known_states, reviews)
    identifier = _pwsid(record, layer, declared, sdwis_counts, reviews)
    vintage = parse_vintage(layer.vintage_fixed if layer.vintage_fixed else record[layer.vintage_field] if layer.vintage_field else None)
    return {
        "reject_reason": reject_reason,
        "zone_role": zone_role,
        "authority": authority,
        "boundary_representation": representation,
        "raw_name": raw_name,
        "name_norm": _name_norm(raw_name),
        "declared_state": declared,
        "vintage": vintage,
        "activity_status": activity,
        "reviews": reviews,
        "pwsid": identifier.federal_id,
        "pwsid_raw": identifier.raw,
        "pwsid_exception": identifier.exception,
        "candidates": identifier.candidates,
        "candidate_federal_id": identifier.federal_id if len(identifier.candidates) == 1 else None,
    }


def _zone_role(record: dict, layer: Layer, role_lookup: dict[tuple, str]) -> tuple[str | None, str | None]:
    if layer.role:
        return None, layer.role
    if layer.role_field is not None:
        if layer.role_field.on_null == "unknown":
            raise ValueError("Null role values cannot be marked unknown")
        reason, value = _coded(record, layer.role_field, "null_role")
        return reason, value
    if layer.role_matrix is not None:
        key = tuple(None if _is_null(record[field]) else _code(record[field]) for field in layer.role_matrix.fields)
        try:
            return None, role_lookup[key]
        except KeyError as exc:
            raise ValueError(f"Unmapped role combination in {layer.layer}: {key!r}") from exc
    return None, None


def _authority(record: dict, layer: Layer) -> tuple[str | None, str | None]:
    authority = layer.authority
    if authority is None:
        return None, None
    if isinstance(authority, str):
        return None, authority
    return _coded(record, authority, "null_authority")


def _representation(record: dict, layer: Layer) -> tuple[str | None, str | None]:
    rep = layer.boundary_representation
    if isinstance(rep, str):
        return None, rep
    return _coded(record, rep, "null_boundary_representation")


def _activity(record: dict, layer: Layer) -> tuple[str | None, str | None]:
    if layer.status_field is None:
        return None, None
    return _coded(record, layer.status_field, "null_status")


def _coded(record: dict, mapping: FieldMap, reject_reason: str) -> tuple[str | None, str | None]:
    value = record[mapping.field]
    if _is_null(value):
        return _missing_coded(mapping.on_null, reject_reason=reject_reason)
    text = _code(value)
    try:
        return None, mapping.values[text]
    except KeyError as exc:
        raise ValueError(f"Unmapped value {value!r} in {mapping.field}") from exc


def _missing_coded(policy: NullPolicy, *, reject_reason: str) -> tuple[str | None, str | None]:
    if policy == "reject":
        return reject_reason, None
    if policy == "review_required":
        return None, "review_required"
    if policy == "unknown":
        return None, "unknown"
    _assert_never(policy)


def _declared_state(record: dict, layer: Layer, known_states: set[str], reviews: list[str]) -> str | None:
    if layer.state_fixed:
        return layer.state_fixed
    if layer.state_from_geometry:
        return None
    if not layer.state_field:
        return None
    value = record[layer.state_field]
    if _is_null(value):
        reviews.append("missing_state")
        return None
    text = value.strip() if isinstance(value, str) else _code(value).strip()
    if text in known_states:
        return text
    reviews.append("unrecognized_state")
    return None


def _pwsid(record: dict, layer: Layer, declared_state: str | None, sdwis_counts: Mapping[str, int], reviews: list[str]) -> PwsidResult:
    if "pwsid" not in layer.id_fields:
        return PwsidResult(None, None, False, False, None, ())
    result = normalize_pwsid(
        record[layer.id_fields["pwsid"]],
        state_prefix_7=layer.pwsid_rule == "state_prefix_7",
        state=declared_state,
        sdwis_counts=sdwis_counts,
    )
    if result.review and result.reason:
        reviews.append(result.reason)
    return result


def _assertion_row(identifier: str, source_id: str, licence: str | None, layer: Layer, feature_id: str, interpreted: dict, geometry_hash: object, area: object) -> dict:
    reviews = list(interpreted["reviews"])
    return {
        "assertion_id": identifier,
        "source_id": source_id,
        "source_layer": layer.layer,
        "source_feature_id": feature_id,
        "sector": layer.sector,
        "zone_role": interpreted["zone_role"],
        "authority": interpreted["authority"],
        "raw_name": interpreted["raw_name"],
        "name_norm": interpreted["name_norm"],
        "pwsid": interpreted["pwsid"],
        "declared_state": interpreted["declared_state"],
        "geom_state": None,
        "source_vintage_date": interpreted["vintage"],
        "licence": licence,
        "area_km2": area,
        "geometry_hash": geometry_hash,
        "grain": layer.grain,
        "boundary_representation": interpreted["boundary_representation"],
        "pwsid_raw": interpreted["pwsid_raw"],
        "pwsid_exception": interpreted["pwsid_exception"],
        "needs_review": bool(reviews),
        "review_reason": "|".join(reviews) or None,
        "state_mismatch": False,
        "footprint_verified": False if interpreted["zone_role"] == "onsite_noncommunity" else None,
        "activity_status": interpreted["activity_status"],
    }


def _attribute_row(identifier: str, source_id: str, licence: str | None, layer: Layer, feature_id: str, interpreted: dict) -> dict:
    reviews = list(interpreted["reviews"])
    return {
        "record_id": identifier,
        "source_id": source_id,
        "source_layer": layer.layer,
        "source_feature_id": feature_id,
        "sector": layer.sector,
        "grain": layer.grain,
        "raw_name": interpreted["raw_name"],
        "name_norm": interpreted["name_norm"],
        "pwsid": interpreted["pwsid"],
        "pwsid_raw": interpreted["pwsid_raw"],
        "pwsid_exception": interpreted["pwsid_exception"],
        "declared_state": interpreted["declared_state"],
        "source_vintage_date": interpreted["vintage"],
        "licence": licence,
        "needs_review": bool(reviews),
        "review_reason": "|".join(reviews) or None,
        "activity_status": interpreted["activity_status"],
    }


def _reject(source_id: str, layer: Layer, feature_id: str, reason: str, interpreted: dict) -> dict:
    return {
        "source_id": source_id,
        "source_layer": layer.layer,
        "source_feature_id": feature_id,
        "reason": reason,
        "sector": layer.sector,
        "raw_name": interpreted["raw_name"],
        "pwsid_raw": interpreted["pwsid_raw"],
    }


def _append_candidates(candidates: list[dict], identifier: str, source_id: str, layer_name: str, feature_id: str, field: str | None, interpreted: dict) -> None:
    for ordinal, candidate in enumerate(interpreted["candidates"]):
        candidates.append({
            "assertion_id": identifier,
            "source_id": source_id,
            "source_layer": layer_name,
            "source_feature_id": feature_id,
            "source_field": field,
            "ordinal": ordinal,
            "candidate": candidate,
            "federal_id": interpreted["candidate_federal_id"],
        })


def mailing_state_mismatch(geom_state: str | None, mailing_state: str | None) -> bool:
    """Return whether a mailing state and the geometry state are both known and different.

    A missing geometry state is unresolved rather than a mismatch. A mailing value
    that is not a state code is not compared.
    """
    return mailing_state is not None and geom_state is not None and mailing_state != geom_state


def _mailing_state(record: dict, layer: Layer, known_states: set[str]) -> str | None:
    field = layer.mailing_state_field
    if not field:
        return None
    value = record[field]
    if _is_null(value):
        return None
    text = value.strip().upper() if isinstance(value, str) else str(value).strip().upper()
    if text in known_states:
        return text
    return None


def _apply_geom_state(row: dict, code: str | None, layer: Layer, *, mailing_state: str | None = None) -> None:
    reviews = [part for part in str(row["review_reason"] or "").split("|") if part]
    if layer.state_from_geometry:
        row["declared_state"] = code
        row["geom_state"] = code
        row["state_mismatch"] = mailing_state_mismatch(code, mailing_state)
        if row["state_mismatch"]:
            reviews.append("state_mismatch")
        if code is None:
            reviews.append("geom_state_unresolved")
    else:
        row["geom_state"] = code
        declared = row["declared_state"]
        mismatch = declared is not None and code is not None and declared != code
        row["state_mismatch"] = mismatch
        if mismatch:
            reviews.append("state_mismatch")
        if code is None:
            reviews.append("geom_state_unresolved")
    row["needs_review"] = bool(reviews)
    row["review_reason"] = "|".join(reviews) or None


def _write_boundaries(frame: pd.DataFrame, geometries: np.ndarray, path: Path) -> None:
    if frame.empty:
        raise ValueError("Water boundary build produced no assertions")
    frame = frame.copy()
    frame["geometry"] = list(geometries)
    geo = gpd.GeoDataFrame(frame, geometry="geometry", crs="EPSG:4326")
    longitude, latitude = representative_longitude_latitude(np.asarray(geo.geometry.values, dtype=object))
    distances = hilbert_distances(longitude, latitude)
    sort_state = geo["geom_state"].fillna(geo["declared_state"]).fillna("")
    geo = geo.assign(_state=sort_state.to_numpy(), _hilbert=distances)
    geo = geo.sort_values(["_state", "_hilbert", "assertion_id"], kind="mergesort").drop(columns=["_state", "_hilbert"])
    geo.to_parquet(path, index=False, write_covering_bbox=True, row_group_size=50_000)


def _load_state_regions(home: Path, sources: list[Source], ref_state_path: Path) -> tuple[np.ndarray, np.ndarray]:
    matches = [home / source.paths[0] for source in sources if source.storage == "home" for layer in source.layers if layer.layer == "tiger_state"]
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError("The Census state file is not available in the data root")
    frame, geometries, crs = read_vector_features(f"/vsizip/{matches[0].resolve().as_posix()}", None, feature_id_field=None)
    if "STATEFP" not in frame.columns:
        raise ValueError("Census state file is missing STATEFP")
    geometries = shapely.make_valid(reproject_geoms(geometries, crs, DESTINATION))
    if bool(shapely.is_empty(geometries).any()):
        raise ValueError("Census state file has an empty geometry")
    reference = pd.read_parquet(ref_state_path, columns=["state", "usps"])
    codes = {str(state).zfill(2): str(usps) for state, usps in zip(reference["state"], reference["usps"], strict=True)}
    state_codes = [str(value).zfill(2) for value in frame["STATEFP"].tolist()]
    missing = sorted(set(state_codes) - set(codes))
    absent = sorted(set(codes) - set(state_codes))
    if missing or absent or len(state_codes) != len(set(state_codes)):
        raise ValueError("Census state polygons do not match ref_state")
    return geometries, np.array([codes[code] for code in state_codes], dtype=object)


def _known_states(path: Path) -> set[str]:
    if not path.is_file():
        raise ValueError("ref_state is not built")
    return set(pd.read_parquet(path, columns=["usps"])["usps"].astype(str))


def _acceptance_report(
    output: Path,
    boundary_path: Path,
    assertions: pd.DataFrame,
    rejects: pd.DataFrame,
    candidates: pd.DataFrame,
    table_counts: dict[str, int],
    layer_reports: list[dict[str, object]],
    drafts: list[str],
    quarter: str,
) -> dict[str, object]:
    if not geoparquet_metadata_present(boundary_path):
        raise ValueError("Boundary output is missing GeoParquet metadata")
    _check_identifiers(output, assertions, candidates)
    community = assertions[assertions["source_layer"].eq("CWS")]
    authority_counts = {str(key): int(value) for key, value in community["authority"].value_counts(dropna=False).items()}
    if authority_counts.get("federal_submitted") != 25409 or authority_counts.get("federal_modeled") != 19247:
        raise ValueError(f"CWS authority counts are {authority_counts}")
    noncommunity_roles = sorted(assertions.loc[assertions["source_layer"].eq("T_NTNC"), "zone_role"].dropna().astype(str).unique())
    if "active_retail_service" in noncommunity_roles or set(noncommunity_roles) - {"onsite_noncommunity", "regional_wholesale_or_district", "review_required"}:
        raise ValueError(f"T_NTNC roles include retail or an undeclared role: {noncommunity_roles}")
    onsite = assertions["zone_role"].eq("onsite_noncommunity")
    if bool(onsite.any()) and not bool(assertions.loc[onsite, "footprint_verified"].eq(False).all()):
        raise ValueError("On-site areas are not flagged as unverified footprints")
    if assertions["source_id"].isin(drafts).any():
        raise ValueError("A draft source was written into water Silver")
    if (assertions["source_id"] == "national_epa_noncommunity_water_service_areas_v1_1").any():
        raise ValueError("The unreviewed noncommunity v1.1 layer was consumed")
    retail_conflict = assertions["zone_role"].isin(["onsite_noncommunity", "regional_wholesale_or_district"]) & assertions["zone_role"].eq("active_retail_service")
    if bool(retail_conflict.any()):
        raise ValueError("An on-site or wholesale role was written as active retail")
    reason_counts = {str(key): int(value) for key, value in rejects["reason"].value_counts(dropna=False).items()} if not rejects.empty else {}
    tables = {
        "boundary_assertion": len(assertions),
        "water_attribute": int(sum(int(item["written"]) for item in layer_reports if item["status"] == "nonspatial" and not str(item["layer"]).endswith(".csv"))),
        "rejects": len(rejects),
        "pwsid_candidate": len(candidates),
        **table_counts,
    }
    return {
        "quarter": quarter,
        "tables": tables,
        "rejects_by_reason": reason_counts,
        "authority_counts": {"CWS": authority_counts},
        "t_ntnc_roles": {role: int((assertions["source_layer"].eq("T_NTNC") & assertions["zone_role"].eq(role)).sum()) for role in noncommunity_roles},
        "onsite_noncommunity": int((assertions["zone_role"] == "onsite_noncommunity").sum()),
        "regional_wholesale_or_district": int((assertions["zone_role"] == "regional_wholesale_or_district").sum()),
        "pwsid_090600058": "090600058",
        "geoparquet_metadata": True,
        "layers": layer_reports,
        "draft_water_sources": drafts,
    }


def _check_identifiers(output: Path, assertions: pd.DataFrame, candidates: pd.DataFrame) -> None:
    systems = pq.read_table(output / "sdwa_public_water_system.parquet", columns=["PWSID"]).column("PWSID").to_pylist()
    if sum(value == "090600058" for value in systems) != 1:
        raise ValueError("PWSID 090600058 was not preserved in SDWA")
    if any(isinstance(value, str) and "090600058" in value and value != "090600058" for value in systems):
        raise ValueError("PWSID 090600058 was rewritten in SDWA")
    exact = assertions["pwsid_raw"].eq("090600058")
    if bool(exact.any()) and not bool(assertions.loc[exact, "pwsid"].eq("090600058").all()):
        raise ValueError("PWSID 090600058 was changed on a boundary")
    florida = assertions[assertions["pwsid"].eq("FL4565183")]
    if florida.empty:
        raise ValueError("The FL4565183 boundary assertion was not preserved")
    oklahoma = assertions[assertions["pwsid_raw"].eq("OKMCD0003")]
    if oklahoma.empty or bool(oklahoma["pwsid"].notna().any()):
        raise ValueError("OKMCD0003 was assigned a federal identifier")
    multi = assertions["review_reason"].fillna("").str.contains("multiple_identifiers") & assertions["source_layer"].eq("CWS")
    multi_ids = set(assertions.loc[multi, "assertion_id"])
    multi_candidates = candidates[candidates["assertion_id"].isin(multi_ids)] if not candidates.empty else candidates
    if len(multi_ids) != 9 or len(multi_candidates) != 26:
        raise ValueError(f"CWS multiple identifiers were {len(multi_ids)} assertions and {len(multi_candidates)} candidates")
    if bool(assertions.loc[multi, "pwsid"].notna().any()):
        raise ValueError("A CWS polygon with multiple identifiers received a federal identifier")


def _reconcile(jobs: list[LayerJob], written: Counter[str], rejected: Counter[str]) -> None:
    expected: Counter[str] = Counter()
    for job in jobs:
        expected[job.source.source_id] += job.feature_count
    for source_id, features in expected.items():
        actual = written[source_id] + rejected[source_id]
        if actual != features:
            raise ValueError(f"{source_id}: snapshot has {features} features, wrote {written[source_id]} and rejected {rejected[source_id]}")


def _require_layer_agreement(sources: list[Source], layers: pd.DataFrame) -> None:
    snapshot_layers = {source_id: set(frame["layer"]) for source_id, frame in layers.groupby("source_id", sort=False)}
    for source in sources:
        if not source.reviewed or not any(layer.sector == "water" for layer in source.layers):
            continue
        declared = {layer.layer for layer in source.layers}
        if snapshot_layers.get(source.source_id, set()) != declared:
            raise ValueError(f"Snapshot layers for {source.source_id} do not match the registry")
        if any(layer.sector != "water" for layer in source.layers):
            raise ValueError(f"{source.source_id} mixes water with another sector")


def _layer_report(job: LayerJob, produced: int, rejected_rows: int) -> dict[str, object]:
    return {
        "source_id": job.source.source_id,
        "layer": job.layer.layer,
        "status": job.status,
        "features": job.feature_count,
        "written": produced,
        "rejected": rejected_rows,
    }


def _feature_id(record: dict, layer: Layer, index: int) -> str:
    field = layer.id_fields.get("feature_id")
    if field is None:
        return f"row-{index}"
    value = record[field]
    if _is_null(value):
        return f"missing-feature-{index}"
    if isinstance(value, bool):
        raise TypeError(f"Feature id {field} is boolean")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text:
        return f"missing-feature-{index}"
    return text


def _raw_name(value: object) -> str | None:
    if _is_null(value):
        return None
    text = value if isinstance(value, str) else _code(value)
    stripped = text.strip()
    return stripped or None


def _name_norm(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    return collapsed.casefold() if collapsed else None


def _code(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _numeric_vintage(value: object) -> date:
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"Unrecognized vintage {value!r}")
    if 1800 <= number <= 2100 and number == int(number):
        return date(int(number), 1, 1)
    seconds = number / 1000.0 if abs(number) >= 10_000_000_000 else number
    if abs(seconds) < 1_000_000_000:
        raise ValueError(f"Unrecognized vintage {value!r}")
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).date()
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(f"Unrecognized vintage {value!r}") from exc


def _safe_date(year: int, month: int, day: int, value: object) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"Unrecognized vintage {value!r}") from exc


def _is_null(value: object) -> bool:
    if value is None or isinstance(value, str):
        return value is None
    return bool(pd.isna(value))


def _assert_never(value: Never) -> NoReturn:
    raise ValueError(f"Unhandled value: {value}")


def _concat(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


@contextmanager
def _extracted_member(archive: Path, member: str) -> Iterator[Path]:
    """Extract one archive member, with shapefile sidecars or a geodatabase folder."""
    with tempfile.TemporaryDirectory(prefix="utilitydata-silver-") as temp_name:
        yield materialize_archive_member(archive, member, Path(temp_name))
