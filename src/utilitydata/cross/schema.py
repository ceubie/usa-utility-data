"""Column lists for cross-sector tables."""

from __future__ import annotations

import hashlib

import pandas as pd

FACILITY_COLUMNS = (
    "facility_id",
    "sector",
    "facility_type",
    "name",
    "name_norm",
    "state",
    "owner_name",
    "status",
    "capacity_mw",
    "unit_count",
    "source_id",
    "source_layer",
    "source_feature_id",
    "licence",
    "longitude",
    "latitude",
    "geometry_wkb",
)
UNIT_COLUMNS = (
    "unit_id",
    "facility_id",
    "sector",
    "facility_type",
    "name",
    "status",
    "capacity_mw",
    "turbine_count",
    "source_id",
    "source_layer",
    "source_feature_id",
    "licence",
    "longitude",
    "latitude",
)
NETWORK_COLUMNS = (
    "segment_id",
    "sector",
    "source_id",
    "source_layer",
    "source_feature_id",
    "segment_class",
    "owner_name",
    "status",
    "length_m",
    "has_geometry",
    "licence",
)
RELATIONSHIP_COLUMNS = (
    "relationship_id",
    "relationship_type",
    "subject_org_id",
    "related_org_id",
    "subject_name",
    "related_name",
    "subject_sector",
    "related_sector",
    "subject_utility_id",
    "related_utility_id",
    "govid",
    "confidence",
    "source_id",
    "as_of",
    "experimental",
    "coverage_note",
)
MATCH_COLUMNS = (
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
PARENT_REVIEW_COLUMNS = (
    "rank",
    "parent_name",
    "parent_utility_id",
    "customers",
    "linked_utilities",
    "utilities_missing_customers",
    "source_id",
    "as_of",
    "experimental",
    "coverage_note",
    "verified",
    "verified_by",
)
REJECT_COLUMNS = (
    "source_id",
    "source_layer",
    "source_feature_id",
    "reason",
    "raw_name",
)


def stable_id(prefix: str, *parts: object) -> str:
    """Return a short stable id. The same parts always yield the same id."""
    text = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    """Return a zero-row frame with the given columns."""
    return pd.DataFrame(columns=list(columns))
