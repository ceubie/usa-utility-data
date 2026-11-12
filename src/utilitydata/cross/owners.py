"""Link organizations that share one government-unit id."""

from __future__ import annotations

import pandas as pd

from utilitydata.core.config import GOVERNMENT_NAME_OWNER_TYPES, GOVID_LINK_CONFIDENCE
from utilitydata.core.organization import unique_government_index
from utilitydata.core.text import as_string, require_columns
from utilitydata.cross.schema import RELATIONSHIP_COLUMNS, empty_frame, stable_id

_ORG_COLUMNS = (
    "org_id",
    "name",
    "name_norm",
    "sector",
    "state",
    "owner_type",
    "government_unit_id",
)
GOVID_COVERAGE_NOTE = (
    "The link is the shared govid from ref_government_unit. A shared name is not a link. "
    "Confidence is 1 because the govid values are equal. It is not a calibrated probability."
)


def link_cross_sector_governments(
    organizations: pd.DataFrame,
    government_units: pd.DataFrame,
    *,
    source_id: str,
    as_of: str,
) -> pd.DataFrame:
    """Link organizations in different sectors only when their govid is the same.

    A missing govid is filled only for a government owner whose state and name
    identify one government unit. An existing govid is not replaced. The same
    name with a different or missing govid does not create a link.
    """
    require_columns(organizations, _ORG_COLUMNS, "organizations")
    if not source_id or not as_of:
        raise ValueError("Government links need a source and an as-of value")
    if bool(organizations["org_id"].duplicated().any()):
        raise ValueError("Organization id is duplicated")
    work = organizations.copy()
    work["govid"] = as_string(work["government_unit_id"])
    index, _ambiguous = unique_government_index(government_units)
    eligible = (
        work["govid"].isna()
        & work["owner_type"].isin(GOVERNMENT_NAME_OWNER_TYPES)
        & work["state"].notna()
        & work["name_norm"].notna()
    )
    matched = work.loc[eligible, ["org_id", "state", "name_norm"]].merge(
        index.loc[:, ["state", "name_norm", "government_unit_id"]],
        on=["state", "name_norm"],
        how="inner",
    )
    if bool(matched["org_id"].duplicated().any()):
        raise ValueError("An organization matched more than one government unit")
    resolved = matched.drop_duplicates("org_id").set_index("org_id")["government_unit_id"].astype("string")
    fill = work["org_id"].isin(resolved.index) & work["govid"].isna()
    work.loc[fill, "govid"] = work.loc[fill, "org_id"].map(resolved)
    linked = work.loc[work["govid"].notna(), ["org_id", "name", "sector", "govid"]]
    if linked.empty:
        return empty_frame(RELATIONSHIP_COLUMNS)
    pairs = linked.merge(linked, on="govid", suffixes=("_a", "_b"))
    pairs = pairs.loc[pairs["org_id_a"].astype(str) < pairs["org_id_b"].astype(str)]
    pairs = pairs.loc[pairs["sector_a"] != pairs["sector_b"]]
    if pairs.empty:
        return empty_frame(RELATIONSHIP_COLUMNS)
    rows = [_relationship(record, source_id, as_of) for record in pairs.itertuples(index=False)]
    frame = pd.DataFrame(rows, columns=list(RELATIONSHIP_COLUMNS))
    return frame.sort_values(["govid", "subject_org_id", "related_org_id"]).reset_index(drop=True)


def _relationship(record: object, source_id: str, as_of: str) -> dict[str, object]:
    return {
        "relationship_id": stable_id("REL", "same_government", record.govid, record.org_id_a, record.org_id_b),
        "relationship_type": "same_government",
        "subject_org_id": record.org_id_a,
        "related_org_id": record.org_id_b,
        "subject_name": record.name_a,
        "related_name": record.name_b,
        "subject_sector": record.sector_a,
        "related_sector": record.sector_b,
        "subject_utility_id": pd.NA,
        "related_utility_id": pd.NA,
        "govid": record.govid,
        "confidence": GOVID_LINK_CONFIDENCE,
        "source_id": source_id,
        "as_of": as_of,
        "experimental": False,
        "coverage_note": GOVID_COVERAGE_NOTE,
    }
