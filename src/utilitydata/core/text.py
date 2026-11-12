"""Small text and frame helpers shared by the core build."""

import re
from collections.abc import Sequence

import pandas as pd

from utilitydata.core.config import NAME_GENERIC_SERVICE_TOKENS, NAME_LEGAL_FORM_TOKENS

_NOT_WORD = re.compile(r"[^0-9a-z ]+")


def require_columns(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    """Raise when a named column is absent. Extra columns are left in place."""
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def normalize_name(value: object) -> str | None:
    """Collapse whitespace and casefold. Interior punctuation stays put."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if not isinstance(value, str):
        if pd.isna(value):
            return None
        text = str(value)
    else:
        text = value
    collapsed = " ".join(text.split())
    return collapsed.casefold() if collapsed else None


def legal_form_key(value: object) -> str | None:
    """Return the name without punctuation or legal-form words such as Inc and Co.

    Word order is kept. ``&`` reads as ``and``. A name made only of removed
    words has no key.
    """
    tokens = _name_tokens(value)
    kept = [token for token in tokens if token not in NAME_LEGAL_FORM_TOKENS]
    return " ".join(kept) or None


def core_name_key(value: object) -> str | None:
    """Return the distinguishing words of a utility name, sorted.

    Legal-form words and generic service words (City, Of, Gas, Dept, System)
    are removed, so ``BAINBRIDGE, CITY OF`` and ``Bainbridge Gas Dept, City
    Of`` share a key. The caller must require the key to be unique in a state.
    """
    tokens = _name_tokens(value)
    kept = sorted(
        token
        for token in tokens
        if token not in NAME_LEGAL_FORM_TOKENS and token not in NAME_GENERIC_SERVICE_TOKENS
    )
    return " ".join(kept) or None


def _name_tokens(value: object) -> list[str]:
    text = normalize_name(value)
    if text is None:
        return []
    return _NOT_WORD.sub(" ", text.replace("&", " and ")).split()


def as_string(series: pd.Series) -> pd.Series:
    """Return a string series whose blanks are missing."""
    text = series.astype("string").str.strip()
    return text.mask(text.eq(""), pd.NA)


def state_code(series: pd.Series) -> pd.Series:
    """Normalize a state or province code without changing its letters."""
    return as_string(series).str.upper()


def is_missing(value: object) -> bool:
    """Return whether a scalar is missing. Strings are missing only when None."""
    if value is None:
        return True
    if isinstance(value, str):
        return False
    return bool(pd.isna(value))
