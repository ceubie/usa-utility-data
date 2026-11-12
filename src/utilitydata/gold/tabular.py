"""Link Safe Drinking Water Act geography rows to census counties and places.

Every input row is either resolved or written to the unresolved frame. Inactive
systems are unresolved with reason ``not_active`` and are not coverage rows.
"""

from collections import Counter

import pandas as pd

from utilitydata.core.text import as_string, require_columns
from utilitydata.gold.schema import UNRESOLVED_GEOGRAPHY_COLUMNS
from utilitydata.gold.text import county_name_key, place_name_key

_GEO_COLUMNS = (
    "PWSID",
    "AREA_TYPE_CODE",
    "ANSI_ENTITY_CODE",
    "COUNTY_SERVED",
    "CITY_SERVED",
    "STATE_SERVED",
)
_SYSTEM_COLUMNS = ("system_id", "pwsid", "status", "primary_state", "sector", "in_federal_registry")
_COUNTY_TYPES = frozenset({"CN"})
_PLACE_TYPES = frozenset({"CT"})


def classify_sdwa_geography(
    geographic: pd.DataFrame,
    systems: pd.DataFrame,
    states: pd.DataFrame,
    counties: pd.DataFrame,
    places: pd.DataFrame,
    alias: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Counter[str]]:
    """Return county links, place links, unresolved rows, and reason counts.

    County codes are the three-digit ANSI code plus a state. The state is the
    PWSID prefix when that prefix is a postal code or a state FIPS code, and
    otherwise the system's primary state. Connecticut legacy counties that map
    to more than one planning region stay unresolved.
    """
    require_columns(geographic, _GEO_COLUMNS, "SDWA geographic areas")
    require_columns(systems, _SYSTEM_COLUMNS, "systems")
    require_columns(states, ("state", "usps"), "states")
    require_columns(counties, ("county_geoid", "state", "name"), "counties")
    require_columns(places, ("place_geoid", "state", "name"), "places")
    require_columns(alias, ("old_county_geoid", "old_county_name", "county_geoid"), "county alias")
    frame = geographic.loc[:, list(_GEO_COLUMNS)].copy()
    frame["_row"] = range(len(frame))
    frame["pwsid"] = as_string(frame["PWSID"])
    if bool(frame["pwsid"].isna().any()):
        raise ValueError("SDWA geographic area is missing a PWSID")
    lookup = _system_lookup(systems)
    merged = frame.merge(lookup, on="pwsid", how="left", indicator=True)
    if len(merged) != len(frame):
        raise ValueError("SDWA geography join changed the row count")
    missing = merged["_merge"].ne("both")
    if bool(missing.any()):
        example = merged.loc[missing, "pwsid"].iloc[0]
        raise ValueError(f"SDWA geography PWSID has no system: {example}")
    merged = merged.drop(columns=["_merge"])
    reasons: list[pd.DataFrame] = []
    inactive = merged["status"].ne("active")
    reasons.append(_unresolved(merged.loc[inactive], "not_active"))
    active = merged.loc[~inactive].copy()
    other = ~active["AREA_TYPE_CODE"].isin(_COUNTY_TYPES | _PLACE_TYPES)
    reasons.append(_unresolved(active.loc[other], "area_type_not_county_place_or_tract"))
    county_rows, county_unresolved = _counties(
        active.loc[active["AREA_TYPE_CODE"].isin(_COUNTY_TYPES)].copy(),
        states,
        counties,
        alias,
    )
    place_rows, place_unresolved = _places(
        active.loc[active["AREA_TYPE_CODE"].isin(_PLACE_TYPES)].copy(),
        states,
        places,
    )
    reasons.extend([county_unresolved, place_unresolved])
    unresolved = _concat_unresolved(reasons)
    accounted = set(county_rows["_row"]).union(place_rows["_row"], unresolved["_row"])
    if accounted != set(frame["_row"]) or len(accounted) != len(frame):
        raise ValueError("SDWA geography rows were not all resolved or recorded")
    county_links = _dedupe_links(county_rows, "county_geoid")
    place_links = _dedupe_links(place_rows, "place_geoid")
    counts = Counter(unresolved["reason"].astype(str))
    counts["resolved_county_rows"] = len(county_rows)
    counts["resolved_place_rows"] = len(place_rows)
    counts["duplicate_county_links"] = len(county_rows) - len(county_links)
    counts["duplicate_place_links"] = len(place_rows) - len(place_links)
    return county_links, place_links, unresolved.loc[:, list(UNRESOLVED_GEOGRAPHY_COLUMNS)], counts


def _system_lookup(systems: pd.DataFrame) -> pd.DataFrame:
    lookup = systems.loc[:, list(_SYSTEM_COLUMNS)].copy()
    lookup["pwsid"] = as_string(lookup["pwsid"])
    if bool(lookup["pwsid"].isna().any()):
        raise ValueError("System lookup is missing a PWSID")
    if bool(lookup["pwsid"].duplicated().any()):
        raise ValueError("A PWSID belongs to more than one system")
    return lookup


def _counties(
    frame: pd.DataFrame,
    states: pd.DataFrame,
    counties: pd.DataFrame,
    alias: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame, _unresolved(frame, "county_not_in_reference")
    usps_to_fips = dict(zip(states["usps"].astype(str), states["state"].astype(str), strict=True))
    fips_codes = set(usps_to_fips.values())
    frame["state_fips"] = _state_fips(frame, usps_to_fips, fips_codes)
    frame["countyfp"] = as_string(frame["ANSI_ENTITY_CODE"])
    code_match = frame["countyfp"].str.fullmatch(r"\d{1,3}").fillna(False)
    invalid_code = frame["countyfp"].isna() | ~code_match
    unresolved = [_unresolved(frame.loc[invalid_code], "invalid_county_code")]
    valid = frame.loc[~invalid_code].copy()
    valid["countyfp"] = valid["countyfp"].str.zfill(3)
    missing_state = valid["state_fips"].isna()
    unresolved.append(_unresolved(valid.loc[missing_state], "missing_state"))
    coded = valid.loc[~missing_state].copy()
    coded["candidate_geoid"] = coded["state_fips"] + coded["countyfp"]
    coded["served_key"] = coded["COUNTY_SERVED"].map(county_name_key)
    current = counties.copy()
    current["name_key"] = current["name"].map(county_name_key)
    current = current.drop_duplicates("county_geoid")
    direct = coded.merge(
        current[["county_geoid", "name_key"]],
        left_on="candidate_geoid",
        right_on="county_geoid",
        how="left",
    )
    if len(direct) != len(coded):
        raise ValueError("County reference join changed the row count")
    matched = direct["county_geoid"].notna()
    name_ok = matched & (direct["served_key"].isna() | direct["served_key"].eq(direct["name_key"]))
    name_bad = matched & ~name_ok
    unresolved.append(_unresolved(direct.loc[name_bad], "county_name_disagrees"))
    accepted = direct.loc[name_ok].copy()
    remaining = direct.loc[~matched].copy()
    alias_links, alias_unresolved = _alias_counties(remaining, alias)
    unresolved.append(alias_unresolved)
    accepted = pd.concat([accepted, alias_links], ignore_index=True)
    return accepted, _concat_unresolved(unresolved)


def _alias_counties(frame: pd.DataFrame, alias: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame, _unresolved(frame, "ambiguous_planning_region")
    counts = alias.groupby("old_county_geoid")["county_geoid"].nunique()
    unique_ids = set(counts[counts.eq(1)].index.astype(str))
    ambiguous_ids = set(counts[counts.gt(1)].index.astype(str))
    unique = alias.loc[alias["old_county_geoid"].astype(str).isin(unique_ids)].drop_duplicates("old_county_geoid")
    unique = unique.copy()
    unique["old_key"] = unique["old_county_name"].map(county_name_key)
    unique["old_county_geoid"] = unique["old_county_geoid"].astype(str)
    merged = frame.merge(
        unique[["old_county_geoid", "county_geoid", "old_key"]],
        left_on="candidate_geoid",
        right_on="old_county_geoid",
        how="left",
        suffixes=("", "_alias"),
    )
    if len(merged) != len(frame):
        raise ValueError("County alias join changed the row count")
    if "county_geoid_alias" in merged.columns:
        merged["county_geoid"] = merged["county_geoid_alias"]
    ambiguous = merged["candidate_geoid"].isin(ambiguous_ids)
    name_ok = merged["county_geoid"].notna() & ~ambiguous
    name_ok = name_ok & (merged["served_key"].isna() | merged["served_key"].eq(merged["old_key"]))
    name_bad = merged["county_geoid"].notna() & merged["candidate_geoid"].isin(unique_ids) & ~name_ok & ~ambiguous
    unresolved = [
        _unresolved(merged.loc[ambiguous], "ambiguous_planning_region"),
        _unresolved(merged.loc[name_bad], "county_name_disagrees"),
        _unresolved(merged.loc[~ambiguous & ~name_ok & ~name_bad], "county_not_in_reference"),
    ]
    return merged.loc[name_ok].copy(), _concat_unresolved(unresolved)


def _places(
    frame: pd.DataFrame,
    states: pd.DataFrame,
    places: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame, _unresolved(frame, "place_name_not_in_reference")
    usps_to_fips = dict(zip(states["usps"].astype(str), states["state"].astype(str), strict=True))
    frame["state_fips"] = as_string(frame["STATE_SERVED"]).map(usps_to_fips)
    frame["city_key"] = frame["CITY_SERVED"].map(place_name_key)
    missing_state = frame["state_fips"].isna()
    missing_city = ~missing_state & frame["city_key"].isna()
    unresolved = [
        _unresolved(frame.loc[missing_state], "missing_state"),
        _unresolved(frame.loc[missing_city], "missing_city"),
    ]
    coded = frame.loc[~missing_state & ~missing_city].copy()
    reference = places.copy()
    reference["name_key"] = reference["name"].map(place_name_key)
    reference = reference.dropna(subset=["name_key"])
    reference["name_count"] = reference.groupby(["state", "name_key"])["place_geoid"].transform("nunique")
    unique = reference.loc[reference["name_count"].eq(1)].drop_duplicates(["state", "name_key"])
    merged = coded.merge(
        unique[["state", "name_key", "place_geoid"]],
        left_on=["state_fips", "city_key"],
        right_on=["state", "name_key"],
        how="left",
    )
    if len(merged) != len(coded):
        raise ValueError("Place reference join changed the row count")
    ambiguous_keys = reference.loc[reference["name_count"].gt(1), ["state", "name_key"]].drop_duplicates()
    ambiguous_keys["_ambiguous"] = True
    merged = merged.merge(
        ambiguous_keys,
        left_on=["state_fips", "city_key"],
        right_on=["state", "name_key"],
        how="left",
        suffixes=("", "_ambiguous_key"),
    )
    if len(merged) != len(coded):
        raise ValueError("Ambiguous place join changed the row count")
    ambiguous = merged["_ambiguous"].fillna(False).astype(bool)
    matched = merged["place_geoid"].notna() & ~ambiguous
    unresolved.extend([
        _unresolved(merged.loc[ambiguous], "ambiguous_place_name"),
        _unresolved(merged.loc[~matched & ~ambiguous], "place_name_not_in_reference"),
    ])
    return merged.loc[matched].copy(), _concat_unresolved(unresolved)


def _state_fips(frame: pd.DataFrame, usps_to_fips: dict[str, str], fips_codes: set[str]) -> pd.Series:
    prefix = frame["pwsid"].str.slice(0, 2)
    primary = as_string(frame["primary_state"])
    state = prefix.map(usps_to_fips)
    digit = state.isna() & prefix.isin(fips_codes)
    state = state.mask(digit, prefix)
    fallback = state.isna()
    state = state.mask(fallback, primary.map(usps_to_fips))
    return state


def _dedupe_links(frame: pd.DataFrame, geoid_column: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["system_id", geoid_column, "sector", "in_federal_registry"])
    columns = ["system_id", geoid_column, "sector", "in_federal_registry"]
    links = frame.loc[:, columns].copy()
    if bool(links.duplicated(["system_id", geoid_column]).any()):
        conflict = links.drop_duplicates(["system_id", geoid_column, "sector", "in_federal_registry"])
        if bool(conflict.duplicated(["system_id", geoid_column]).any()):
            raise ValueError(f"A system has conflicting attributes for one {geoid_column}")
        links = links.drop_duplicates(["system_id", geoid_column])
    return links.reset_index(drop=True)


def _unresolved(frame: pd.DataFrame, reason: str) -> pd.DataFrame:
    if frame.empty:
        empty = pd.DataFrame(columns=[*UNRESOLVED_GEOGRAPHY_COLUMNS, "_row"])
        return empty
    out = pd.DataFrame({
        "pwsid": frame["pwsid"].to_numpy(),
        "area_type_code": frame["AREA_TYPE_CODE"].to_numpy(),
        "ansi_entity_code": frame["ANSI_ENTITY_CODE"].to_numpy(),
        "county_served": frame["COUNTY_SERVED"].to_numpy(),
        "city_served": frame["CITY_SERVED"].to_numpy(),
        "state_served": frame["STATE_SERVED"].to_numpy(),
        "reason": reason,
        "system_id": frame["system_id"].to_numpy(),
        "_row": frame["_row"].to_numpy(),
    })
    return out


def _concat_unresolved(frames: list[pd.DataFrame]) -> pd.DataFrame:
    present = [frame for frame in frames if not frame.empty]
    if not present:
        return pd.DataFrame(columns=[*UNRESOLVED_GEOGRAPHY_COLUMNS, "_row"])
    return pd.concat(present, ignore_index=True)
