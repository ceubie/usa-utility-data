"""Read declared columns from a reviewed archive without guessing names."""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

import pandas as pd

from utilitydata.bronze.blobs import snapshot_blob
from utilitydata.core.text import require_columns
from utilitydata.registry import Layer, Source


def layer_ending(source: Source, suffix: str) -> Layer:
    """Return the one declared layer whose file name is suffix."""
    found = [layer for layer in source.layers if PurePosixPath(layer.layer).name == suffix]
    if len(found) != 1:
        raise ValueError(f"{source.source_id} needs one layer named {suffix}")
    return found[0]


def field_name(layer: Layer, logical: str) -> str:
    """Return the source column declared for a logical name."""
    if logical in layer.id_fields:
        return layer.id_fields[logical]
    if logical in layer.attribute_fields:
        return layer.attribute_fields[logical]
    raise ValueError(f"{layer.layer} does not name {logical}")


def read_csv_fields(archive: Path, layer: Layer, logical: tuple[str, ...]) -> pd.DataFrame:
    """Read the named fields. A missing column or archive member raises."""
    columns = [field_name(layer, name) for name in logical]
    if not zipfile.is_zipfile(archive):
        raise ValueError(f"CSV archive is not a zip: {layer.layer}")
    with zipfile.ZipFile(archive) as bundle:
        if layer.layer not in bundle.namelist():
            raise ValueError(f"Missing archive member {layer.layer}")
        frame = pd.read_csv(bundle.open(layer.layer), dtype="string", encoding="utf-8-sig", keep_default_na=False)
    require_columns(frame, columns, layer.layer)
    selected = frame.loc[:, columns].copy()
    selected = selected.replace({"": pd.NA})
    renamed = {source: logical_name for logical_name, source in zip(logical, columns, strict=True)}
    return selected.rename(columns=renamed)


def snapshot_path(home: Path, quarter: str, relative: str) -> Path:
    """Return one frozen collection path. It must stay inside the snapshot.

    A snapshot that copied files still reads those files. A later snapshot can
    point at a content-addressed blob instead of copying the bytes again.
    """
    root = (home / "snapshots" / quarter / "files").resolve()
    path = (root / relative).resolve()
    if path.is_relative_to(root) and path.exists() and not path.is_symlink():
        return path
    pointed = snapshot_blob(home, quarter, relative)
    if pointed is not None:
        return pointed
    raise ValueError(f"Snapshot path is missing: {relative}")
