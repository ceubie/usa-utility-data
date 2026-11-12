"""Sample and score hand labels. This module never changes a calibrated flag."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from utilitydata.core.config import (
    ELECTRIC_THRESHOLDS_CALIBRATED,
    FACILITY_THRESHOLDS_CALIBRATED,
    GAS_NAME_KEYS_CALIBRATED,
    MATCH_SAMPLE_SEED,
    THRESHOLDS_CALIBRATED,
    WASTEWATER_THRESHOLDS_CALIBRATED,
)
from utilitydata.core.text import require_columns

LABEL_COLUMNS = ("method", "label", "labelled_by", "labelled_on", "note")
_FLAGS = {
    "THRESHOLDS_CALIBRATED": THRESHOLDS_CALIBRATED,
    "ELECTRIC_THRESHOLDS_CALIBRATED": ELECTRIC_THRESHOLDS_CALIBRATED,
    "WASTEWATER_THRESHOLDS_CALIBRATED": WASTEWATER_THRESHOLDS_CALIBRATED,
    "GAS_NAME_KEYS_CALIBRATED": GAS_NAME_KEYS_CALIBRATED,
    "FACILITY_THRESHOLDS_CALIBRATED": FACILITY_THRESHOLDS_CALIBRATED,
}
_Z = 1.96


def require_measurement_record(record_path: Path) -> None:
    """A true calibrated flag needs a committed measurement row. A false flag does not."""
    recorded = set()
    if record_path.is_file():
        frame = pd.read_csv(record_path, dtype=str, keep_default_na=False)
        require_columns(frame, ("flag", "labelled_by", "precision"), "calibration record")
        recorded = set(frame.loc[frame["labelled_by"].ne("") & frame["precision"].ne(""), "flag"])
    for name, value in _FLAGS.items():
        if value and name not in recorded:
            raise ValueError(f"{name} is true without a committed measurement record")


def score_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Precision and a Wilson interval for each method. A row without a labeller is refused."""
    require_columns(frame, LABEL_COLUMNS, "calibration labels")
    missing = frame["labelled_by"].isna() | frame["labelled_by"].astype(str).str.strip().eq("")
    if bool(missing.any()):
        raise ValueError("A calibration row has no labeller")
    labels = frame["label"].astype(str).str.strip().str.casefold()
    unknown = sorted(set(labels) - {"correct", "incorrect"})
    if unknown:
        raise ValueError(f"A calibration label is not correct or incorrect: {unknown[0]}")
    rows = []
    for method, group in frame.groupby(frame["method"].astype(str), sort=True):
        group_labels = labels.loc[group.index]
        correct = int(group_labels.eq("correct").sum())
        total = len(group)
        low, high = _wilson(correct, total)
        rows.append({
            "method": method,
            "correct": correct,
            "rows": total,
            "precision": correct / total,
            "interval_low": low,
            "interval_high": high,
        })
    return pd.DataFrame(rows)


def sample_rows(frame: pd.DataFrame, *, method_column: str, size: int, seed: int = MATCH_SAMPLE_SEED) -> pd.DataFrame:
    """Draw a seeded sample stratified by method. The rows stay unlabelled."""
    require_columns(frame, (method_column,), "calibration sample")
    if size < 1:
        raise ValueError("Sample size must be at least 1")
    if frame.empty:
        return frame.copy()
    pieces = []
    methods = sorted(frame[method_column].astype(str).unique())
    per_method = max(1, size // len(methods))
    for method in methods:
        group = frame.loc[frame[method_column].astype(str).eq(method)]
        take = min(per_method, len(group))
        pieces.append(group.sample(n=take, random_state=seed))
    sampled = pd.concat(pieces, ignore_index=True)
    if len(sampled) > size:
        sampled = sampled.sample(n=size, random_state=seed).reset_index(drop=True)
    for column in ("label", "labelled_by", "labelled_on", "note"):
        if column not in sampled.columns:
            sampled[column] = pd.NA
    return sampled


def _wilson(correct: int, total: int) -> tuple[float, float]:
    if total == 0:
        raise ValueError("Precision needs at least one labelled row")
    proportion = correct / total
    denominator = 1 + _Z * _Z / total
    centre = proportion + _Z * _Z / (2 * total)
    margin = _Z * math.sqrt(proportion * (1 - proportion) / total + _Z * _Z / (4 * total * total))
    return max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)
