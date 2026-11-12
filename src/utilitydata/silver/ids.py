"""Public water system identifier rules for Silver.

A standard identifier is two letters or digits followed by seven digits. A
nine-character value is never given another prefix. A seven-digit state number
is prefixed only when the registry entry says ``state_prefix_7``. A
nine-character alphanumeric value that is not standard is a federal identifier
only when it occurs once in the frozen SDWIS identifier list.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

STANDARD_PWSID = re.compile(r"^[A-Za-z0-9]{2}[0-9]{7}$")
NINE_CHARACTER_PWSID = re.compile(r"^[A-Za-z0-9]{9}$")
SEVEN_DIGITS = re.compile(r"^[0-9]{7}$")


@dataclass(frozen=True)
class PwsidResult:
    """One identifier decision. ``federal_id`` is set only when the rules accept it."""

    raw: str | None
    federal_id: str | None
    exception: bool
    review: bool
    reason: str | None
    candidates: tuple[str, ...]


def normalize_pwsid(
    value: object,
    *,
    state_prefix_7: bool,
    state: str | None,
    sdwis_counts: Mapping[str, int],
) -> PwsidResult:
    """Trim surrounding whitespace and apply the registry identifier rules.

    Interior characters are not rewritten. A composite value that contains a
    semicolon stays raw, with one candidate per piece, and receives no federal
    identifier.
    """
    text = identifier_text(value)
    if text is None:
        return PwsidResult(None, None, False, True, "missing_pwsid", ())
    if ";" in text:
        candidates = tuple(part.strip() for part in text.split(";") if part.strip())
        return PwsidResult(text, None, False, True, "multiple_identifiers", candidates)
    if STANDARD_PWSID.fullmatch(text):
        return PwsidResult(text, text, False, False, None, (text,))
    if state_prefix_7 and SEVEN_DIGITS.fullmatch(text):
        if state is None or not re.fullmatch(r"[A-Z]{2}", state):
            return PwsidResult(text, None, False, True, "missing_state_for_pwsid", (text,))
        return PwsidResult(text, f"{state}{text}", False, False, None, (text,))
    if NINE_CHARACTER_PWSID.fullmatch(text):
        found = int(sdwis_counts.get(text, 0))
        if found == 1:
            return PwsidResult(text, text, True, False, None, (text,))
        reason = "nonunique_sdwis_match" if found > 1 else "unmatched_pwsid"
        return PwsidResult(text, None, False, True, reason, (text,))
    return PwsidResult(text, None, False, True, "unmatched_pwsid", (text,))


def identifier_text(value: object) -> str | None:
    """Return a trimmed identifier, preserving interior characters and leading zeroes."""
    if _is_null(value) or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if float(value).is_integer():
            return str(int(value))
        text = str(value).strip()
        return text or None
    text = str(value).strip()
    return text or None


def _is_null(value: object) -> bool:
    if value is None or isinstance(value, str):
        return value is None
    return bool(pd.isna(value))
