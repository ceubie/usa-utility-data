"""Drinking-water core rules: identity, state, local ids, roles, and overrides."""

from datetime import date

import pandas as pd
import pytest
import shapely

from utilitydata.core.checks import acceptance_blockers, require_buildable_sources
from utilitydata.core.config import (
    IOU_AUTO_ACCEPT,
    LOCAL_ID_HEX_LENGTH,
    NAME_AUTO_ACCEPT,
    NAME_WITH_OVERLAP,
    THRESHOLDS_CALIBRATED,
)
from utilitydata.core.matching import ScoredCandidate, match_water, select_auto_match
from utilitydata.core.organization import link_organizations
from utilitydata.core.service_areas import assemble_service_areas
from utilitydata.core.system import build_systems_from_sdwa
from utilitydata.core.text import normalize_name
from utilitydata.release.reports import blocked_case_reasons
from utilitydata.silver.boundaries import geoparquet_metadata_present

RELEASE = "2026-Q4"


def test_thresholds_stay_at_the_uncalibrated_starting_values():
    assert NAME_AUTO_ACCEPT == 95
    assert NAME_WITH_OVERLAP == 80
    assert IOU_AUTO_ACCEPT == 0.5
    assert THRESHOLDS_CALIBRATED is False


def test_auto_match_uses_one_strong_name_or_one_overlap():
    strong = ScoredCandidate("a", NAME_AUTO_ACCEPT, None)
    other = ScoredCandidate("b", NAME_WITH_OVERLAP, 1.0)
    assert select_auto_match([strong, other]) == ("a", "name_state")
    assert select_auto_match([
        ScoredCandidate("a", NAME_AUTO_ACCEPT, 0.0),
        ScoredCandidate("b", NAME_AUTO_ACCEPT, 0.0),
    ]) == (None, None)
    assert select_auto_match([ScoredCandidate("a", NAME_WITH_OVERLAP, IOU_AUTO_ACCEPT)]) == ("a", "overlap")
    assert select_auto_match([ScoredCandidate("a", NAME_WITH_OVERLAP, IOU_AUTO_ACCEPT - 0.001)]) == (None, None)
    assert select_auto_match([
        ScoredCandidate("a", NAME_WITH_OVERLAP, IOU_AUTO_ACCEPT),
        ScoredCandidate("b", NAME_WITH_OVERLAP, IOU_AUTO_ACCEPT),
    ]) == (None, None)


def test_federal_id_link_ignores_a_conflicting_name(tmp_path):
    systems = _systems([
        _sdwa("TX0000001", "Alpha Water", "TX"),
        _sdwa("TX0000002", "Beta Works", "TX"),
    ])
    assertions = _assertions([_boundary("a", "TX0000001", "Beta Works", "TX")])
    result = _match(assertions, systems, tmp_path)
    row = result.decisions.iloc[0]
    assert row.system_id == "SYS_PWS_TX0000001"
    assert row.method == "federal_id"
    assert result.decisions.loc[result.decisions.assertion_id.eq("a"), "system_id"].iloc[0] != "SYS_PWS_TX0000002"


def test_pwsid_is_not_linked_to_a_different_system(tmp_path):
    systems = _systems([
        _sdwa("TX0000001", "Alpha Water", "TX"),
        _sdwa("TX0000002", "Beta Works", "TX"),
    ])
    assertions = _assertions([
        _boundary("named", None, "Beta Works", "TX"),
        _boundary("identified", "TX0000001", "Beta Works", "TX"),
    ])
    result = _match(assertions, systems, tmp_path)
    identified = result.decisions.loc[result.decisions.assertion_id.eq("identified")].iloc[0]
    named = result.decisions.loc[result.decisions.assertion_id.eq("named")].iloc[0]
    assert identified.system_id == "SYS_PWS_TX0000001"
    assert named.system_id == "SYS_PWS_TX0000002"
    linked = assertions.merge(result.decisions, on="assertion_id")
    single = linked.loc[linked.pwsid.notna()]
    assert (single.system_id == "SYS_PWS_" + single.pwsid.astype("string")).all()


def test_name_match_cannot_cross_a_state(tmp_path):
    systems = _systems([
        _sdwa("TX0000001", "Alpha Water", "TX"),
        _sdwa("CA0000001", "Alpha Water", "CA"),
    ])
    assertions = _assertions([
        _boundary("tx", None, "Alpha Water", "TX"),
        _boundary("nv", None, "Alpha Water", "NV"),
    ])
    result = _match(assertions, systems, tmp_path)
    texas = result.decisions.loc[result.decisions.assertion_id.eq("tx")].iloc[0]
    nevada = result.decisions.loc[result.decisions.assertion_id.eq("nv")].iloc[0]
    assert texas.system_id == "SYS_PWS_TX0000001"
    assert texas.method == "name_state"
    assert (result.sample.method.eq("name_state") & result.sample.decision.eq("auto_accept")).any()
    assert nevada.system_id.startswith("SYS_LOC_")
    assert nevada.system_id not in {"SYS_PWS_TX0000001", "SYS_PWS_CA0000001"}
    local = result.systems.loc[result.systems.system_id.eq(nevada.system_id)].iloc[0]
    assert local.primary_state == "NV"


def test_overlap_accepts_inside_the_same_state(tmp_path):
    systems = _systems([
        _sdwa("TX0000001", "Canyon Creek Works", "TX"),
        _sdwa("CA0000001", "Canyon Creek Water", "CA"),
    ])
    assertions = _assertions([
        _boundary("fed", "TX0000001", "Unrelated", "TX"),
        _boundary("query", None, "Canyon Creek Water", "TX"),
    ])
    geometries = pd.Series({
        "fed": shapely.box(0, 0, 2, 2),
        "query": shapely.box(0.1, 0.1, 1.9, 1.9),
    })
    result = _match(assertions, systems, tmp_path, geometries)
    query = result.decisions.loc[result.decisions.assertion_id.eq("query")].iloc[0]
    assert query.method == "overlap"
    assert query.system_id == "SYS_PWS_TX0000001"


def test_sys_loc_is_stable_across_a_second_run(tmp_path):
    systems = _systems([_sdwa("TX0000001", "Alpha Water", "TX")])
    assertions = _assertions([_boundary("nv", None, "Unique Quarry Water", "NV")])
    registry = tmp_path / "id_registry.parquet"
    first = _match(assertions, systems, tmp_path, registry=registry)
    second = _match(assertions, systems, tmp_path, registry=registry)
    first_id = first.decisions.iloc[0].system_id
    second_id = second.decisions.iloc[0].system_id
    assert first_id == second_id
    assert first_id.startswith("SYS_LOC_")
    assert len(first_id.removeprefix("SYS_LOC_")) == LOCAL_ID_HEX_LENGTH
    saved = pd.read_parquet(registry)
    assert len(saved) == 1
    other = _assertions([_boundary("other", None, "Different Quarry Water", "NV")])
    third = _match(other, systems, tmp_path, registry=registry)
    assert third.decisions.iloc[0].system_id != first_id
    assert len(pd.read_parquet(registry)) == 2


def test_override_row_wins(tmp_path):
    systems = _systems([
        _sdwa("TX0000001", "Alpha Water", "TX"),
        _sdwa("TX0000002", "Beta Works", "TX"),
    ])
    assertions = _assertions([
        _boundary("overridden", "TX0000001", "Alpha Water", "TX"),
        _boundary("plain", "TX0000001", "Alpha Water", "TX"),
    ])
    overrides = pd.DataFrame([{
        "assertion_id": "overridden",
        "system_id": "SYS_PWS_TX0000002",
        "decided_by": "tester",
        "notes": pd.NA,
    }])
    result = _match(assertions, systems, tmp_path, overrides=overrides)
    overridden = result.decisions.loc[result.decisions.assertion_id.eq("overridden")].iloc[0]
    plain = result.decisions.loc[result.decisions.assertion_id.eq("plain")].iloc[0]
    assert overridden.system_id == "SYS_PWS_TX0000002"
    assert overridden.method == "manual"
    assert overridden.decided_by == "tester"
    assert plain.system_id == "SYS_PWS_TX0000001"
    assert plain.method == "federal_id"


def test_inactive_systems_remain_and_activity_codes_are_explicit():
    frame = pd.DataFrame([
        _sdwa("TX0000001", "Active", "TX", activity="A"),
        _sdwa("TX0000002", "Inactive", "TX", activity="I"),
        _sdwa("TX0000003", "Not", "TX", activity="N"),
        _sdwa("TX0000004", "Proposed", "TX", activity="P"),
        _sdwa("TX0000005", "Merged", "TX", activity="M"),
        _sdwa("TX0000006", "Blank", "TX", activity=None),
    ])
    systems, _identifiers, evidence = build_systems_from_sdwa(frame, release=RELEASE, source_id="federal_sdwa", sector="water")
    assert len(systems) == 6
    assert systems.loc[systems.pwsid.eq("TX0000002"), "status"].iloc[0] == "inactive"
    assert int(evidence.activity_code.eq("I").sum()) == 1
    assert set(systems.status) == {"active", "inactive", "unknown"}
    frame.loc[0, "PWS_ACTIVITY_CODE"] = "Z"
    with pytest.raises(ValueError, match="Unmapped SDWA activity"):
        build_systems_from_sdwa(frame, release=RELEASE, source_id="federal_sdwa", sector="water")


def test_missing_named_column_raises():
    frame = pd.DataFrame([_sdwa("TX0000001", "Alpha", "TX")]).drop(columns=["PWS_NAME"])
    with pytest.raises(ValueError, match="PWS_NAME"):
        build_systems_from_sdwa(frame, release=RELEASE, source_id="federal_sdwa", sector="water")


def test_onsite_and_wholesale_roles_are_not_best(tmp_path):
    retail = [_part("S1", "active_retail_service", "utility_direct", "direct", date(2020, 1, 1), shapely.box(0, 0, 1, 1), footprint=None)]
    retail.append(_part("S1", "active_retail_service", "utility_direct", "direct", date(2020, 6, 1), shapely.box(1, 0, 2, 1), footprint=None))
    modeled = _part("S1", "active_retail_service", "federal_modeled", "model", date(2024, 1, 1), shapely.box(0, 1, 1, 2), footprint=None)
    onsite = _part("S1", "onsite_noncommunity", "utility_direct", "site", date(2024, 1, 1), shapely.box(3, 3, 4, 4), footprint=False)
    wholesale = _part("S1", "regional_wholesale_or_district", "utility_direct", "whole", date(2024, 1, 1), shapely.box(5, 5, 6, 6), footprint=None)
    only_nonserving = [
        _part("S2", "onsite_noncommunity", "utility_direct", "site", date(2024, 1, 1), shapely.box(0, 0, 1, 1), footprint=False),
        _part("S2", "regional_wholesale_or_district", "state_regulator", "whole", date(2024, 1, 1), shapely.box(2, 2, 3, 3), footprint=None),
    ]
    newer = _part("S3", "active_retail_service", "state_regulator", "new", date(2021, 1, 1), shapely.box(0, 0, 1, 1), footprint=None)
    older = _part("S3", "active_retail_service", "state_regulator", "old", date(2020, 1, 1), shapely.box(2, 2, 3, 3), footprint=None)
    areas = assemble_service_areas(pd.DataFrame([*retail, modeled, onsite, wholesale, *only_nonserving, newer, older]))
    best = areas.loc[areas.is_best]
    assert set(best.system_id) == {"S1", "S3"}
    first = best.loc[best.system_id.eq("S1")].iloc[0]
    assert first.authority == "utility_direct"
    assert first.zone_role == "active_retail_service"
    assert int(first.part_count) == 2
    assert not bool(areas.loc[areas.zone_role.eq("onsite_noncommunity"), "is_best"].any())
    assert not bool(areas.loc[areas.zone_role.eq("regional_wholesale_or_district"), "is_best"].any())
    assert not bool(areas.loc[areas.system_id.eq("S2"), "is_best"].any())
    assert best.loc[best.system_id.eq("S3"), "source_id"].iloc[0] == "new"
    path = tmp_path / "service_area.parquet"
    areas.to_parquet(path, index=False)
    assert geoparquet_metadata_present(path)


def test_local_owner_links_only_an_exact_unique_government_name():
    systems, _identifiers, _evidence = build_systems_from_sdwa(pd.DataFrame([
        _sdwa("MA0000001", "Boston", "MA", owner="L"),
        _sdwa("MA0000002", "Cambridge", "MA", owner="L"),
        _sdwa("CT0000001", "Boston", "CT", owner="L"),
        _sdwa("MA0000003", "Springfield", "MA", owner="L"),
        _sdwa("MA0000004", "Boston", "MA", owner="Y"),
    ]), release=RELEASE, source_id="federal_sdwa", sector="water")
    units = pd.DataFrame({
        "CENSUS_ID_PID6": ["111", "222", "333", "444"],
        "UNIT_NAME": ["Boston", "Springfield", "Springfield", "Boston"],
        "STATE": ["MA", "MA", "MA", "CT"],
    })
    linked, organizations, counts = link_organizations(
        systems, units, sdwa_source_id="federal_sdwa", government_source_id="census_government_units", sector="water"
    )
    boston = linked.loc[linked.pwsid.eq("MA0000001")].iloc[0]
    cambridge = linked.loc[linked.pwsid.eq("MA0000002")].iloc[0]
    connecticut = linked.loc[linked.pwsid.eq("CT0000001")].iloc[0]
    springfield = linked.loc[linked.pwsid.eq("MA0000003")].iloc[0]
    unmapped = linked.loc[linked.pwsid.eq("MA0000004")].iloc[0]
    assert boston.owner_org_id == "ORG_GOV_111"
    assert organizations.loc[organizations.org_id.eq("ORG_GOV_111"), "government_unit_id"].iloc[0] == "111"
    assert cambridge.owner_org_id.startswith("ORG_OWN_")
    assert organizations.loc[organizations.org_id.eq(cambridge.owner_org_id), "government_unit_id"].isna().all()
    assert connecticut.owner_org_id == "ORG_GOV_444"
    assert springfield.owner_org_id.startswith("ORG_OWN_")
    assert organizations.loc[organizations.org_id.eq(springfield.owner_org_id), "government_unit_id"].isna().all()
    assert unmapped.owner_type is pd.NA or pd.isna(unmapped.owner_type)
    assert not str(unmapped.owner_org_id).startswith("ORG_GOV_")
    assert counts["ambiguous_government_names"] == 1


def test_unnamed_multiple_pwsids_are_not_assigned_and_nonstandard_ids_stay_raw(tmp_path):
    systems = _systems([
        _sdwa("ND0000001", "One", "ND"),
        _sdwa("ND0000002", "Two", "ND"),
    ])
    assertions = _assertions([
        _boundary("multi", None, None, "ND", review="multiple_identifiers"),
        _boundary("raw", None, "Mountain Park MCD", "OK", raw="OKMCD0003", review="unmatched_pwsid"),
    ])
    candidates = pd.DataFrame([
        {"assertion_id": "multi", "candidate": "ND0000001", "federal_id": pd.NA, "ordinal": 0},
        {"assertion_id": "multi", "candidate": "ND0000002", "federal_id": pd.NA, "ordinal": 1},
    ])
    result = _match(assertions, systems, tmp_path, candidates=candidates)
    multi = result.decisions.loc[result.decisions.assertion_id.eq("multi")].iloc[0]
    raw = result.decisions.loc[result.decisions.assertion_id.eq("raw")].iloc[0]
    assert pd.isna(multi.system_id)
    assert "ND0000001" in multi.evidence and "ND0000002" in multi.evidence
    assert result.decisions.assertion_id.eq("multi").sum() == 1
    assert str(raw.system_id).startswith("SYS_LOC_")
    assert "OKMCD0003" in raw.evidence
    assert not result.systems.system_id.eq("SYS_PWS_OKMCD0003").any()
    assert not result.identifiers.value.eq("OKMCD0003").any()


def test_change_report_names_only_acceptance_cases_that_are_blocked():
    ready = _acceptance_source("state_tx_puct_water_ccn", True)
    other = _acceptance_source("texas_water_service_areas_twdb", True)
    consumed = {"state_tx_puct_water_ccn", "texas_water_service_areas_twdb"}
    assert blocked_case_reasons([ready, other], consumed) == []
    assert blocked_case_reasons([ready, other], set())
    other.reviewed = False
    reasons = blocked_case_reasons([ready, other], {"state_tx_puct_water_ccn"})
    assert len(reasons) == 1
    assert "Aqua Texas" in reasons[0]
    assert "still draft" not in reasons[0]


def _acceptance_source(source_id: str, reviewed: bool):
    item = type("Source", (), {})()
    item.source_id = source_id
    item.reviewed = reviewed
    return item


def test_unreviewed_acceptance_sources_block_the_case_and_cannot_be_consumed():
    case = type("Source", (), {})
    sources = []
    for source_id in ("state_tx_puct_water_ccn", "texas_water_service_areas_twdb"):
        item = case()
        item.source_id = source_id
        item.reviewed = False
        sources.append(item)
    report = acceptance_blockers(sources, set())
    assert report[0]["status"] == "blocked"
    assert report[0]["case_id"] == "aqua_texas_399_areas"
    with pytest.raises(ValueError, match="unreviewed acceptance source"):
        acceptance_blockers(sources, {"texas_water_service_areas_twdb"})
    manifest = pd.DataFrame({"source_id": ["texas_water_service_areas_twdb"], "status": ["draft"]})
    with pytest.raises(ValueError, match="Draft or empty-geometry"):
        require_buildable_sources(manifest, {"texas_water_service_areas_twdb"})


def _systems(rows: list[dict]) -> pd.DataFrame:
    systems, _identifiers, _evidence = build_systems_from_sdwa(
        pd.DataFrame(rows), release=RELEASE, source_id="federal_sdwa", sector="water"
    )
    return systems


def _match(assertions, systems, tmp_path, geometries=None, overrides=None, candidates=None, registry=None):
    if overrides is None:
        overrides = pd.DataFrame(columns=["assertion_id", "system_id", "decided_by", "notes"])
    if candidates is None:
        candidates = pd.DataFrame(columns=["assertion_id", "candidate", "federal_id"])
    return match_water(
        assertions,
        systems,
        geometries=geometries,
        overrides=overrides,
        candidates=candidates,
        registry_path=registry or tmp_path / "id_registry.parquet",
        release=RELEASE,
    )


def _sdwa(pwsid, name, state, *, activity="A", owner="P"):
    return {
        "PWSID": pwsid,
        "PWS_NAME": name,
        "PWS_ACTIVITY_CODE": activity,
        "PWS_TYPE_CODE": "CWS",
        "OWNER_TYPE_CODE": owner,
        "STATE_CODE": state,
        "POPULATION_SERVED_COUNT": 10,
        "SERVICE_CONNECTIONS_COUNT": 1,
        "IS_WHOLESALER_IND": "N",
    }


def _boundary(assertion_id, pwsid, name, state, *, raw=None, review=None):
    return {
        "assertion_id": assertion_id,
        "source_id": "example_water",
        "sector": "water",
        "zone_role": "active_retail_service",
        "authority": "state_regulator",
        "raw_name": name,
        "name_norm": normalize_name(name),
        "pwsid": pwsid,
        "pwsid_raw": raw if raw is not None else pwsid,
        "geom_state": state,
        "source_vintage_date": date(2020, 1, 1),
        "licence": "unknown",
        "grain": "service_area",
        "area_km2": 1.0,
        "footprint_verified": pd.NA,
        "activity_status": "active",
        "review_reason": review,
    }


def _assertions(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _part(system_id, role, authority, source_id, vintage, geometry, *, footprint):
    return {
        "system_id": system_id,
        "sector": "water",
        "zone_role": role,
        "source_id": source_id,
        "authority": authority,
        "grain": "service_area",
        "source_vintage_date": vintage,
        "licence": "unknown",
        "footprint_verified": footprint,
        "geometry": geometry,
    }
