"""Typed Safe Drinking Water Act tables.

Every archived row is kept, including inactive systems. Empty CSV fields become
null. A value that does not match its column type raises instead of being
dropped or coerced to null.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

TABLE_NAMES = {
    "SDWA_PUB_WATER_SYSTEMS.csv": "sdwa_public_water_system",
    "SDWA_GEOGRAPHIC_AREAS.csv": "sdwa_geographic_area",
    "SDWA_FACILITIES.csv": "sdwa_facility",
    "SDWA_VIOLATIONS_ENFORCEMENT.csv": "sdwa_violation",
}
SYSTEMS_MEMBER = "SDWA_PUB_WATER_SYSTEMS.csv"
_INTEGER_TEXT = re.compile(r"^-?\d+(?:\.0+)?$")
_CHUNK_ROWS = 100_000
# EPA uses this token for an open-ended compliance period. It is preserved beside the typed date.
_DATE_SENTINELS = frozenset({"--->"})


def load_sdwa_tables(
    archive: Path,
    required_columns: Mapping[str, set[str]],
    output_dir: Path,
    *,
    pwsid_column: str,
) -> tuple[dict[str, int], Counter[str]]:
    """Write one typed parquet for each declared CSV and count frozen PWSIDs.

    ``required_columns`` maps an archive member name to the source columns the
    registry names. A missing name raises. Extra columns are kept.
    """
    unknown = sorted(set(required_columns) - set(TABLE_NAMES))
    if unknown:
        raise ValueError(f"No typed SDWA table is declared for {', '.join(unknown)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    identifier_counts: Counter[str] = Counter()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        for member, needed in required_columns.items():
            if member not in names:
                raise ValueError(f"Missing archive member {member}")
            table_name = TABLE_NAMES[member]
            written, found = _write_member(
                bundle,
                member,
                needed,
                output_dir / f"{table_name}.parquet",
                count_column=pwsid_column if member == SYSTEMS_MEMBER else None,
            )
            counts[table_name] = written
            identifier_counts.update(found)
            print(f"wrote {table_name}: {written} rows", flush=True)
    return counts, identifier_counts


def _write_member(
    bundle: zipfile.ZipFile,
    member: str,
    required: set[str],
    destination: Path,
    *,
    count_column: str | None,
) -> tuple[int, Counter[str]]:
    counts: Counter[str] = Counter()
    written = 0
    holder = _Writer()
    try:
        with bundle.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, [])
            if not header or len(header) != len(set(header)) or any(not name for name in header):
                raise ValueError(f"Invalid or duplicate CSV header for {member}")
            missing = sorted(required - set(header))
            if missing:
                raise ValueError(f"Missing columns in {member}: {', '.join(missing)}")
            kinds = {name: _column_kind(name) for name in header}
            batch: list[list[str]] = []
            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    raise ValueError(f"Malformed CSV row {line_number} in {member}")
                batch.append(row)
                if len(batch) >= _CHUNK_ROWS:
                    written += _flush(batch, header, kinds, destination, count_column, counts, holder)
                    batch = []
                    print(f"{member}: {written} rows", flush=True)
            if batch:
                written += _flush(batch, header, kinds, destination, count_column, counts, holder)
            if holder.writer is None:
                _flush([], header, kinds, destination, count_column, counts, holder)
    finally:
        if holder.writer is not None:
            holder.writer.close()
    return written, counts


class _Writer:
    def __init__(self) -> None:
        self.writer: pq.ParquetWriter | None = None


def _flush(
    batch: list[list[str]],
    header: list[str],
    kinds: dict[str, str],
    destination: Path,
    count_column: str | None,
    counts: Counter[str],
    holder: _Writer,
) -> int:
    frame = pd.DataFrame(batch, columns=header, dtype="string")
    if count_column is not None:
        if count_column not in frame.columns:
            raise ValueError(f"PWSID column {count_column} is missing")
        trimmed = frame[count_column].fillna("").str.strip()
        counts.update(value for value in trimmed.tolist() if value)
        frame[count_column] = trimmed.mask(trimmed.eq(""), pd.NA)
    arrays: list[pa.Array] = []
    fields: list[pa.Field] = []
    for name in header:
        kind = kinds[name]
        series = frame[name] if name in frame else pd.Series(dtype="string")
        if kind == "date":
            values, sentinels = _dates(series, name)
            arrays.append(pa.array(values, type=pa.date32(), from_pandas=True))
            fields.append(pa.field(name, pa.date32()))
            arrays.append(pa.array(sentinels, type=pa.string(), from_pandas=True))
            fields.append(pa.field(f"{name}_unparsed", pa.string()))
        elif kind == "int":
            values = _integers(series, name)
            arrays.append(pa.array(values, type=pa.int64(), from_pandas=True))
            fields.append(pa.field(name, pa.int64()))
        else:
            text = series.mask(series.fillna("").eq(""), pd.NA)
            arrays.append(pa.array(text, type=pa.string(), from_pandas=True))
            fields.append(pa.field(name, pa.string()))
    table = pa.Table.from_arrays(arrays, schema=pa.schema(fields))
    if holder.writer is None:
        holder.writer = pq.ParquetWriter(destination, table.schema, compression="snappy")
    holder.writer.write_table(table)
    return len(batch)


def _column_kind(name: str) -> str:
    if name.endswith("_DATE"):
        return "date"
    if name.endswith(("_COUNT", "_CNT")):
        return "int"
    return "string"


def _dates(series: pd.Series, name: str) -> tuple[list[date | None], list[str | None]]:
    blank = series.isna() | series.eq("")
    sentinel = series.isin(_DATE_SENTINELS)
    parsed = pd.to_datetime(series.mask(blank | sentinel), format="%m/%d/%Y", errors="coerce")
    invalid = ~(blank | sentinel) & parsed.isna()
    if bool(invalid.any()):
        raise ValueError(f"Unrecognized date {series[invalid].iloc[0]!r} in {name}")
    values: list[date | None] = []
    sentinels: list[str | None] = []
    for is_blank, is_sentinel, raw, stamp in zip(blank.tolist(), sentinel.tolist(), series.tolist(), parsed.tolist(), strict=True):
        values.append(None if is_blank or is_sentinel or pd.isna(stamp) else stamp.date())
        sentinels.append(str(raw) if is_sentinel else None)
    return values, sentinels


def _integers(series: pd.Series, name: str) -> pd.Series:
    blank = series.isna() | series.eq("")
    present = series[~blank]
    if len(present) and not bool(present.str.fullmatch(_INTEGER_TEXT).all()):
        bad = present[~present.str.fullmatch(_INTEGER_TEXT)].iloc[0]
        raise ValueError(f"Unrecognized integer {bad!r} in {name}")
    numbers = pd.to_numeric(series.mask(blank), errors="coerce")
    if bool((~blank & numbers.isna()).any()):
        raise ValueError(f"Unrecognized integer in {name}")
    if bool((numbers.notna() & (numbers != numbers.round())).any()):
        raise ValueError(f"Non-integral number in {name}")
    return numbers.round().astype("Int64")
