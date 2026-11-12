"""Measure tabular files for the refresh gate."""

import csv
import io
import zipfile
from collections.abc import Mapping

from utilitydata.bronze.gate import Measurement
from utilitydata.registry import Source, mapped_field_names

_SPATIAL = frozenset({"service_area", "facility", "network"})


def measure_tabular(source: Source, files: Mapping[str, bytes], *, mapped_fields: frozenset[str]) -> Measurement:
    """Count rows and headers. A missing named column is left for the gate to reject."""
    if len(files) != 1:
        raise ValueError(f"{source.source_id} measurement needs exactly one file")
    name, content = next(iter(files.items()))
    if name.lower().endswith(".csv"):
        count, header = _csv_table(content, name)
        return Measurement(count, None, header, 0, False)
    if name.lower().endswith(".zip") or zipfile.is_zipfile(io.BytesIO(content)):
        return _zip_table(source, content, mapped_fields)
    if mapped_fields:
        raise ValueError(f"Cannot measure {name} for the refresh gate")
    return Measurement(None, None, frozenset(), 0, False)


def _zip_table(source: Source, content: bytes, mapped_fields: frozenset[str]) -> Measurement:
    found = set(mapped_fields)
    total = 0
    saw_csv = False
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        names = set(bundle.namelist())
        for layer in source.layers:
            needed = mapped_field_names(layer)
            member = layer.layer
            if member not in names:
                raise ValueError(f"Missing archive member {member}")
            if layer.grain in _SPATIAL and not member.lower().endswith(".csv"):
                raise ValueError(f"Cannot measure spatial area for {source.source_id}.{member}")
            if not member.lower().endswith(".csv"):
                if needed:
                    raise ValueError(f"Cannot measure mapped fields for {source.source_id}.{member}")
                continue
            count, header = _csv_table(bundle.read(member), member)
            saw_csv = True
            total += count
            found -= needed - header
    if not saw_csv and mapped_fields:
        raise ValueError(f"Cannot measure {source.source_id} for the refresh gate")
    return Measurement(total if saw_csv else None, None, frozenset(found), 0, False)


def _csv_table(content: bytes, label: str) -> tuple[int, frozenset[str]]:
    with io.TextIOWrapper(io.BytesIO(content), encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if not header or len(header) != len(set(header)) or any(name == "" for name in header):
            raise ValueError(f"CSV header is missing or duplicated: {label}")
        count = 0
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"CSV row does not match the header: {label}")
            count += 1
    return count, frozenset(header)
