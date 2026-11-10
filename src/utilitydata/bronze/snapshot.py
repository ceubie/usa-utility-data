"""Account for raw files and freeze verified, immutable collection snapshots."""

import gzip
import hashlib
import json
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
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
    arcgis = {}
    for source in sources:
        if source.driver == "arcgis":
            arcgis[source.source_id] = _inspect_arcgis(source, root)
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
            details, status = arcgis.get(source_id, ({}, "collected"))
            info = details.get(relative, {})
            if info.get("expected_sha256") and info["expected_sha256"] != sha.hexdigest():
                raise ValueError(f"ArcGIS page changed during snapshot: {relative}")
            dates = [date for recorded_hash, date in retrieval_records.get(relative, []) if recorded_hash.casefold() == sha.hexdigest()]
            retrieved = details.get("__retrieved_utc") or (max(dates) if dates else None)
            rows.append({"source_id": source_id, "relative_path": relative, "sha256": sha.hexdigest(), "bytes": size, "retrieved_utc": retrieved, "feature_count": info.get("feature_count"), "has_geometry": info.get("has_geometry"), "status": "unused" if relative in unused else status})
        schema = pa.schema([("source_id", pa.string()), ("relative_path", pa.string()), ("sha256", pa.string()), ("bytes", pa.int64()), ("retrieved_utc", pa.string()), ("feature_count", pa.int64()), ("has_geometry", pa.bool_()), ("status", pa.string())])
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), payload / "manifest.parquet")
        registry_copy = payload / "registry" / "sources"
        registry_copy.mkdir(parents=True)
        for name, content in registry_bytes.items():
            (registry_copy / name).write_bytes(content)
        if unused_bytes is not None:
            (payload / "registry" / "unused.yaml").write_bytes(unused_bytes)
        payload.rename(target)
    return target
