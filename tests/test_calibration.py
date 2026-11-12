"""Calibration scores labels and refuses to treat an unmeasured flag as true."""

from pathlib import Path

import pandas as pd
import pytest

from utilitydata.release import calibration
from utilitydata.release.calibration import require_measurement_record, score_labels


def test_score_refuses_a_missing_labeller_and_reports_an_interval():
    with pytest.raises(ValueError, match="no labeller"):
        score_labels(pd.DataFrame([{
            "method": "exact_name_state",
            "label": "correct",
            "labelled_by": "",
            "labelled_on": "2026-11-12",
            "note": "",
        }]))
    scored = score_labels(pd.DataFrame([
        {"method": "exact_name_state", "label": "correct", "labelled_by": "Cole", "labelled_on": "2026-11-12", "note": ""},
        {"method": "exact_name_state", "label": "incorrect", "labelled_by": "Cole", "labelled_on": "2026-11-12", "note": ""},
    ]))
    assert scored.iloc[0]["precision"] == 0.5
    assert scored.iloc[0]["interval_low"] < 0.5 < scored.iloc[0]["interval_high"]


def test_a_true_flag_without_a_record_is_refused(tmp_path: Path):
    require_measurement_record(tmp_path / "missing.csv")
    record = tmp_path / "measurements.csv"
    record.write_text("flag,labelled_by,precision\n", encoding="utf-8")
    original = calibration._FLAGS["GAS_NAME_KEYS_CALIBRATED"]
    calibration._FLAGS["GAS_NAME_KEYS_CALIBRATED"] = True
    try:
        with pytest.raises(ValueError, match="GAS_NAME_KEYS_CALIBRATED"):
            require_measurement_record(record)
    finally:
        calibration._FLAGS["GAS_NAME_KEYS_CALIBRATED"] = original
