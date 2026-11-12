"""Stable PHMSA system ids and same-state name links."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from utilitydata.core.config import GAS_NAME_KEYS_CALIBRATED
from utilitydata.core.text import core_name_key, legal_form_key
from utilitydata.registry import STATES

# Name comparisons, strictest first. Each is a method recorded on the decision.
NAME_TIERS: tuple[tuple[str, Callable[[object], str | None]], ...] = (
    ("exact_name_state", lambda value: value if isinstance(value, str) and value else None),
    ("legal_form_name_state", legal_form_key),
    ("core_name_state", core_name_key),
)


def phmsa_system_id(operator_id: int, state: str) -> str:
    """Return the system id for one operator in one state.

    The same operator in another state is a different system. The id does not
    depend on a row position or a report date.
    """
    if isinstance(operator_id, bool) or not isinstance(operator_id, int):
        raise TypeError("PHMSA operator id must be an integer")
    if state not in STATES:
        raise ValueError(f"PHMSA system state is not a known code: {state}")
    return f"SYS_PHMSA_{operator_id}_{state}"


class StateNameIndex:
    """Systems indexed by state and name key, built once for many lookups."""

    def __init__(self, candidates: pd.DataFrame) -> None:
        if GAS_NAME_KEYS_CALIBRATED:
            raise ValueError("Gas name keys are marked calibrated without a recorded measurement")
        missing = [name for name in ("name_norm", "state", "system_id") if name not in candidates.columns]
        if missing:
            raise ValueError("Name candidates need name_norm, state, and system_id")
        self._tiers: list[tuple[str, Callable[[object], str | None], dict[tuple[str, str], set[str]]]] = []
        for method, key in NAME_TIERS:
            index: dict[tuple[str, str], set[str]] = {}
            for state, name, system_id in zip(candidates["state"], candidates["name_norm"], candidates["system_id"], strict=True):
                value = key(name)
                if value is None or state is None or pd.isna(state):
                    continue
                index.setdefault((str(state), value), set()).add(str(system_id))
            self._tiers.append((method, key, index))

    def match(self, name: str | None, state: str | None) -> tuple[str | None, str]:
        """Link a name to the one system in the same state that shares a key.

        The strictest comparison that finds a system decides. Two systems
        sharing a key in the state is ambiguous and is not linked. A system in
        another state is never eligible.
        """
        if not name or not state:
            return None, "missing_name_or_state"
        for method, key, index in self._tiers:
            value = key(name)
            if value is None:
                continue
            found = index.get((state, value), set())
            if len(found) == 1:
                return next(iter(found)), method
            if len(found) > 1:
                return None, "ambiguous_name_in_state"
        return None, "no_name_in_state"


def match_name_within_state(
    name: str | None,
    state: str | None,
    candidates: pd.DataFrame,
) -> tuple[str | None, str]:
    """Link one name to one candidate in the same state. See ``StateNameIndex.match``."""
    return StateNameIndex(candidates).match(name, state)
