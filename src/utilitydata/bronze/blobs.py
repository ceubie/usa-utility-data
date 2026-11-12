"""Content-addressed copies of raw files.

A snapshot manifest stores a path relative to the data root. The bytes live
under ``blobs/`` and are named by their SHA-256 digest. An existing blob is
never overwritten.
"""

import hashlib
from pathlib import Path

import pyarrow.parquet as pq

_DIGEST = 64


def sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 hex digest of an in-memory file."""
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file without loading it all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def blob_name(digest: str) -> str:
    """Return the data-root-relative path for one digest."""
    if len(digest) != _DIGEST or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Blob name must be a sha256 hex digest")
    return f"blobs/{digest[:2]}/{digest}"


def blob_file(home: Path, digest: str) -> Path:
    """Return the blob path and reject a name that leaves the blob store."""
    relative = blob_name(digest)
    path = (home / relative).resolve()
    root = (home / "blobs").resolve()
    if not path.is_relative_to(root):
        raise ValueError("Blob path escapes the blob store")
    return path


def store_blob(home: Path, content: bytes) -> str:
    """Store bytes under their digest. Identical bytes are left in place."""
    digest = sha256_bytes(content)
    path = blob_file(home, digest)
    if path.exists():
        _require_blob(path, digest)
        return digest
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{digest}.partial")
    temporary.write_bytes(content)
    try:
        if sha256_file(temporary) != digest:
            raise ValueError("Blob write failed its checksum")
        if path.exists():
            _require_blob(path, digest)
            return digest
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    _require_blob(path, digest)
    return digest


def snapshot_blob(home: Path, quarter: str, relative: str) -> Path | None:
    """Return the blob a snapshot manifest names, when the manifest has one."""
    manifest = home / "snapshots" / quarter / "manifest.parquet"
    if not manifest.is_file():
        return None
    table = pq.read_table(manifest)
    if "blob" not in table.column_names or "relative_path" not in table.column_names:
        return None
    matches = [
        blob
        for path, blob in zip(table.column("relative_path").to_pylist(), table.column("blob").to_pylist(), strict=True)
        if path == relative
    ]
    if not matches:
        return None
    if len(set(matches)) != 1:
        raise ValueError(f"Snapshot has more than one blob for {relative}")
    value = matches[0]
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"Snapshot blob pointer is invalid: {relative}")
    path = (home / value).resolve()
    root = (home / "blobs").resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError(f"Snapshot blob is missing: {relative}")
    return path


def _require_blob(path: Path, digest: str) -> None:
    if path.is_symlink():
        raise ValueError("Blob path is a symbolic link")
    if sha256_file(path) != digest:
        raise ValueError("Blob name does not match its bytes")
