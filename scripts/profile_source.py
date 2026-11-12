"""Profile a saved source without collapsing null, empty, and whitespace.

Prints, for each field, how many values are null, how many are an empty
string, how many are whitespace, how many distinct values remain, and the
most common values with ``repr`` so a single space is visible. ArcGIS page
folders, zipped shapefiles, GeoPackages, GeoJSON, and CSV are accepted.

Run from the repository root:

    uv run python scripts/profile_source.py collection/data/gis/texas_water_service_areas_twdb
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

from utilitydata.bronze.archive import materialize_archive_member

_PAGE_CHUNK = 10_000
_VECTOR_SUFFIXES = {".gpkg": "geopackage", ".geojson": "geojson", ".json": "geojson", ".shp": "shapefile"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile nulls, distinct values, and top values in a saved source.")
    parser.add_argument("path", help="ArcGIS page folder, zip, GeoPackage, GeoJSON, shapefile, or CSV.")
    parser.add_argument("--top", type=int, default=12, help="How many common values to print per field.")
    parser.add_argument("--json", action="store_true", help="Print the profile as JSON.")
    args = parser.parse_args()
    try:
        report = profile_path(Path(args.path), top=args.top)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report), end="")


def profile_path(path: Path, *, top: int = 12) -> dict[str, object]:
    """Return field profiles for one saved source. The path is not resolved for display."""
    if top < 1:
        raise ValueError("--top must be at least 1")
    if not path.exists():
        raise ValueError(f"Missing source path: {path.as_posix()}")
    if path.is_symlink():
        raise ValueError(f"Refusing to profile a symbolic link: {path.as_posix()}")
    if path.is_dir():
        layers = [_profile_arcgis(path, top)]
    elif path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        layers = _profile_zip(path, top)
    else:
        layers = _profile_file(path, top, label=None)
    return {"path": path.as_posix(), "layers": layers}


def format_report(report: dict[str, object]) -> str:
    """Render a profile. Null, empty, and whitespace stay on separate lines."""
    lines = [f"path: {report['path']}"]
    layers = report["layers"]
    if not isinstance(layers, list):
        raise TypeError("Profile has no layer list")
    for layer in layers:
        lines.append("")
        lines.append(f"layer: {layer['name']} ({layer['kind']})")
        lines.append(f"rows: {layer['rows']}")
        expected = layer.get("snapshot_rows")
        if expected is not None and expected != layer["rows"]:
            lines.append(f"snapshot rows: {expected}")
        geometry = layer["geometry"]
        if geometry is None:
            lines.append("geometry: none")
        else:
            lines.append(
                "geometry: "
                f"{geometry['nonempty']} nonempty, {geometry['empty']} empty, "
                f"{geometry['null']} null, {geometry['unrecognized']} unrecognized"
            )
        for field in layer["fields"]:
            lines.append(
                f"field {field['name']}: null {field['null']}, empty {field['empty']}, "
                f"whitespace {field['whitespace']}, absent {field['absent']}, distinct {field['distinct']}"
            )
            for item in field["top"]:
                lines.append(f"  {item['count']:6d}  {item['repr']}")
    return "\n".join(lines) + "\n"


class _Column:
    def __init__(self) -> None:
        self.null = 0
        self.empty = 0
        self.whitespace = 0
        self.absent = 0
        self._counts: Counter[tuple[str, str]] = Counter()

    def add_absent(self) -> None:
        self.absent += 1

    def add(self, value: object) -> None:
        plain = _plain(value)
        if _is_null(plain):
            self.null += 1
            return
        if isinstance(plain, str) and plain == "":
            self.empty += 1
        elif isinstance(plain, str) and plain.strip() == "":
            self.whitespace += 1
        self._counts[_identity(plain)] += 1

    def as_dict(self, name: str, top: int) -> dict[str, object]:
        ranked = sorted(self._counts.items(), key=lambda item: (-item[1], item[0][1], item[0][0]))
        return {
            "name": name,
            "null": self.null,
            "empty": self.empty,
            "whitespace": self.whitespace,
            "absent": self.absent,
            "distinct": len(self._counts),
            "top": [{"repr": key[1], "count": count} for key, count in ranked[:top]],
        }


def _profile_arcgis(directory: Path, top: int) -> dict[str, object]:
    metadata_names = _metadata_fields(directory / "layer_metadata.json")
    names, expected = _page_names(directory)
    columns = {name: _Column() for name in metadata_names}
    geometry = {"null": 0, "empty": 0, "nonempty": 0, "unrecognized": 0}
    rows = 0
    for name in names:
        page_path = directory / name
        if page_path.parent != directory or not page_path.is_file():
            raise ValueError(f"Invalid ArcGIS page path: {name}")
        with gzip.open(page_path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise TypeError(f"ArcGIS page has no feature list: {name}")
        for index, feature in enumerate(features):
            if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
                raise TypeError(f"ArcGIS feature {index} in {name} has no attributes")
            attributes = feature["attributes"]
            for key in attributes:
                if key not in columns:
                    columns[key] = _Column()
                    columns[key].absent = rows
            seen = set(attributes)
            for key, column in columns.items():
                if key in seen:
                    column.add(attributes[key])
                else:
                    column.add_absent()
            geometry[_esri_kind(feature.get("geometry"))] += 1
            rows += 1
    return {
        "name": directory.name,
        "kind": "arcgis",
        "rows": rows,
        "snapshot_rows": expected,
        "geometry": geometry,
        "fields": [columns[name].as_dict(name, top) for name in sorted(columns)],
    }


def _profile_zip(path: Path, top: int) -> list[dict[str, object]]:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"Not a zip archive: {path.name}")
    with zipfile.ZipFile(path) as bundle:
        members = [name.replace("\\", "/") for name in bundle.namelist() if not name.endswith("/")]
    chosen = [member for member in members if _zip_kind(member) is not None]
    if not chosen:
        raise ValueError(f"No shapefile, GeoPackage, GeoJSON, or CSV member in {path.name}")
    layers: list[dict[str, object]] = []
    for member in chosen:
        with tempfile.TemporaryDirectory(prefix="utilitydata-profile-") as temp_name:
            extracted = materialize_archive_member(path, member, Path(temp_name))
            layers.extend(_profile_file(extracted, top, label=member))
    return layers


def _profile_file(path: Path, top: int, label: str | None) -> list[dict[str, object]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [_profile_csv(path, top, label or path.name)]
    if suffix not in _VECTOR_SUFFIXES:
        raise ValueError(f"No profiler for {path.name}")
    return _profile_vector(path, top, label, _VECTOR_SUFFIXES[suffix])


def _profile_csv(path: Path, top: int, label: str) -> dict[str, object]:
    columns: dict[str, _Column] = {}
    rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        csv.field_size_limit(32 * 1024 * 1024)
        reader = csv.reader(stream)
        headers = next(reader, [])
        if not headers or len(headers) != len(set(headers)) or any(not name for name in headers):
            raise ValueError(f"Invalid or duplicate CSV header: {label}")
        columns = {name: _Column() for name in headers}
        for line_number, row in enumerate(reader, start=2):
            if len(row) != len(headers):
                raise ValueError(f"Malformed CSV row {line_number} in {label}")
            for name, value in zip(headers, row, strict=True):
                columns[name].add(value)
            rows += 1
    return {
        "name": label,
        "kind": "csv",
        "rows": rows,
        "snapshot_rows": None,
        "geometry": None,
        "fields": [columns[name].as_dict(name, top) for name in headers],
    }


def _profile_vector(path: Path, top: int, label: str | None, kind: str) -> list[dict[str, object]]:
    single = path.suffix.lower() in {".geojson", ".json", ".shp"}
    if single:
        listed = [(None, None)]
    else:
        listed = [(str(name), str(geometry_type) if geometry_type is not None else None) for name, geometry_type in pyogrio.list_layers(path)]
        if not listed:
            raise ValueError(f"No layers in {label or path.name}")
    layers = []
    for layer_name, _geometry_type in listed:
        info = pyogrio.read_info(path, layer=layer_name)
        count = int(info["features"])
        if count < 0:
            raise ValueError(f"Unknown feature count for {label or path.name}")
        frame = pyogrio.read_dataframe(path, layer=layer_name, read_geometry=False)
        if len(frame) != count:
            raise ValueError(f"Feature count changed for {label or layer_name or path.name}")
        display = label or (str(layer_name) if layer_name is not None else path.name)
        if label and layer_name is not None and not single:
            display = f"{label}:{layer_name}"
        layers.append({
            "name": display,
            "kind": kind,
            "rows": count,
            "snapshot_rows": None,
            "geometry": _vector_geometry(path, layer_name, count, info.get("geometry_type"), display),
            "fields": _profile_frame(frame, top),
        })
    return layers


def _profile_frame(frame: pd.DataFrame, top: int) -> list[dict[str, object]]:
    fields = []
    for name in frame.columns:
        column = _Column()
        for value in frame[name].tolist():
            column.add(value)
        fields.append(column.as_dict(str(name), top))
    return fields


def _vector_geometry(path: Path, layer_name: str | None, count: int, geometry_type: object, label: str) -> dict[str, int] | None:
    if not geometry_type:
        return None
    counts = {"null": 0, "empty": 0, "nonempty": 0, "unrecognized": 0}
    for offset in range(0, count, _PAGE_CHUNK):
        width = min(_PAGE_CHUNK, count - offset)
        frame = pyogrio.read_dataframe(path, layer=layer_name, columns=[], skip_features=offset, max_features=width)
        if len(frame) != width:
            raise ValueError(f"Feature count changed for {label}")
        missing = frame.geometry.isna()
        counts["null"] += int(missing.sum())
        present = frame.geometry[~missing]
        empty = present.is_empty
        counts["empty"] += int(empty.sum())
        counts["nonempty"] += int((~empty).sum())
    return counts


def _page_names(directory: Path) -> tuple[list[str], int | None]:
    snapshot_path = directory / "snapshot.json"
    if not snapshot_path.is_file():
        names = sorted(path.name for path in directory.glob("page*.json.gz") if path.is_file())
        if not names:
            raise ValueError(f"No ArcGIS pages in {directory.name}")
        return names, None
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    pages = snapshot.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError(f"ArcGIS snapshot has no pages: {directory.name}")
    names = []
    expected = 0
    for page in pages:
        name = page.get("file") if isinstance(page, dict) else None
        count = page.get("features") if isinstance(page, dict) else None
        if not isinstance(name, str) or Path(name).name != name or not isinstance(count, int) or isinstance(count, bool):
            raise ValueError(f"Invalid ArcGIS snapshot page in {directory.name}")
        names.append(name)
        expected += count
    saved = sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file() and _is_page_name(path.name))
    if saved != sorted(names):
        raise ValueError(f"ArcGIS page inventory mismatch for {directory.name}")
    return names, expected


def _metadata_fields(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    metadata = json.loads(path.read_text(encoding="utf-8"))
    names = set()
    for field in metadata.get("fields", []) if isinstance(metadata, dict) else []:
        name = field.get("name") if isinstance(field, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _zip_kind(member: str) -> str | None:
    suffix = Path(member).suffix.lower()
    if suffix == ".csv":
        return "csv"
    return _VECTOR_SUFFIXES.get(suffix)


def _is_page_name(name: str) -> bool:
    folded = name.casefold()
    return folded.startswith("page") and folded.endswith(".json.gz")


def _esri_kind(geometry: object) -> str:
    if geometry is None:
        return "null"
    if not isinstance(geometry, dict):
        return "unrecognized"
    if "x" in geometry and "y" in geometry:
        if geometry["x"] is None or geometry["y"] is None:
            return "empty"
        return "nonempty"
    for key in ("rings", "paths", "points"):
        if key not in geometry:
            continue
        parts = geometry[key]
        if not isinstance(parts, list) or not parts:
            return "empty"
        if key == "points":
            return "nonempty"
        if any(part for part in parts):
            return "nonempty"
        return "empty"
    return "unrecognized"


def _plain(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _is_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes, bool, int)):
        return False
    if isinstance(value, float):
        return math.isnan(value)
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _identity(value: object) -> tuple[str, str]:
    if isinstance(value, bool):
        return ("bool", repr(value))
    if isinstance(value, int):
        return ("int", repr(value))
    if isinstance(value, float):
        return ("float", repr(value))
    if isinstance(value, str):
        return ("str", repr(value))
    return (type(value).__name__, repr(value))


if __name__ == "__main__":
    main()
