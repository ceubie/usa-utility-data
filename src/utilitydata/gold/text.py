"""Name keys used by search and by Safe Drinking Water Act geography."""

import re
import unicodedata

from utilitydata.core.text import is_missing

_COUNTY_SUFFIXES = (
    "census area",
    "municipality",
    "borough",
    "parish",
    "island",
    "county",
    "city",
)
_PAREN_STATE = re.compile(r"\(([A-Za-z]{2})\)\s*$")
_DASH_STATE = re.compile(r"[-–]\s*\(([A-Za-z]{2})\)\s*$|[-–]\s*([A-Za-z]{2})\s*$")


def _plain(value: object) -> str | None:
    if is_missing(value):
        return None
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^0-9A-Za-z]+", " ", text).casefold()
    text = " ".join(text.split())
    return text or None


def county_name_key(value: object) -> str | None:
    """Compare county names after dropping a trailing jurisdiction word."""
    text = _plain(value)
    if text is None:
        return None
    changed = True
    while changed and text:
        changed = False
        for suffix in _COUNTY_SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return text or None


def place_name_key(value: object) -> str | None:
    """Compare place and city names without changing tokens."""
    return _plain(value)


def search_key(value: object, *, state_codes: set[str]) -> str | None:
    """Return the search key, keeping a punctuation-only label as its folded text."""
    key = search_norm(value, state_codes=state_codes)
    if key:
        return key
    if is_missing(value):
        return None
    fallback = " ".join(str(value).split()).casefold()
    return fallback or None


def search_norm(value: object, *, state_codes: set[str]) -> str | None:
    """Fold a display name so the two North St. Paul spellings share a key.

    A leading "city of" is removed. A two-letter state in a trailing parenthesis
    is removed when it is one of ``state_codes``. Interior tokens, including
    "st", stay in place.
    """
    if is_missing(value):
        return None
    raw = str(value).strip()
    folded = _plain(raw)
    if folded is None:
        return None
    if folded.startswith("city of "):
        folded = folded[len("city of "):].strip()
    state = _trailing_state(raw)
    codes = {code.casefold() for code in state_codes}
    if state is not None and state.casefold() in codes:
        parts = folded.split()
        if parts and parts[-1] == state.casefold():
            parts = parts[:-1]
        folded = " ".join(parts)
    return folded or None


def _trailing_state(value: str) -> str | None:
    parenthetical = _PAREN_STATE.search(value)
    if parenthetical:
        return parenthetical.group(1)
    dashed = _DASH_STATE.search(value)
    if dashed:
        return dashed.group(1) or dashed.group(2)
    return None
