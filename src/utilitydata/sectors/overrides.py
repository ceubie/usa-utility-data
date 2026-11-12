"""Replace a sector decision from the shared override file.

Each sector calls ``apply_match_overrides``. An assertion that belongs to
another sector is left unused. The assemble step fails when any override row
was used by no sector. Facility pairs use a separate file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from utilitydata.core.schema import OVERRIDE_COLUMNS
from utilitydata.core.text import require_columns

FACILITY_OVERRIDE_COLUMNS = (
    "facility_id_a",
    "facility_id_b",
    "decided_by",
    "notes",
)


def load_match_overrides(path: Path) -> pd.DataFrame:
    """Read the zone override file. A missing file is an error, not an empty guess."""
    if not path.is_file():
        raise ValueError(f"Match overrides are missing: {path.as_posix()}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    require_columns(frame, OVERRIDE_COLUMNS, "match overrides")
    if bool(frame["assertion_id"].duplicated().any()):
        raise ValueError("Match overrides repeat an assertion id")
    return frame.loc[:, list(OVERRIDE_COLUMNS)].copy()


def apply_match_overrides(
    decisions: pd.DataFrame,
    systems: pd.DataFrame,
    overrides: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace decisions named in this sector and return the override rows used.

    ``method`` becomes ``override``. ``decided_by`` and the note come from the
    override file. The note is stored on ``evidence``. An assertion this sector
    does not have is not used. An unknown system or a repeated assertion raises.
    """
    require_columns(decisions, ("assertion_id", "system_id", "method", "decided_by", "evidence"), "decisions")
    require_columns(systems, ("system_id",), "systems")
    require_columns(overrides, OVERRIDE_COLUMNS, "match overrides")
    if bool(overrides["assertion_id"].duplicated().any()):
        raise ValueError("Match overrides repeat an assertion id")
    if overrides.empty or decisions.empty:
        return decisions.copy(), overrides.iloc[0:0].copy()
    known_assertions = set(decisions["assertion_id"].astype(str))
    applicable = overrides.loc[overrides["assertion_id"].astype(str).isin(known_assertions)].copy()
    if applicable.empty:
        return decisions.copy(), applicable
    known_systems = set(systems["system_id"].dropna().astype(str))
    unknown = sorted(set(applicable["system_id"].astype(str)) - known_systems)
    if unknown:
        raise ValueError(f"Match override names an unknown system: {unknown[0]}")
    notes = applicable.set_index(applicable["assertion_id"].astype(str), drop=False)
    updated = decisions.copy()
    ids = updated["assertion_id"].astype(str)
    mask = ids.isin(set(notes.index))
    updated.loc[mask, "system_id"] = ids.loc[mask].map(notes["system_id"]).to_numpy()
    updated.loc[mask, "method"] = "override"
    decided = ids.loc[mask].map(notes["decided_by"])
    updated.loc[mask, "decided_by"] = decided.where(decided.ne(""), "override").to_numpy()
    updated.loc[mask, "evidence"] = ids.loc[mask].map(notes["notes"]).to_numpy()
    return updated, applicable.reset_index(drop=True)


def require_overrides_used(overrides: pd.DataFrame, used: list[pd.DataFrame]) -> None:
    """Fail when an override row was not applied by any sector."""
    require_columns(overrides, OVERRIDE_COLUMNS, "match overrides")
    if overrides.empty:
        return
    consumed: set[str] = set()
    for frame in used:
        require_columns(frame, ("assertion_id",), "used overrides")
        consumed.update(frame["assertion_id"].dropna().astype(str))
    missing = sorted(set(overrides["assertion_id"].astype(str)) - consumed)
    if missing:
        raise ValueError(f"Match override matched no sector: {missing[0]}")


def write_used_overrides(path: Path, used: pd.DataFrame) -> None:
    """Record the override rows one sector applied, including a header when none applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = used.loc[:, ["assertion_id"]] if not used.empty else pd.DataFrame(columns=["assertion_id"])
    frame.to_csv(path, index=False)


def load_facility_overrides(path: Path) -> pd.DataFrame:
    """Read facility-pair overrides. The file is created empty when absent."""
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=list(FACILITY_OVERRIDE_COLUMNS)).to_csv(path, index=False)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    require_columns(frame, FACILITY_OVERRIDE_COLUMNS, "facility match overrides")
    pair = [tuple(sorted((left, right))) for left, right in zip(frame["facility_id_a"], frame["facility_id_b"], strict=True)]
    if len(pair) != len(set(pair)):
        raise ValueError("Facility match overrides repeat a pair")
    return frame.loc[:, list(FACILITY_OVERRIDE_COLUMNS)].copy()


_FACILITY_DECISION_COLUMNS = (
    "facility_id_a",
    "facility_id_b",
    "sector",
    "source_id_a",
    "source_id_b",
    "distance_m",
    "name_score",
    "decision",
    "reason",
)


def apply_facility_overrides(
    decisions: pd.DataFrame,
    facilities: pd.DataFrame,
    overrides: pd.DataFrame,
) -> pd.DataFrame:
    """Set a facility pair to an override match. An unknown facility raises."""
    require_columns(decisions, _FACILITY_DECISION_COLUMNS, "facility decisions")
    require_columns(facilities, ("facility_id", "sector", "source_id"), "facilities")
    require_columns(overrides, FACILITY_OVERRIDE_COLUMNS, "facility match overrides")
    if overrides.empty:
        return decisions.copy()
    if bool(facilities["facility_id"].duplicated().any()):
        raise ValueError("Facility ids are not unique")
    known = facilities.set_index(facilities["facility_id"].astype(str))
    named = [*overrides["facility_id_a"].astype(str), *overrides["facility_id_b"].astype(str)]
    unknown = sorted({value for value in named if value not in known.index})
    if unknown:
        raise ValueError(f"Facility override names an unknown facility: {unknown[0]}")
    updated = decisions.copy()
    for record in overrides.itertuples(index=False):
        left = str(record.facility_id_a)
        right = str(record.facility_id_b)
        pair = updated["facility_id_a"].astype(str) + "\t" + updated["facility_id_b"].astype(str)
        mask = pair.isin({f"{left}\t{right}", f"{right}\t{left}"})
        if bool(mask.any()):
            updated.loc[mask, "decision"] = "match"
            updated.loc[mask, "reason"] = "override"
            continue
        updated = pd.concat(
            [
                updated,
                pd.DataFrame([{
                    "facility_id_a": left,
                    "facility_id_b": right,
                    "sector": known.loc[left, "sector"],
                    "source_id_a": known.loc[left, "source_id"],
                    "source_id_b": known.loc[right, "source_id"],
                    "distance_m": None,
                    "name_score": None,
                    "decision": "match",
                    "reason": "override",
                }]),
            ],
            ignore_index=True,
        )
    return updated.loc[:, list(_FACILITY_DECISION_COLUMNS)]
