"""Refresh sources from the registry without replacing the last good snapshot blindly."""

import datetime as dt
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry.base import BaseGeometry

from utilitydata.bronze.blobs import (
    blob_name,
    sha256_bytes,
    sha256_file,
    snapshot_blob,
    store_blob,
)
from utilitydata.bronze.drivers import fetch, measure_files
from utilitydata.bronze.drivers.arcgis import recount_features, source_mapped_fields
from utilitydata.bronze.drivers.protocol import (
    CandidateFile,
    FetchRequest,
    PreviousFile,
    Transport,
)
from utilitydata.bronze.drivers.transport import RequestsTransport
from utilitydata.bronze.gate import evaluate_gate
from utilitydata.bronze.snapshot import require_quarter
from utilitydata.core.config import (
    ARCGIS_PAGE_SIZE,
    ARCGIS_TIMEOUT_SECONDS,
    DISCOVER_TIMEOUT_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    REFRESH_AREA_DRIFT,
    REFRESH_COUNT_DRIFT,
)
from utilitydata.registry import Source, load_registry
from utilitydata.silver.boundaries import _load_state_regions

_BUILDABLE = frozenset({"collected", "partial_geometry", "nonspatial"})
_MANIFEST_COLUMNS = (
    "source_id",
    "relative_path",
    "sha256",
    "bytes",
    "retrieved_utc",
    "feature_count",
    "has_geometry",
    "status",
)
_LAYER_COLUMNS = ("source_id", "layer", "feature_count", "status")
_PATH_LITERAL = re.compile(r"""['\"]([^'\"]+\.[A-Za-z0-9]{1,8})['\"]""")
_REFRESH_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("relative_path", pa.string()),
    ("sha256", pa.string()),
    ("bytes", pa.int64()),
    ("retrieved_utc", pa.string()),
    ("blob", pa.string()),
    ("status", pa.string()),
    ("action", pa.string()),
    ("feature_count", pa.int64()),
    ("has_geometry", pa.bool_()),
    ("area", pa.float64()),
])


@dataclass(frozen=True)
class SourceRefresh:
    """One source after a refresh run."""

    source_id: str
    action: str
    status: str
    hashes_match: bool
    differences: tuple[str, ...]
    blobs: tuple[str, ...]
    paths: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class RefreshResult:
    """A refresh report. A dry run is not a published release."""

    snapshot: str
    previous: str
    dry_run: bool
    sources: tuple[SourceRefresh, ...]
    report: Path
    deleted_scripts: tuple[str, ...]
    published: bool


def refresh(
    snapshot: str,
    *,
    previous: str,
    home: Path,
    raw_root: Path,
    registry_dir: Path,
    script_dir: Path | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    source_ids: tuple[str, ...] | None = None,
    transport: Transport | None = None,
    forced_failures: Mapping[str, str] | None = None,
    expected_states: Mapping[str, BaseGeometry] | None = None,
) -> RefreshResult:
    """Read the registry, skip unchanged sources, and carry forward a failed source."""
    require_quarter(snapshot)
    require_quarter(previous)
    if snapshot == previous:
        raise ValueError("Refresh snapshot must be a new quarter")
    _require_limits()
    if limit is not None and limit < 1:
        raise ValueError("Refresh limit must be at least 1")
    manifest_path = home / "snapshots" / previous / "manifest.parquet"
    if not manifest_path.is_file():
        raise ValueError(f"Previous snapshot is missing: {previous}")
    manifest = _read_table(manifest_path, _MANIFEST_COLUMNS, "snapshot manifest")
    layers_path = home / "snapshots" / previous / "layers.parquet"
    layers = _read_table(layers_path, _LAYER_COLUMNS, "snapshot layers") if layers_path.is_file() else None
    full_layers = pq.read_table(layers_path).to_pylist() if layers_path.is_file() else None
    sources = load_registry(registry_dir, require_reviewed=False)
    state_map = expected_states if expected_states is not None else _default_expected_states(home, previous, sources)
    if source_ids is not None:
        chosen, eligible_count, excluded = _select_named(sources, manifest, source_ids)
    else:
        chosen, eligible_count, excluded = _select(sources, manifest, limit)
    caller = transport
    if not dry_run and caller is None:
        caller = RequestsTransport()
    outcomes = [
        _refresh_source(
            item,
            home=home,
            raw_root=raw_root,
            previous_name=previous,
            snapshot=snapshot,
            dry_run=dry_run,
            transport=caller,
            forced_failures=forced_failures or {},
            expected_states=state_map,
            layers=layers,
        )
        for item in chosen
    ]
    rows = [row for outcome in outcomes for row in outcome.rows]
    work = home / "refresh" / snapshot / "work"
    if work.exists():
        shutil.rmtree(work)
    report_dir = home / "refresh" / snapshot
    report_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=_REFRESH_SCHEMA), report_dir / "manifest.parquet")
    matched_paths = {path for outcome in outcomes if outcome.result.hashes_match and outcome.result.action == "skipped" for path in outcome.result.paths}
    deleted = _delete_reproduced_scripts(script_dir, matched_paths)
    published = (
        _publish(home, snapshot, registry_dir, rows, outcomes, full_layers, layers_path)
        if not dry_run and limit is None and source_ids is None and chosen
        else False
    )
    result = RefreshResult(
        snapshot,
        previous,
        dry_run,
        tuple(outcome.result for outcome in outcomes),
        report_dir / "triage_report.md",
        tuple(deleted),
        published,
    )
    retained = sorted(path.name for path in script_dir.glob("collect_round*.py")) if script_dir is not None else []
    result.report.write_text(
        _report(result, eligible_count, excluded, retained, len(manifest)),
        encoding="utf-8",
    )
    return result


def reproduced_scripts(covered: set[str], script_dir: Path) -> list[str]:
    """Return collect scripts whose declared paths were all reproduced."""
    ready = []
    for script in sorted(script_dir.glob("collect_round*.py")):
        paths = _script_paths(script.read_text(encoding="utf-8"))
        if paths and paths <= covered:
            ready.append(script.name)
    return ready


@dataclass
class _Outcome:
    result: SourceRefresh
    rows: list[dict]


def _refresh_source(chosen, *, home, raw_root, previous_name, snapshot, dry_run, transport, forced_failures, expected_states, layers) -> _Outcome:
    source, rows = chosen
    previous_files = _previous_files(home, previous_name, rows)
    status = _one_status(rows, source.source_id)
    feature_count = _recorded_count(rows, layers, source.source_id)
    reader = _snapshot_reader(home, previous_name, previous_files, rows)
    forced = forced_failures.get(source.source_id)
    if forced is not None:
        return _keep(source, previous_files, reader, status, "carried_forward", False, (forced,), forced, feature_count, None)
    request = _request(source, previous_files, reader, home, raw_root, snapshot, dry_run, transport, expected_states)
    try:
        fetched = fetch(request)
    except (OSError, ValueError, TypeError, TimeoutError) as exc:
        return _keep(source, previous_files, reader, status, "carried_forward", False, (str(exc),), str(exc), feature_count, None)
    if fetched.unchanged:
        return _skipped(source, fetched, reader, status, feature_count, previous_files)
    if dry_run:
        note = "dry run kept the last good bytes"
        return _keep(source, previous_files, reader, status, "changed", False, fetched.differences, note, feature_count, None)
    return _gate(source, request, fetched, reader, status, feature_count, expected_states)


def _skipped(source, fetched, reader, status, recorded_count, previous_files) -> _Outcome:
    differences: list[str] = []
    note = "bytes match the frozen snapshot"
    if source.driver == "arcgis":
        try:
            recounted = recount_features({item.relative_path: item.content for item in fetched.files})
        except ValueError as exc:
            recounted = None
            note = f"bytes match; features were not recounted ({exc})"
        if recounted is not None and recorded_count is not None and recounted != recorded_count:
            differences.append(f"feature count recounted {recounted} but the snapshot records {recorded_count}")
            note = differences[-1]
    return _keep(source, previous_files, reader, status, "skipped", True, tuple(differences), note, recorded_count, None)


def _gate(source, request, fetched, reader, status, recorded_count, expected_states) -> _Outcome:
    state_code = _state_code(source)
    expected = expected_states.get(state_code) if state_code else None
    previous_bytes = {item.relative_path: request.read_previous(item.relative_path) for item in request.previous}
    current_bytes = {item.relative_path: item.content for item in fetched.files}
    try:
        before = measure_files(source, previous_bytes, expected_state=expected)
        after = measure_files(source, current_bytes, expected_state=expected)
    except (OSError, ValueError, TypeError) as exc:
        return _keep(source, request.previous, reader, status, "carried_forward", False, fetched.differences + (str(exc),), str(exc), recorded_count, None)
    failures = list(evaluate_gate(before, after, source_mapped_fields(source)))
    if after.spatial and state_code and expected is None:
        failures.append("expected state geometry is unavailable")
    if failures:
        note = "; ".join(failures)
        kept = _keep(source, request.previous, reader, "carried_forward", "carried_forward", False, fetched.differences + tuple(failures), note, recorded_count, before.area)
        return kept
    now_utc = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _store_rows(
        source,
        fetched.files,
        reader.home,
        status,
        "fetched",
        after.feature_count,
        after.area,
        retrieved_by_path={item.relative_path: now_utc for item in fetched.files},
        has_geometry=after.spatial,
    )
    return _Outcome(_view(source, "fetched", status, False, fetched.differences, rows, "gate passed"), rows)


def _store_rows(
    source: Source,
    files,
    home: Path,
    status: str,
    action: str,
    feature_count: int | None,
    area: float | None,
    *,
    retrieved_by_path: Mapping[str, str | None] | None = None,
    has_geometry_by_path: Mapping[str, bool | None] | None = None,
    has_geometry: bool | None = None,
) -> list[dict]:
    rows = []
    for item in files:
        digest = store_blob(home, item.content)
        if sha256_bytes(item.content) != digest:
            raise ValueError(f"Blob pointer does not match {item.relative_path}")
        retrieved = retrieved_by_path.get(item.relative_path) if retrieved_by_path is not None else None
        geom_flag = has_geometry_by_path.get(item.relative_path) if has_geometry_by_path is not None else has_geometry
        rows.append({
            "source_id": source.source_id,
            "relative_path": item.relative_path,
            "sha256": digest,
            "bytes": len(item.content),
            "retrieved_utc": retrieved,
            "blob": blob_name(digest),
            "status": status,
            "action": action,
            "feature_count": feature_count,
            "has_geometry": geom_flag,
            "area": area,
        })
    if not rows:
        raise ValueError(f"{source.source_id} produced no files")
    return rows


def _view(source, action, status, hashes_match, differences, rows, note) -> SourceRefresh:
    return SourceRefresh(
        source.source_id,
        action,
        status,
        hashes_match,
        tuple(differences),
        tuple(row["blob"] for row in rows),
        tuple(row["relative_path"] for row in rows),
        note,
    )


def _keep(source, previous_files, reader, status, action, hashes_match, differences, note, feature_count, area) -> _Outcome:
    files = [CandidateFile(item.relative_path, reader(item.relative_path)) for item in previous_files]
    kept_status = "carried_forward" if action == "carried_forward" else status
    rows = _store_rows(
        source,
        files,
        reader.home,
        kept_status,
        action,
        feature_count,
        area,
        retrieved_by_path={item.relative_path: item.retrieved_utc for item in previous_files},
        has_geometry_by_path=reader.has_geometry,
    )
    return _Outcome(_view(source, action, kept_status, hashes_match, differences, rows, note), rows)


def _request(source, previous_files, reader, home, raw_root, snapshot, dry_run, transport, expected_states) -> FetchRequest:
    page_size, timeout = _limits(source.driver or "")
    state_code = _state_code(source)
    match source.storage:
        case "home":
            root = home
        case "collection":
            root = raw_root
        case _ as storage:
            raise ValueError(f"Unknown storage {storage} for {source.source_id}")
    return FetchRequest(
        source=source,
        dry_run=dry_run,
        staging=home / "refresh" / snapshot / "work" / source.source_id,
        previous=previous_files,
        read_previous=reader,
        read_current=_reader(root),
        transport=transport,
        page_size=page_size,
        timeout_seconds=timeout,
        expected_state=expected_states.get(state_code) if state_code else None,
    )


class _SnapshotReader:
    """Read one previous snapshot file (copied or blob-backed) and remember the data root."""

    def __init__(self, home: Path, previous_name: str, digests: dict[str, str], has_geometry: dict[str, bool | None]) -> None:
        self.home = home
        self.previous_name = previous_name
        self.root = home / "snapshots" / previous_name / "files"
        self.digests = digests
        self.has_geometry = has_geometry

    def __call__(self, relative: str) -> bytes:
        digest = self.digests.get(relative)
        if digest is None:
            raise ValueError(f"Previous snapshot file is missing: {relative}")
        path = _resolve_previous_path(self.home, self.previous_name, relative)
        content = path.read_bytes()
        if sha256_bytes(content) != digest:
            raise ValueError(f"Frozen snapshot hash does not match the manifest: {relative}")
        return content


def _resolve_previous_path(home: Path, previous: str, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"Invalid source path: {relative}")
    files_root = (home / "snapshots" / previous / "files").resolve()
    copied = (files_root / relative).resolve()
    if copied.is_relative_to(files_root) and copied.is_file() and not copied.is_symlink():
        return copied
    pointed = snapshot_blob(home, previous, relative)
    if pointed is not None:
        return pointed
    raise ValueError(f"Missing source file: {relative}")


def _snapshot_reader(home: Path, previous_name: str, files: tuple[PreviousFile, ...], rows: pd.DataFrame | None = None) -> _SnapshotReader:
    geom_map: dict[str, bool | None] = {}
    if rows is not None and "has_geometry" in rows.columns:
        for row in rows.itertuples(index=False):
            val = row.has_geometry
            geom_map[str(row.relative_path)] = None if pd.isna(val) else bool(val)
    return _SnapshotReader(home, previous_name, {item.relative_path: item.sha256 for item in files}, geom_map)


def _previous_files(home: Path, previous: str, rows: pd.DataFrame) -> tuple[PreviousFile, ...]:
    files = []
    for row in rows.itertuples(index=False):
        relative = str(row.relative_path)
        path = _resolve_previous_path(home, previous, relative)
        digest = sha256_file(path)
        recorded = str(row.sha256)
        if digest != recorded:
            raise ValueError(f"Frozen snapshot hash does not match the manifest: {relative}")
        retrieved = None if pd.isna(row.retrieved_utc) else str(row.retrieved_utc)
        files.append(PreviousFile(relative, recorded, int(row.bytes), retrieved))
    if not files:
        raise ValueError("Selected source has no files")
    return tuple(files)


def _select_named(sources: list[Source], manifest: pd.DataFrame, source_ids: tuple[str, ...]):
    """Select named sources, including drafts. A missing id raises."""
    if not source_ids:
        raise ValueError("Refresh source list is empty")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Refresh source was named more than once")
    by_id = {source.source_id: source for source in sources}
    selected = []
    for source_id in source_ids:
        source = by_id.get(source_id)
        if source is None:
            raise ValueError(f"Refresh source is not in the registry: {source_id}")
        rows = manifest.loc[manifest["source_id"].astype(str).eq(source_id)]
        if rows.empty:
            raise ValueError(f"Refresh source is not in the previous snapshot: {source_id}")
        selected.append((source, rows))
    return selected, len(selected), (0, 0)


def _select(sources: list[Source], manifest: pd.DataFrame, limit: int | None):
    by_id = {source.source_id: source for source in sources}
    eligible = []
    not_buildable = 0
    unreviewed = 0
    grouped = manifest.dropna(subset=["source_id"]).groupby("source_id", sort=False)
    for source_id, rows in grouped:
        source = by_id.get(str(source_id))
        if source is None or not source.reviewed or source.driver is None:
            unreviewed += 1
            continue
        statuses = {str(value) for value in rows["status"].dropna().unique()}
        if not statuses or not statuses <= (_BUILDABLE | {"carried_forward"}):
            not_buildable += 1
            continue
        eligible.append((int(rows["bytes"].sum()), source.source_id, source, rows))
    eligible.sort(key=lambda item: (item[0], item[1]))
    chosen = eligible if limit is None else eligible[:limit]
    selected = [(source, rows) for _size, _source_id, source, rows in chosen]
    return selected, len(eligible), (not_buildable, unreviewed)


def _read_table(path: Path, columns: tuple[str, ...], label: str) -> pd.DataFrame:
    table = pq.read_table(path)
    missing = [name for name in columns if name not in table.column_names]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")
    return table.select(list(columns)).to_pandas()


def _one_status(rows: pd.DataFrame, source_id: str) -> str:
    statuses = {str(value) for value in rows["status"].dropna().unique()}
    if len(statuses) != 1:
        raise ValueError(f"{source_id} has more than one snapshot status")
    return next(iter(statuses))


def _recorded_count(rows: pd.DataFrame, layers: pd.DataFrame | None, source_id: str) -> int | None:
    if layers is not None:
        selected = layers.loc[layers["source_id"] == source_id, "feature_count"]
        if not selected.empty and selected.notna().any():
            return _sum_ints(selected, f"{source_id} layer feature count")
    page_counts = rows["feature_count"].dropna()
    if page_counts.empty:
        return None
    return _sum_ints(page_counts, f"{source_id} feature count")


def _sum_ints(values: pd.Series, label: str) -> int:
    total = 0
    for value in values:
        number = _optional_int(value, label)
        if number is None:
            raise ValueError(f"{label} is missing")
        total += number
    return total


def _optional_int(value: object, label: str) -> int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} is not an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label} is not an integer")
    return int(value)


def _state_code(source: Source) -> str | None:
    codes = {layer.state_fixed for layer in source.layers if layer.state_fixed}
    if len(codes) > 1:
        raise ValueError(f"{source.source_id} declares more than one state")
    return next(iter(codes), None)


def _limits(driver: str) -> tuple[int, float]:
    match driver:
        case "arcgis":
            return ARCGIS_PAGE_SIZE, float(ARCGIS_TIMEOUT_SECONDS)
        case "http":
            return ARCGIS_PAGE_SIZE, float(HTTP_TIMEOUT_SECONDS)
        case "discover":
            return ARCGIS_PAGE_SIZE, float(DISCOVER_TIMEOUT_SECONDS)
        case "custom":
            return ARCGIS_PAGE_SIZE, float(HTTP_TIMEOUT_SECONDS)
        case _:
            raise ValueError(f"Unknown driver: {driver}")


def _require_limits() -> None:
    if ARCGIS_PAGE_SIZE < 2:
        raise ValueError("ARCGIS_PAGE_SIZE must be at least 2")
    if min(ARCGIS_TIMEOUT_SECONDS, HTTP_TIMEOUT_SECONDS, DISCOVER_TIMEOUT_SECONDS) <= 0:
        raise ValueError("Refresh timeouts must be positive")
    if REFRESH_COUNT_DRIFT < 0 or REFRESH_AREA_DRIFT < 0:
        raise ValueError("Refresh drift thresholds cannot be negative")


def _reader(root: Path):
    def read(relative: str) -> bytes:
        return _inside(root, relative).read_bytes()

    return read


def _inside(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"Invalid source path: {relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing source file: {relative}")
    return path


def _script_paths(text: str) -> set[str]:
    paths = set()
    for match in _PATH_LITERAL.findall(text):
        normalized = match.replace("\\", "/")
        if "://" in normalized or normalized.startswith(("/", ".")) or "/" not in normalized:
            continue
        paths.add(normalized)
    return paths


def _delete_reproduced_scripts(script_dir: Path | None, covered: set[str]) -> list[str]:
    if script_dir is None:
        return []
    deleted = []
    for name in reproduced_scripts(covered, script_dir):
        (script_dir / name).unlink()
        deleted.append(name)
    return deleted


def _default_expected_states(home: Path, previous: str, sources: list[Source]) -> Mapping[str, BaseGeometry]:
    ref_state = home / "silver" / previous / "ref_state.parquet"
    if not ref_state.is_file():
        candidates = sorted((home / "silver").glob("*/ref_state.parquet"))
        ref_state = candidates[-1] if candidates else ref_state
    if not ref_state.is_file():
        return {}
    try:
        geometries, codes = _load_state_regions(home, sources, ref_state)
    except (OSError, ValueError):
        return {}
    return {str(code): geom for geom, code in zip(geometries, codes, strict=True)}


def _publish(
    home: Path,
    snapshot: str,
    registry_dir: Path,
    rows: list[dict],
    outcomes: list[_Outcome],
    previous_layers: list[dict] | None,
    previous_layers_path: Path | None,
) -> bool:
    snapshots = (home / "snapshots").resolve()
    target = snapshots / snapshot
    if target.exists():
        raise FileExistsError(f"Snapshot already exists: {snapshot}")
    snapshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{snapshot}-", dir=snapshots) as staging_name:
        staging = Path(staging_name).resolve()
        if not staging.is_relative_to(snapshots):
            raise ValueError("Snapshot staging path escapes snapshot root")
        payload = staging / "snapshot"
        payload.mkdir()
        pq.write_table(pa.Table.from_pylist(rows, schema=_REFRESH_SCHEMA), payload / "manifest.parquet")
        if previous_layers is not None and previous_layers_path is not None and previous_layers_path.is_file():
            updated_counts = {
                outcome.result.source_id: (outcome.rows[0].get("feature_count"), outcome.result.status)
                for outcome in outcomes
                if outcome.rows
            }
            chosen_ids = set(updated_counts)
            layer_rows = []
            for layer_row in previous_layers:
                sid = str(layer_row.get("source_id") or "")
                if sid not in chosen_ids:
                    continue
                copied_row = dict(layer_row)
                new_count, new_status = updated_counts[sid]
                if new_count is not None and len([r for r in previous_layers if r.get("source_id") == sid]) == 1:
                    copied_row["feature_count"] = new_count
                if new_status != "carried_forward":
                    copied_row["status"] = new_status
                layer_rows.append(copied_row)
            pq.write_table(pa.Table.from_pylist(layer_rows, schema=pq.read_schema(previous_layers_path)), payload / "layers.parquet")
        registry_copy = payload / "registry" / "sources"
        registry_copy.mkdir(parents=True)
        registry_files = sorted(registry_dir.glob("*.yaml"))
        if not registry_files:
            raise ValueError("No registry files in the refresh")
        for path in registry_files:
            (registry_copy / path.name).write_bytes(path.read_bytes())
        registry_root = registry_dir.parent.resolve()
        unused_file = registry_root / "unused.yaml"
        if unused_file.is_file():
            (payload / "registry" / "unused.yaml").write_bytes(unused_file.read_bytes())
        for folder in ("vocab", "overrides", "truth"):
            folder_path = registry_root / folder
            if folder_path.is_dir():
                for item in sorted(folder_path.rglob("*")):
                    if item.is_file() and not item.is_symlink():
                        rel = item.relative_to(registry_root)
                        dest = payload / "registry" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(item.read_bytes())
        payload.rename(target)
    return True


def _report(result: RefreshResult, eligible: int, excluded: tuple[int, int], retained: list[str], manifest_rows: int) -> str:
    lines = [
        f"# Refresh {result.snapshot}",
        "",
        f"Previous snapshot: {result.previous}",
        f"Dry run: {str(result.dry_run).lower()}",
        f"Published snapshot: {str(result.published).lower()}",
        "",
        "This run does not replace the previous snapshot.",
    ]
    if result.dry_run or not result.published:
        lines.append(f"This is not a full {result.snapshot} release.")
    lines.extend([
        "",
        f"Eligible buildable sources in the previous manifest: {eligible}. Sources in this run: {len(result.sources)}.",
        "A limit keeps the smallest of those sources by frozen byte count.",
        f"Reviewed manifest sources that are not buildable and were left out: {excluded[0]}.",
        f"Unreviewed manifest sources left out: {excluded[1]}.",
        f"Previous manifest rows: {manifest_rows}. Blob files were written only for sources in this run.",
        "",
        "| source_id | action | status | hashes | blob |",
        "| --- | --- | --- | --- | --- |",
    ])
    for source in result.sources:
        hashes = "match" if source.hashes_match else "differ"
        blob = ", ".join(source.blobs)
        lines.append(f"| {source.source_id} | {source.action} | {source.status} | {hashes} | {blob} |")
    lines.extend(["", "## Sources", ""])
    if result.sources and all(source.hashes_match and not source.differences for source in result.sources):
        lines.append("Every selected source matches the frozen snapshot hashes.")
    for source in result.sources:
        hashes = "match" if source.hashes_match else "differ"
        detail = "; ".join(source.differences) if source.differences else source.note
        lines.append(f"- {source.source_id}: hashes {hashes}; {source.action}; {detail}")
    lines.extend(["", "## Collection scripts", ""])
    if result.deleted_scripts:
        lines.append("Deleted after every collected path was reproduced: " + ", ".join(result.deleted_scripts))
    elif retained:
        lines.append("No collect_round script was deleted. This run did not reproduce every path these scripts collect:")
        lines.extend(f"- {name}" for name in retained)
    else:
        lines.append("No collect_round script was deleted.")
    lines.extend([
        "",
        "## Limits",
        "",
        "A dry run does not contact publishers.",
        "Unchanged bytes are not remeasured against a state outline.",
        "The full collection was not copied into blobs.",
        "Custom sources are compared locally and are not downloaded.",
        "",
    ])
    return "\n".join(lines)
