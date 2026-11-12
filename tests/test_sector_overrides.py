"""Override rows replace a decision and are reconciled across sectors."""

from pathlib import Path

import pandas as pd
import pytest

from utilitydata.sectors.overrides import (
    apply_facility_overrides,
    apply_match_overrides,
    load_facility_overrides,
    load_match_overrides,
    require_overrides_used,
)


def _decisions() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "assertion_id": "A1",
            "system_id": "SYS_OLD",
            "method": "exact_name_state",
            "score": 100.0,
            "evidence": "before",
            "decided_by": "rule",
            "release": "2026-Q4",
        }
    ])


def _systems() -> pd.DataFrame:
    return pd.DataFrame([{"system_id": "SYS_NEW"}, {"system_id": "SYS_OLD"}])


def test_override_replaces_the_decision_and_records_the_note(tmp_path: Path):
    path = tmp_path / "match_overrides.csv"
    path.write_text(
        "assertion_id,system_id,decided_by,notes\nA1,SYS_NEW,Cole,measured link\nA2,SYS_OTHER,Cole,other sector\n",
        encoding="utf-8",
    )
    updated, used = apply_match_overrides(_decisions(), _systems(), load_match_overrides(path))
    row = updated.iloc[0]
    assert row["system_id"] == "SYS_NEW"
    assert row["method"] == "override"
    assert row["decided_by"] == "Cole"
    assert row["evidence"] == "measured link"
    assert list(used["assertion_id"]) == ["A1"]


def test_unknown_system_and_duplicate_assertion_raise(tmp_path: Path):
    overrides = pd.DataFrame([
        {"assertion_id": "A1", "system_id": "SYS_MISSING", "decided_by": "Cole", "notes": "no"},
    ])
    with pytest.raises(ValueError, match="unknown system"):
        apply_match_overrides(_decisions(), _systems(), overrides)
    duplicated = pd.DataFrame([
        {"assertion_id": "A1", "system_id": "SYS_NEW", "decided_by": "Cole", "notes": "one"},
        {"assertion_id": "A1", "system_id": "SYS_OLD", "decided_by": "Cole", "notes": "two"},
    ])
    with pytest.raises(ValueError, match="repeat an assertion"):
        apply_match_overrides(_decisions(), _systems(), duplicated)


def test_assemble_fails_when_an_override_matches_no_sector():
    overrides = pd.DataFrame([
        {"assertion_id": "A1", "system_id": "SYS_NEW", "decided_by": "Cole", "notes": "used"},
        {"assertion_id": "A9", "system_id": "SYS_NEW", "decided_by": "Cole", "notes": "unused"},
    ])
    used = pd.DataFrame({"assertion_id": ["A1"]})
    with pytest.raises(ValueError, match="matched no sector"):
        require_overrides_used(overrides, [used])
    require_overrides_used(overrides.iloc[:1], [used])


def test_facility_pair_override_sets_a_match(tmp_path: Path):
    path = tmp_path / "facility_match_overrides.csv"
    path.write_text(
        "facility_id_a,facility_id_b,decided_by,notes\nFAC_B,FAC_A,Cole,same plant\n",
        encoding="utf-8",
    )
    facilities = pd.DataFrame([
        {"facility_id": "FAC_A", "sector": "electric", "source_id": "left"},
        {"facility_id": "FAC_B", "sector": "electric", "source_id": "right"},
    ])
    decisions = pd.DataFrame([{
        "facility_id_a": "FAC_A",
        "facility_id_b": "FAC_B",
        "sector": "electric",
        "source_id_a": "left",
        "source_id_b": "right",
        "distance_m": 10.0,
        "name_score": 40.0,
        "decision": "review",
        "reason": "name_below_similarity",
    }])
    updated = apply_facility_overrides(decisions, facilities, load_facility_overrides(path))
    assert updated.iloc[0]["decision"] == "match"
    assert updated.iloc[0]["reason"] == "override"
    with pytest.raises(ValueError, match="unknown facility"):
        apply_facility_overrides(
            decisions,
            facilities,
            pd.DataFrame([{
                "facility_id_a": "FAC_A",
                "facility_id_b": "FAC_MISSING",
                "decided_by": "Cole",
                "notes": "no",
            }]),
        )
