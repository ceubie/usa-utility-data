"""Account for raw files and freeze verified, immutable collection snapshots."""

import csv
import gzip
import hashlib
import io
import json
import re
import shutil
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pyogrio
import yaml

from utilitydata.registry import Source, load_registry


def _checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_absolute() and not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path outside raw collection: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path outside raw collection: {relative}")
    if not path.exists() or path.is_symlink():
        raise ValueError(f"Missing or symbolic-link collection path: {relative}")
    return path


def _files(path: Path):
    if path.is_file():
        return [path]
    files = []
    for child in path.rglob("*"):
        if child.is_symlink():
            raise ValueError(f"Symbolic link in raw collection: {child}")
        if child.is_file():
            files.append(child)
    return files


def inventory(raw_root: Path, sources: list[Source], unused_path: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Return unique source ownership, declared unused files, and unassigned files."""
    raw_root = raw_root.resolve()
    owners = {}
    for source in sources:
        for value in source.paths:
            for file in _files(_checked_path(raw_root, value)):
                relative = file.relative_to(raw_root).as_posix()
                if relative in owners:
                    raise ValueError(f"File assigned to multiple sources: {relative}")
                owners[relative] = source.source_id
    unused = {}
    if unused_path.exists():
        content = yaml.safe_load(unused_path.read_text(encoding="utf-8"))
        if not isinstance(content, dict) or set(content) != {"unused"} or not isinstance(content["unused"], list):
            raise ValueError("Unused file must contain an unused list")
        for item in content["unused"]:
            if not isinstance(item, dict) or set(item) != {"path", "reason"} or not isinstance(item["reason"], str) or not item["reason"].strip():
                raise ValueError("Each unused path requires an explicit reason")
            for file in _files(_checked_path(raw_root, item["path"])):
                relative = file.relative_to(raw_root).as_posix()
                if relative in owners or relative in unused:
                    raise ValueError(f"File has multiple registry dispositions: {relative}")
                unused[relative] = item["reason"]
    all_files = {p.relative_to(raw_root).as_posix() for p in _files(raw_root)}
    return owners, unused, sorted(all_files - set(owners) - set(unused))


def _inspect_arcgis(source: Source, root: Path) -> tuple[dict[str, dict], str]:
    details = {}
    total_features = 0
    total_geometry = 0
    expects_geometry = False
    for value in source.paths:
        directory = _checked_path(root, value)
        if not directory.is_dir():
            continue
        snap_path = directory / "snapshot.json"
        if not snap_path.is_file():
            raise ValueError(f"Missing ArcGIS snapshot for {source.source_id}")
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        metadata_path = directory / "layer_metadata.json"
        if not metadata_path.is_file():
            raise ValueError(f"Missing ArcGIS metadata for {source.source_id}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        layer_type = metadata.get("type")
        if (layer_type == "Feature Layer" and not metadata.get("geometryType")) or (layer_type == "Table" and metadata.get("geometryType")) or layer_type not in {"Feature Layer", "Table"}:
            raise ValueError(f"Inconsistent ArcGIS geometry metadata for {source.source_id}")
        expects_geometry = expects_geometry or layer_type == "Feature Layer"
        if snapshot.get("source_layer", "").rstrip("/").casefold() != (source.url or "").rstrip("/").casefold():
            raise ValueError(f"Snapshot URL mismatch for {source.source_id}")
        expected_pages = set()
        directory_features = 0
        for page in snapshot.get("pages", []):
            page_path = _checked_path(directory, page["file"])
            if not page_path.is_file() or page_path.parent != directory:
                raise ValueError(f"Invalid page path for {source.source_id}")
            expected_pages.add(page_path.name)
            sha = hashlib.sha256()
            with page_path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(block)
            if sha.hexdigest() != page.get("sha256"):
                raise ValueError(f"ArcGIS page hash mismatch: {page_path.name}")
            with gzip.open(page_path, "rt", encoding="utf-8") as stream:
                content = json.load(stream)
            features = content.get("features")
            if not isinstance(features, list) or len(features) != page.get("features"):
                raise ValueError(f"ArcGIS page count mismatch: {page_path.name}")
            count = len(features)
            geometry = sum(feature.get("geometry") is not None for feature in features)
            total_features += count
            directory_features += count
            total_geometry += geometry
            details[page_path.relative_to(root).as_posix()] = {"feature_count": count, "has_geometry": None if not count or 0 < geometry < count else geometry == count, "expected_sha256": page["sha256"]}
        actual_pages = {p.name for p in directory.glob("page*.json.gz")}
        if expected_pages != actual_pages:
            raise ValueError(f"ArcGIS page inventory mismatch for {source.source_id}")
        if directory_features != snapshot.get("downloaded_count") or directory_features != snapshot.get("id_count") or directory_features != snapshot.get("expected_count_at_start"):
            raise ValueError(f"ArcGIS source count mismatch for {source.source_id}")
        details["__retrieved_utc"] = snapshot.get("retrieved_utc")
    if not expects_geometry and total_geometry:
        raise ValueError(f"Unexpected geometry for nonspatial source {source.source_id}")
    status = "nonspatial" if not expects_geometry else "no_geometry" if total_features and not total_geometry else "partial_geometry" if 0 < total_geometry < total_features else "collected"
    details["__feature_count"] = total_features
    details["__geometry_count"] = total_geometry if expects_geometry else None
    return details, status


def _retrieval_records(root: Path) -> dict[str, list[tuple[str, str]]]:
    """Read saved retrieval dates only when the source recorded the file hash."""
    records = {}
    for manifest in sorted(root.glob("manifest*.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict):
                continue
            path, sha, retrieved = entry.get("path"), entry.get("sha256"), entry.get("retrieved_utc")
            if all(isinstance(value, str) and value for value in (path, sha, retrieved)):
                normalized = path.replace("\\", "/").removeprefix("collection/data/").removeprefix("data/")
                if not normalized.startswith("/") and ".." not in Path(normalized).parts:
                    records.setdefault(normalized, []).append((sha, retrieved))
    return records


def _inspect_archived_layers(source: Source, frozen_root: Path, staging: Path) -> list[dict]:
    """Count features and actual nonempty geometries in frozen GeoPackage layers."""
    layers = [layer for layer in source.layers if layer.archive_member]
    if not layers:
        return []
    if len(source.paths) != 1:
        raise ValueError(f"Geospatial archive source needs exactly one path: {source.source_id}")
    archive_path = _checked_path(frozen_root, source.paths[0])
    rows = []
    with zipfile.ZipFile(archive_path) as bundle:
        for member in sorted({layer.archive_member for layer in layers}):
            with tempfile.TemporaryDirectory(prefix="inspect-", dir=staging) as temp_name:
                temp_path = Path(temp_name).resolve()
                if not temp_path.is_relative_to(staging.resolve()):
                    raise ValueError("Layer inspection path escapes snapshot staging")
                extracted = temp_path / Path(member).name
                with bundle.open(member) as raw, extracted.open("xb") as output:
                    shutil.copyfileobj(raw, output, 4 * 1024 * 1024)
                for layer in (item for item in layers if item.archive_member == member):
                    info = pyogrio.read_info(extracted, layer=layer.layer)
                    count = info["features"]
                    if count < 0:
                        raise ValueError(f"Unknown feature count for {source.source_id}.{layer.layer}")
                    geometry_count = 0
                    if info.get("geometry_type"):
                        for offset in range(0, count, 10000):
                            frame = pyogrio.read_dataframe(extracted, layer=layer.layer, columns=[], skip_features=offset, max_features=min(10000, count - offset))
                            if len(frame) != min(10000, count - offset):
                                raise ValueError(f"Feature count changed for {source.source_id}.{layer.layer}")
                            geometry_count += int((~frame.geometry.isna() & ~frame.geometry.is_empty).sum())
                    status = "nonspatial" if not info.get("geometry_type") else "no_geometry" if count and not geometry_count else "partial_geometry" if geometry_count < count else "collected"
                    rows.append({"source_id": source.source_id, "relative_path": source.paths[0], "archive_member": member, "layer": layer.layer, "feature_count": count, "geometry_count": geometry_count if info.get("geometry_type") else None, "status": status})
    return rows


def _inspect_csv_layers(source: Source, frozen_root: Path) -> list[dict]:
    """Count every archived CSV record and fail on duplicate headers or ragged rows."""
    layers = [layer for layer in source.layers if not layer.archive_member and layer.layer.lower().endswith(".csv")]
    if not layers:
        return []
    if len(source.paths) != 1:
        raise ValueError(f"CSV archive source needs exactly one path: {source.source_id}")
    archive_path = _checked_path(frozen_root, source.paths[0])
    rows = []
    with ExitStack() as stack:
        bundle = stack.enter_context(zipfile.ZipFile(archive_path)) if zipfile.is_zipfile(archive_path) else None
        for layer in layers:
            if bundle is not None:
                raw = stack.enter_context(bundle.open(layer.layer))
                member = layer.layer
            elif archive_path.suffix.lower() == ".csv" and layer.layer == archive_path.name:
                raw = stack.enter_context(archive_path.open("rb"))
                member = None
            else:
                raise ValueError(f"Invalid CSV source for {source.source_id}.{layer.layer}")
            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                headers = next(reader, [])
                if not headers or len(headers) != len(set(headers)) or any(not name for name in headers):
                    raise ValueError(f"Invalid or duplicate CSV header for {source.source_id}.{layer.layer}")
                count = 0
                for record in reader:
                    if len(record) != len(headers):
                        raise ValueError(f"Malformed CSV row in {source.source_id}.{layer.layer}")
                    count += 1
            rows.append({"source_id": source.source_id, "relative_path": source.paths[0], "archive_member": member, "layer": layer.layer, "feature_count": count, "geometry_count": None, "status": "nonspatial"})
    return rows


def freeze(quarter: str, *, home: Path, raw_root: Path, registry_dir: Path, unused_path: Path) -> Path:
    if not re.fullmatch(r"[0-9]{4}-Q[1-4]", quarter):
        raise ValueError("Snapshot must be formatted YYYY-QN")
    registry_bytes = {p.name: p.read_bytes() for p in sorted(registry_dir.glob("*.yaml"))}
    unused_bytes = unused_path.read_bytes() if unused_path.exists() else None
    sources = load_registry(registry_dir, require_reviewed=True, raw_root=raw_root)
    owners, unused, unassigned = inventory(raw_root, sources, unused_path)
    if registry_bytes != {p.name: p.read_bytes() for p in sorted(registry_dir.glob("*.yaml"))} or unused_bytes != (unused_path.read_bytes() if unused_path.exists() else None):
        raise ValueError("Registry changed during snapshot preparation")
    if unassigned:
        raise ValueError(f"{len(unassigned)} raw files lack a registry disposition; first: {unassigned[0]}")
    root = raw_root.resolve()
    retrieval_records = _retrieval_records(root)
    snapshots = (home / "snapshots").resolve()
    snapshots.mkdir(parents=True, exist_ok=True)
    target = snapshots / quarter
    if target.exists():
        raise FileExistsError(f"Snapshot already exists: {quarter}")
    rows = []
    # A temporary directory under the verified snapshot root is atomically renamed
    # only after every copy and the manifest have succeeded.
    with tempfile.TemporaryDirectory(prefix=f".{quarter}-", dir=snapshots) as staging_name:
        staging = Path(staging_name).resolve()
        if not staging.is_relative_to(snapshots):
            raise ValueError("Snapshot staging path escapes snapshot root")
        payload = staging / "snapshot"
        payload.mkdir()
        for relative in sorted(set(owners) | set(unused)):
            source_path = _checked_path(root, relative)
            initial_stat = source_path.stat()
            destination = payload / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            sha = hashlib.sha256()
            size = 0
            with source_path.open("rb") as reader, destination.open("xb") as writer:
                for block in iter(lambda: reader.read(4 * 1024 * 1024), b""):
                    sha.update(block)
                    size += len(block)
                    writer.write(block)
            final_stat = source_path.stat()
            if size != final_stat.st_size or size != destination.stat().st_size or initial_stat.st_mtime_ns != final_stat.st_mtime_ns or initial_stat.st_size != final_stat.st_size:
                raise ValueError(f"Source changed during snapshot: {relative}")
            with destination.open("rb") as copied:
                copied_hash = hashlib.file_digest(copied, "sha256").hexdigest()
            if copied_hash != sha.hexdigest():
                raise ValueError(f"Copied file failed checksum verification: {relative}")
            source_id = owners.get(relative)
            dates = [date for recorded_hash, date in retrieval_records.get(relative, []) if recorded_hash.casefold() == sha.hexdigest()]
            rows.append({"source_id": source_id, "relative_path": relative, "sha256": sha.hexdigest(), "bytes": size, "retrieved_utc": max(dates) if dates else None, "feature_count": None, "has_geometry": None, "status": "unused" if relative in unused else "collected"})
        layer_rows = []
        frozen_root = (payload / "files").resolve()
        registry_copy = payload / "registry" / "sources"
        registry_copy.mkdir(parents=True)
        for name, content in registry_bytes.items():
            (registry_copy / name).write_bytes(content)
        if unused_bytes is not None:
            (payload / "registry" / "unused.yaml").write_bytes(unused_bytes)
        # Check the copied bytes, not just the live files inspected before copy.
        load_registry(registry_copy, require_reviewed=True, raw_root=frozen_root)
        for source in sources:
            if source.driver == "arcgis":
                if len(source.layers) != 1:
                    raise ValueError(f"ArcGIS snapshot requires one declared layer per source: {source.source_id}")
                details, status = _inspect_arcgis(source, frozen_root)
                for row in rows:
                    if row["source_id"] == source.source_id:
                        info = details.get(row["relative_path"], {})
                        row.update(retrieved_utc=details.get("__retrieved_utc"), feature_count=info.get("feature_count"), has_geometry=info.get("has_geometry"), status=status)
                layer_rows.append({"source_id": source.source_id, "relative_path": source.paths[0], "archive_member": None, "layer": source.layers[0].layer, "feature_count": details["__feature_count"], "geometry_count": details["__geometry_count"], "status": status})
            layer_rows.extend(_inspect_archived_layers(source, frozen_root, staging))
            layer_rows.extend(_inspect_csv_layers(source, frozen_root))
        for row in rows:
            with _checked_path(frozen_root, row["relative_path"]).open("rb") as copied:
                if hashlib.file_digest(copied, "sha256").hexdigest() != row["sha256"]:
                    raise ValueError(f"Frozen file changed during validation: {row['relative_path']}")
        schema = pa.schema([("source_id", pa.string()), ("relative_path", pa.string()), ("sha256", pa.string()), ("bytes", pa.int64()), ("retrieved_utc", pa.string()), ("feature_count", pa.int64()), ("has_geometry", pa.bool_()), ("status", pa.string())])
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), payload / "manifest.parquet")
        layer_schema = pa.schema([("source_id", pa.string()), ("relative_path", pa.string()), ("archive_member", pa.string()), ("layer", pa.string()), ("feature_count", pa.int64()), ("geometry_count", pa.int64()), ("status", pa.string())])
        pq.write_table(pa.Table.from_pylist(layer_rows, schema=layer_schema), payload / "layers.parquet")
        payload.rename(target)
    return target
