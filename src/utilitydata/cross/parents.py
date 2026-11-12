"""Parent relationships from SEC filings and holding-company attributes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from utilitydata.core.config import PARENT_REVIEW_ROWS
from utilitydata.core.text import as_string, is_missing, normalize_name, require_columns
from utilitydata.cross.schema import (
    PARENT_REVIEW_COLUMNS,
    RELATIONSHIP_COLUMNS,
    empty_frame,
    stable_id,
)

_PLACEHOLDER_HOLDING_NAMES = frozenset({
    "",
    "not available",
    "not applicable",
    "n/a",
    "n a",
    "na",
    "none",
    "unknown",
    "null",
    "-",
    "tbd",
})


def holding_org_id(name_norm: str) -> str:
    """Deterministic organization identifier for a parent holding company."""
    digest = hashlib.sha256(f"holding|{name_norm}".encode()).hexdigest()[:16]
    return f"ORG_HOLD_{digest}"

SEC_COVERAGE_NOTE = (
    "out_sec10k__parents_and_subsidiaries is experimental and incomplete. "
    "It is not a complete parent map."
)
HIFLD_COVERAGE_NOTE = (
    "HIFLD HOLDING_CO is a modeled compilation. It is not hand-verified and it is not a complete parent map. "
    "Confidence is a source-quality label, not a calibrated probability."
)
_FILING_COLUMNS = (
    "parent_company_name",
    "subsidiary_company_name",
    "parent_company_utility_id_eia",
    "subsidiary_company_utility_id_eia",
    "report_date",
)


def filing_relationships(
    filings: pd.DataFrame,
    *,
    source_id: str,
    confidence: float,
    experimental: bool,
    coverage_note: str,
    org_by_utility: dict[int, str] | None = None,
    minted_orgs: dict[str, dict[str, object]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Turn each filing row into a deduplicated latest relationship or a named reject."""
    require_columns(filings, _FILING_COLUMNS, "parent filings")
    if not source_id or not coverage_note:
        raise ValueError("Parent filings need a source and a coverage note")
    work = filings.copy()
    work["parent_company_name"] = as_string(work["parent_company_name"])
    work["subsidiary_company_name"] = as_string(work["subsidiary_company_name"])
    missing = work["parent_company_name"].isna() | work["subsidiary_company_name"].isna()
    reject_frames = [
        pd.DataFrame({
            "source_id": source_id,
            "source_layer": pd.NA,
            "source_feature_id": work.index.astype("string"),
            "reason": "missing_parent_or_subsidiary",
            "raw_name": work["parent_company_name"],
        }).loc[missing]
    ]
    kept = work.loc[~missing].copy()
    if kept.empty:
        rejects = pd.concat(reject_frames, ignore_index=True)
        return empty_frame(RELATIONSHIP_COLUMNS), rejects.reset_index(drop=True)
    kept["orig_index"] = kept.index.astype("string")
    kept["parent_id"] = _utility_ids(kept["parent_company_utility_id_eia"], "parent utility id")
    kept["child_id"] = _utility_ids(kept["subsidiary_company_utility_id_eia"], "subsidiary utility id")
    kept["as_of"] = _dates(kept["report_date"])
    kept["parent_norm"] = kept["parent_company_name"].map(normalize_name)
    kept["child_norm"] = kept["subsidiary_company_name"].map(normalize_name)
    placeholder = kept["parent_norm"].isna() | kept["parent_norm"].astype(str).isin(_PLACEHOLDER_HOLDING_NAMES)
    if bool(placeholder.any()):
        reject_frames.append(
            pd.DataFrame({
                "source_id": source_id,
                "source_layer": pd.NA,
                "source_feature_id": kept.loc[placeholder, "orig_index"],
                "reason": "placeholder_parent_name",
                "raw_name": kept.loc[placeholder, "parent_company_name"],
            })
        )
        kept = kept.loc[~placeholder].copy()
    if not kept.empty:
        kept["dedup_parent"] = [
            f"id:{pid}" if pid is not None and not pd.isna(pid) else f"name:{pnorm}"
            for pid, pnorm in zip(kept["parent_id"], kept["parent_norm"], strict=True)
        ]
        kept["dedup_child"] = [
            f"id:{cid}" if cid is not None and not pd.isna(cid) else f"name:{cnorm}"
            for cid, cnorm in zip(kept["child_id"], kept["child_norm"], strict=True)
        ]
        kept["sort_date"] = kept["as_of"].fillna("")
        kept = kept.sort_values(["sort_date", "orig_index"], ascending=[False, True], kind="mergesort")
        dup_mask = kept.duplicated(["dedup_parent", "dedup_child"], keep="first")
        if bool(dup_mask.any()):
            reject_frames.append(
                pd.DataFrame({
                    "source_id": source_id,
                    "source_layer": pd.NA,
                    "source_feature_id": kept.loc[dup_mask, "orig_index"],
                    "reason": "superseded_filing_duplicate",
                    "raw_name": kept.loc[dup_mask, "parent_company_name"],
                })
            )
            kept = kept.loc[~dup_mask].copy()
    org_by_utility = org_by_utility or {}
    rows = []
    for index, record in enumerate(kept.itertuples(index=False)):
        parent_name = record.parent_company_name
        child_name = record.subsidiary_company_name
        parent_id = None if record.parent_id is None or pd.isna(record.parent_id) else int(record.parent_id)
        child_id = None if record.child_id is None or pd.isna(record.child_id) else int(record.child_id)
        as_of = record.as_of
        parent_norm = record.parent_norm
        child_norm = record.child_norm
        subject_org = None if child_id is None else org_by_utility.get(child_id)
        related_org = None if parent_id is None else org_by_utility.get(parent_id)
        if subject_org is not None and related_org is None and org_by_utility and parent_norm and parent_norm != child_norm:
            candidate_org = holding_org_id(str(parent_norm))
            if candidate_org != subject_org:
                related_org = candidate_org
                if minted_orgs is not None and candidate_org not in minted_orgs:
                    minted_orgs[candidate_org] = {
                        "org_id": candidate_org,
                        "name": str(parent_name),
                        "name_norm": str(parent_norm),
                        "state": pd.NA,
                        "owner_type": "investor_owned",
                        "owner_type_code": pd.NA,
                        "government_unit_id": pd.NA,
                        "sector": "electric",
                        "source_id": source_id,
                    }
        if subject_org is not None and related_org == subject_org:
            reject_frames.append(
                pd.DataFrame([{
                    "source_id": source_id,
                    "source_layer": pd.NA,
                    "source_feature_id": record.orig_index,
                    "reason": "self_parent_relationship",
                    "raw_name": parent_name,
                }])
            )
            continue
        rows.append({
            "relationship_id": stable_id("REL", "parent", source_id, index, parent_name, child_name, parent_id, child_id, as_of),
            "relationship_type": "parent",
            "subject_org_id": subject_org,
            "related_org_id": related_org,
            "subject_name": child_name,
            "related_name": parent_name,
            "subject_sector": "electric" if subject_org is not None else pd.NA,
            "related_sector": "electric" if related_org is not None else pd.NA,
            "subject_utility_id": pd.NA if child_id is None else str(child_id),
            "related_utility_id": pd.NA if parent_id is None else str(parent_id),
            "govid": pd.NA,
            "confidence": confidence,
            "source_id": source_id,
            "as_of": as_of,
            "experimental": experimental,
            "coverage_note": coverage_note,
        })
    rejects = pd.concat(reject_frames, ignore_index=True) if reject_frames else pd.DataFrame(columns=["source_id", "source_layer", "source_feature_id", "reason", "raw_name"])
    relationships = pd.DataFrame(rows, columns=list(RELATIONSHIP_COLUMNS)) if rows else empty_frame(RELATIONSHIP_COLUMNS)
    if len(relationships) + len(rejects) != len(filings):
        raise ValueError("Parent filing rows do not reconcile")
    return relationships, rejects.reset_index(drop=True)


def parent_customer_totals(
    filings: pd.DataFrame,
    customers: pd.DataFrame,
    *,
    source_id: str,
    experimental: bool,
    coverage_note: str,
) -> pd.DataFrame:
    """Sum customers once per utility. A utility with two parents is not assigned."""
    require_columns(filings, _FILING_COLUMNS, "parent filings")
    require_columns(customers, ("utility_id", "customers"), "utility customers")
    work = filings.copy()
    work["parent_name"] = as_string(work["parent_company_name"])
    work["parent_utility_id"] = _utility_series(work["parent_company_utility_id_eia"], "parent utility id")
    work["child_utility_id"] = _utility_series(work["subsidiary_company_utility_id_eia"], "subsidiary utility id")
    work["report_date"] = pd.to_datetime(work["report_date"], errors="coerce")
    edges = _edges(work)
    if edges.empty:
        return empty_frame((
            "parent_name",
            "parent_utility_id",
            "customers",
            "linked_utilities",
            "utilities_missing_customers",
            "source_id",
            "as_of",
            "experimental",
            "coverage_note",
        ))
    latest = edges.groupby("utility_id", dropna=False)["report_date"].transform("max")
    current = edges.loc[edges["report_date"].eq(latest)].copy()
    current["parent_key"] = list(zip(
        current["parent_name"].astype("string"),
        current["parent_utility_id"].astype("string"),
        strict=True,
    ))
    parent_count = current.groupby("utility_id", dropna=False)["parent_key"].nunique()
    single = set(parent_count.loc[parent_count.eq(1)].index)
    assigned = current.loc[current["utility_id"].isin(single)].drop_duplicates(["utility_id", "parent_key"])
    customer_ids = _utility_series(customers["utility_id"], "customer utility id")
    customer_frame = pd.DataFrame({"utility_id": customer_ids, "customers": pd.to_numeric(customers["customers"], errors="coerce")})
    assigned = assigned.merge(customer_frame, on="utility_id", how="left")
    rows = []
    for parent_key, group in assigned.groupby("parent_key", dropna=False):
        known = group["customers"].dropna()
        rows.append({
            "parent_name": group["parent_name"].iloc[0],
            "parent_utility_id": group["parent_utility_id"].iloc[0],
            "customers": None if known.empty else float(known.sum()),
            "linked_utilities": int(known.shape[0]),
            "utilities_missing_customers": int(group["customers"].isna().sum()),
            "source_id": source_id,
            "as_of": group["report_date"].max().date().isoformat(),
            "experimental": experimental,
            "coverage_note": coverage_note,
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return empty_frame((
            "parent_name",
            "parent_utility_id",
            "customers",
            "linked_utilities",
            "utilities_missing_customers",
            "source_id",
            "as_of",
            "experimental",
            "coverage_note",
        ))
    return frame


def rank_parents(totals: pd.DataFrame) -> pd.DataFrame:
    """Return the largest parents by known customers. The list is not verified."""
    require_columns(
        totals,
        ("parent_name", "customers", "source_id", "as_of", "experimental", "coverage_note"),
        "parent totals",
    )
    ranked = totals.loc[totals["customers"].notna()].sort_values(
        ["customers", "parent_name", "source_id"],
        ascending=[False, True, True],
    )
    top = ranked.head(PARENT_REVIEW_ROWS).copy()
    top.insert(0, "rank", range(1, len(top) + 1))
    top["verified"] = False
    top["verified_by"] = pd.Series(pd.NA, index=top.index, dtype="string")
    for column in PARENT_REVIEW_COLUMNS:
        if column not in top.columns:
            top[column] = pd.NA
    return top.loc[:, list(PARENT_REVIEW_COLUMNS)].reset_index(drop=True)


def write_parent_review(frame: pd.DataFrame, path: Path) -> None:
    """Write the parent review file. It cannot be marked hand-verified."""
    require_columns(frame, PARENT_REVIEW_COLUMNS, "parent review")
    if bool(frame["verified"].fillna(False).astype(bool).any()):
        raise ValueError("Parent review cannot be marked verified")
    reviewer = frame["verified_by"].astype("string")
    if bool(reviewer.str.casefold().eq("cole").fillna(False).any()):
        raise ValueError("Parent review cannot name a reviewer")
    experimental = frame.loc[frame["experimental"].astype(bool), "coverage_note"].astype("string")
    if not experimental.empty and (
        not bool(experimental.str.contains("experimental").all()) or not bool(experimental.str.contains("incomplete").all())
    ):
        raise ValueError("Experimental parent rows must stay labeled experimental and incomplete")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _edges(work: pd.DataFrame) -> pd.DataFrame:
    """Use subsidiary utilities only. A parent id is not added as its own subsidiary."""
    child = work.loc[work["child_utility_id"].notna() & work["parent_name"].notna() & work["report_date"].notna(), [
        "parent_name",
        "parent_utility_id",
        "child_utility_id",
        "report_date",
    ]]
    child = child.rename(columns={"child_utility_id": "utility_id"})
    return child.drop_duplicates(["parent_name", "parent_utility_id", "utility_id", "report_date"])


def _utility_ids(series: pd.Series, label: str) -> list[int | None]:
    numeric = _utility_series(series, label)
    return [None if pd.isna(value) else int(value) for value in numeric]


def _utility_series(series: pd.Series, label: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    bad = []
    for raw, parsed in zip(series, numeric, strict=True):
        if is_missing(raw) or (isinstance(raw, str) and not raw.strip()):
            continue
        if pd.isna(parsed):
            bad.append(str(raw))
    if bad:
        raise ValueError(f"{label} is not numeric, for example {bad[0]}")
    return numeric.astype("Int64")


def _dates(series: pd.Series) -> list[str | None]:
    parsed = pd.to_datetime(series, errors="coerce")
    bad = series.notna() & parsed.isna()
    if bool(bad.any()):
        example = series.loc[bad].iloc[0]
        raise ValueError(f"Unparsed relationship date: {example}")
    output: list[str | None] = []
    for value in parsed:
        output.append(None if pd.isna(value) else value.date().isoformat())
    return output
