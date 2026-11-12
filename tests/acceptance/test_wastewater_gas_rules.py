"""Wastewater and natural-gas rules that do not need the national build."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from utilitydata.core.config import (
    CWNS_TOTAL_FLOW_TYPE,
    ELECTRIC_HIFLD_OVERLAP,
    ELECTRIC_NAME_SIMILARITY,
    GAS_NAME_KEYS_CALIBRATED,
    IOU_AUTO_ACCEPT,
    NAME_AUTO_ACCEPT,
    NAME_WITH_OVERLAP,
    WASTEWATER_SEWERSHED_OVERLAP,
    WASTEWATER_THRESHOLDS_CALIBRATED,
)
from utilitydata.core.text import core_name_key, legal_form_key
from utilitydata.gas.build import GAS_ZONE_AUTHORITIES, _decision
from utilitydata.gas.match import (
    StateNameIndex,
    match_name_within_state,
    phmsa_system_id,
)
from utilitydata.registry import Layer, Source, load_registry
from utilitydata.sectors.zones import (
    LOCAL_AUTHORITIES,
    require_buildable,
    select_local_zones,
)
from utilitydata.wastewater.flow import select_total_flow
from utilitydata.wastewater.match import contained_plant_ids, federal_link


def test_water_and_electric_thresholds_are_unchanged():
    assert NAME_AUTO_ACCEPT == 95
    assert NAME_WITH_OVERLAP == 80
    assert IOU_AUTO_ACCEPT == 0.5
    assert ELECTRIC_HIFLD_OVERLAP == 0.5
    assert ELECTRIC_NAME_SIMILARITY == 70
    assert WASTEWATER_SEWERSHED_OVERLAP == 0.5
    assert WASTEWATER_THRESHOLDS_CALIBRATED is False


def test_total_flow_row_is_kept_when_it_is_not_the_last_row():
    frame = pd.DataFrame({
        "CWNS_ID": ["1", "1", "1", "2", "2"],
        "FLOW_TYPE": ["Municipal Flow", "Total Flow", "Industrial Flow", "Industrial Flow", "Total Flow"],
        "CURRENT_DESIGN_FLOW": ["1", "9", "4", "2", "8"],
    })
    kept, rejected = select_total_flow(
        frame,
        id_column="CWNS_ID",
        type_column="FLOW_TYPE",
        value_column="CURRENT_DESIGN_FLOW",
        total_value=CWNS_TOTAL_FLOW_TYPE,
    )
    assert kept["CURRENT_DESIGN_FLOW"].tolist() == ["9", "8"]
    assert kept["FLOW_TYPE"].tolist() == ["Total Flow", "Total Flow"]
    assert set(rejected["reason"]) == {"component_flow"}
    assert len(kept) + len(rejected) == len(frame)


def test_missing_total_flow_does_not_keep_the_last_row():
    frame = pd.DataFrame({
        "CWNS_ID": ["1", "1", "2"],
        "FLOW_TYPE": ["Municipal Flow", "Industrial Flow", "Total Flow"],
        "CURRENT_DESIGN_FLOW": ["1", "4", "8"],
    })
    kept, rejected = select_total_flow(
        frame,
        id_column="CWNS_ID",
        type_column="FLOW_TYPE",
        value_column="CURRENT_DESIGN_FLOW",
    )
    assert kept["CURRENT_DESIGN_FLOW"].tolist() == ["8"]
    assert set(rejected.loc[rejected["id"].eq("1"), "reason"]) == {"missing_total_flow"}
    assert len(kept) + len(rejected) == len(frame)


def test_one_contained_plant_links_and_two_plants_do_not():
    assert federal_link({}, {"01000000001"}) == ("01000000001", "single_contained_plant")
    assert federal_link({}, {"01000000001", "01000000002"}) == (None, "multiple_contained_plants")
    assert federal_link({"01000000001": 0.5}, set()) == ("01000000001", "sewershed_overlap")
    assert federal_link({"01000000001": 0.49}, {"01000000009"}) == ("01000000009", "single_contained_plant")
    assert federal_link({"01000000001": 0.8, "01000000002": 0.6}, {"01000000001"}) == (None, "ambiguous_sewershed_overlap")


def test_a_zone_geometry_contains_one_plant_and_not_two():
    zone = shapely.box(0, 0, 2, 2)
    one = gpd.GeoDataFrame({"cwns_id": ["01000000001"]}, geometry=[shapely.Point(1, 1)], crs="EPSG:4326")
    two = gpd.GeoDataFrame(
        {"cwns_id": ["01000000001", "01000000002"]},
        geometry=[shapely.Point(0.5, 0.5), shapely.Point(1.5, 1.5)],
        crs="EPSG:4326",
    )
    tree_one = shapely.STRtree(list(one.geometry))
    tree_two = shapely.STRtree(list(two.geometry))
    assert contained_plant_ids(zone, tree_one, ["01000000001"]) == {"01000000001"}
    assert contained_plant_ids(zone, tree_two, ["01000000001", "01000000002"]) == {"01000000001", "01000000002"}
    assert federal_link({}, contained_plant_ids(zone, tree_one, ["01000000001"]))[1] == "single_contained_plant"
    assert federal_link({}, contained_plant_ids(zone, tree_two, ["01000000001", "01000000002"]))[1] == "multiple_contained_plants"


def test_gas_name_match_cannot_cross_a_state():
    candidates = pd.DataFrame({
        "name_norm": ["city gas", "city gas"],
        "state": ["VA", "NC"],
        "system_id": ["SYS_PHMSA_1_VA", "SYS_PHMSA_1_NC"],
    })
    assert match_name_within_state("city gas", "VA", candidates) == ("SYS_PHMSA_1_VA", "exact_name_state")
    assert match_name_within_state("city gas", "NC", candidates) == ("SYS_PHMSA_1_NC", "exact_name_state")
    assert match_name_within_state("city gas", "VA", candidates)[0] != "SYS_PHMSA_1_NC"
    assert match_name_within_state("city gas", "MD", candidates) == (None, "no_name_in_state")


def test_name_keys_drop_legal_form_then_generic_words():
    assert GAS_NAME_KEYS_CALIBRATED is False
    assert legal_form_key("Acme Gas Co.") == "acme gas"
    assert core_name_key("Acme Gas Co.") == "acme"
    assert legal_form_key("BAINBRIDGE, CITY OF") == "bainbridge city of"
    assert core_name_key("Bainbridge Gas Dept, City Of") == "bainbridge"
    assert core_name_key("A & B Co") == "a b"
    assert legal_form_key("Inc") is None
    assert core_name_key("City of Gas") is None


def test_state_name_index_keeps_one_state_and_the_strictest_unique_tier():
    candidates = pd.DataFrame({
        "name_norm": ["acme gas co", "acme municipal", "acme gas co"],
        "state": ["VA", "VA", "NC"],
        "system_id": ["SYS_EXACT", "SYS_OTHER", "SYS_NC"],
    })
    index = StateNameIndex(candidates)
    assert index.match("acme gas co", "VA") == ("SYS_EXACT", "exact_name_state")
    assert index.match("Acme Gas Company", "VA") == ("SYS_EXACT", "legal_form_name_state")
    assert index.match("acme gas dept", "VA") == (None, "ambiguous_name_in_state")
    assert index.match("acme gas co", "NC") == ("SYS_NC", "exact_name_state")
    assert index.match("acme gas co", "MD") == (None, "no_name_in_state")
    assert index.match("acme gas dept", "NC")[0] != "SYS_EXACT"
    assert index.match(None, "VA") == (None, "missing_name_or_state")


def test_local_zones_exclude_federal_modeled_until_asked():
    assert "federal_modeled" not in LOCAL_AUTHORITIES
    assert "federal_modeled" in GAS_ZONE_AUTHORITIES
    sources = [
        _gas_zone("state_layer", "state_regulator"),
        _gas_zone("modeled_layer", "federal_modeled"),
    ]
    layers = pd.DataFrame({
        "source_id": ["state_layer", "modeled_layer"],
        "layer": ["0", "0"],
        "status": ["collected", "collected"],
    })
    jobs, drafts, skipped = select_local_zones(sources, layers, sector="natural_gas")
    assert [source.source_id for source, _layer, _status in jobs] == ["state_layer"]
    assert drafts == []
    assert skipped == []
    included, _drafts, _skipped = select_local_zones(
        sources,
        layers,
        sector="natural_gas",
        authorities=LOCAL_AUTHORITIES | {"federal_modeled"},
    )
    assert {source.source_id for source, _layer, _status in included} == {"state_layer", "modeled_layer"}


def test_gas_decision_records_the_quarter_it_is_given():
    exact = _decision("assertion-1", "SYS_A", "exact_name_state", "exact_name_state", "2027-Q1")
    loosened = _decision("assertion-2", None, "core_name_state", "core_name_state", "2027-Q1")
    assert exact["release"] == "2027-Q1"
    assert loosened["release"] == "2027-Q1"
    assert exact["score"] == 100.0
    assert loosened["score"] is None
    assert exact["decided_by"] == "rule"


def _gas_zone(source_id: str, authority: str) -> Source:
    return Source(
        source_id=source_id,
        publisher="Publisher",
        driver="http",
        url="https://example.test/gas",
        cadence="irregular",
        licence="unknown",
        reviewed=True,
        paths=["zones"],
        layers=[
            Layer(
                layer="0",
                sector="natural_gas",
                grain="service_area",
                role="active_retail_service",
                authority=authority,
                name_field="NAME",
                on_missing_name="preserve_and_review",
                state_fixed="TX",
            )
        ],
    )


def test_phmsa_id_is_stable_per_operator_and_state():
    assert phmsa_system_id(19876, "VA") == "SYS_PHMSA_19876_VA"
    assert phmsa_system_id(19876, "VA") == phmsa_system_id(19876, "VA")
    assert phmsa_system_id(19876, "NC") == "SYS_PHMSA_19876_NC"
    assert phmsa_system_id(19876, "NC") != phmsa_system_id(19876, "VA")


def test_draft_snapshot_status_is_not_readable():
    layers = pd.DataFrame({
        "source_id": ["federal_epa_cwns_2022", "south_carolina_greer_sewer_service_areas"],
        "layer": ["FACILITIES.csv", "0"],
        "status": ["draft", "no_geometry"],
    })
    with pytest.raises(ValueError, match="draft"):
        require_buildable(layers, "federal_epa_cwns_2022", "FACILITIES.csv")
    with pytest.raises(ValueError, match="no_geometry"):
        require_buildable(layers, "south_carolina_greer_sewer_service_areas", "0")


def test_draft_service_areas_are_not_selected():
    sources = load_registry(Path(__file__).resolve().parents[2] / "registry" / "sources", require_reviewed=False)
    rows = []
    for source in sources:
        for layer in source.layers:
            if layer.sector not in {"wastewater", "natural_gas"} or layer.grain != "service_area":
                continue
            status = "collected" if source.reviewed and isinstance(layer.authority, str) else "draft"
            if source.source_id in {
                "south_carolina_greer_sewer_service_areas",
                "colorado_metro_water_recovery_sewer_lines",
                "south_carolina_conway_gravity_sewers",
                "south_carolina_conway_sewer_force_mains",
            }:
                status = "no_geometry"
            rows.append({"source_id": source.source_id, "layer": layer.layer, "status": status})
    layers = pd.DataFrame(rows)
    jobs, drafts, skipped = select_local_zones(sources, layers, sector="wastewater")
    job_ids = {source.source_id for source, _layer, _status in jobs}
    assert "florida_collier_wastewater_service_area" in drafts
    assert "florida_collier_wastewater_service_area" not in job_ids
    assert "south_carolina_greer_sewer_service_areas" in drafts
    assert "south_carolina_greer_sewer_service_areas" not in job_ids
    assert "colorado_metro_water_recovery_sewer_lines" not in job_ids
    assert "south_carolina_conway_gravity_sewers" not in job_ids
    assert "alaska_sewer_areas_rca" in job_ids
    assert "federal_epa_sewersheds_v1_3" not in job_ids
    assert not skipped
    assert all(status == "collected" for _source, _layer, status in jobs)
