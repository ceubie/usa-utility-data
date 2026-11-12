"""The one facility-type list and the source values that map to it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FacilityVocabulary:
    """Canonical facility types and the exact source strings that map to them."""

    types: frozenset[str]
    values: dict[str, str]


def load_facility_types(path: Path) -> FacilityVocabulary:
    """Load the facility-type list. A map target outside the list fails."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"types", "values"}:
        raise ValueError("Facility type vocabulary must contain types and values")
    types = payload["types"]
    values = payload["values"]
    if not isinstance(types, list) or not types or len(types) != len(set(types)):
        raise ValueError("Facility type list must be unique and nonempty")
    if any(not isinstance(item, str) or not item for item in types):
        raise ValueError("Facility types must be nonempty strings")
    if not isinstance(values, dict) or not values:
        raise ValueError("Facility type values must map source text to a type")
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in values.items()):
        raise ValueError("Facility type values must be strings")
    unknown = sorted({item for item in values.values() if item not in set(types)})
    if unknown:
        raise ValueError("Facility type map points outside the list: " + ", ".join(unknown))
    return FacilityVocabulary(frozenset(types), dict(values))


def require_known_facility_type(vocabulary: FacilityVocabulary, facility_type: str) -> str:
    """Return a facility type that is on the canonical list."""
    if facility_type not in vocabulary.types:
        raise ValueError(f"Unmapped facility type: {facility_type}")
    return facility_type


def map_facility_type(vocabulary: FacilityVocabulary, value: object) -> str:
    """Map one exact source value. An unknown value fails."""
    if not isinstance(value, str):
        raise ValueError(f"Unmapped facility type: {value!r}")
    mapped = vocabulary.values.get(value)
    if mapped is None:
        raise ValueError(f"Unmapped facility type: {value}")
    return mapped


def require_mapped_facility_types(vocabulary: FacilityVocabulary, values: set[str] | list[str]) -> None:
    """Fail when any source value is missing from the facility-type map."""
    missing = sorted({value for value in values if value not in vocabulary.values})
    if missing:
        raise ValueError("Unmapped facility type: " + ", ".join(missing))
