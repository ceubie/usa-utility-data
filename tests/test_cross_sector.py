"""Cross-sector rules that do not need the national build."""

from pathlib import Path

import pandas as pd
import pytest

from utilitydata.core.config import (
    FACILITY_MATCH_DISTANCE_M,
    FACILITY_NAME_SIMILARITY,
    FACILITY_THRESHOLDS_CALIBRATED,
)
from utilitydata.cross.build import _without_state_inventory
from utilitydata.cross.capacity import resolve_plant_capacity
from utilitydata.cross.features import (
    covered_unit_states,
    facilities_from_frame,
    normalize_frame,
)
from utilitydata.cross.layers import LayerJob, csv_points, read_layer, select_layers
from utilitydata.cross.match import classify_facility_pair, match_facilities
from utilitydata.cross.owners import link_cross_sector_governments
from utilitydata.cross.parents import (
    SEC_COVERAGE_NOTE,
    filing_relationships,
    parent_customer_totals,
    rank_parents,
    write_parent_review,
)
from utilitydata.cross.vocab import (
    FacilityVocabulary,
    load_facility_types,
    require_mapped_facility_types,
)
from utilitydata.registry import Layer, Source

REPO = Path(__file__).resolve().parents[1]


def test_capacity_is_not_multiplied_by_turbine_count():
    units = pd.DataFrame({
        "facility_id": ["plant", "plant", "plant"],
        "unit_capacity_mw": [2.0, 2.0, 2.0],
        "plant_capacity_mw": [6.0, 6.0, 6.0],
        "turbine_count": [3, 3, 3],
    })
    capacity, rejects = resolve_plant_capacity(units)
    assert float(capacity.loc[capacity["facility_id"].eq("plant"), "capacity_mw"].iloc[0]) == 6.0
    assert set(rejects["reason"]) == {"repeated_plant_total"}
    assert len(rejects) == 3
    assert float(rejects["plant_capacity_mw"].iloc[0]) == 6.0


def test_different_sectors_do_not_match():
    decision, reason = classify_facility_pair("water", "electric", 0, 100)
    assert decision == "unmatched"
    assert reason == "different_sector"
    frame = pd.DataFrame([
        _facility("a", "water", "one", 0.0, 0.0),
        _facility("b", "electric", "two", 0.0, 0.0),
    ])
    assert match_facilities(frame).empty


def test_match_beyond_500_meters_goes_to_review():
    assert FACILITY_MATCH_DISTANCE_M == 500
    assert FACILITY_NAME_SIMILARITY == 85
    assert FACILITY_THRESHOLDS_CALIBRATED is False
    decision, _reason = classify_facility_pair("electric", "electric", 500, 85)
    assert decision == "match"
    reviewed, reason = classify_facility_pair("electric", "electric", 501, 85)
    assert reviewed == "review"
    assert reason == "beyond_match_distance"
    frame = pd.DataFrame([
        _facility("near", "electric", "one", 0.0, 0.0),
        _facility("far", "electric", "two", 0.01, 0.0),
    ])
    decisions = match_facilities(frame)
    assert len(decisions) == 1
    assert decisions.iloc[0]["decision"] == "review"
    assert decisions.iloc[0]["reason"] == "beyond_match_distance"
    assert float(decisions.iloc[0]["distance_m"]) > 500


def test_unmapped_facility_type_fails():
    vocabulary = load_facility_types(REPO / "registry" / "vocab" / "facility_type.yaml")
    assert vocabulary.values["Treatment Plant"] == "treatment_plant"
    assert vocabulary.values["Power Substation"] == "substation"
    with pytest.raises(ValueError, match="Unmapped facility type"):
        require_mapped_facility_types(vocabulary, ["Treatment Plant", "Not A Facility Type"])


def test_name_alone_does_not_create_a_govid_link():
    organizations = pd.DataFrame([
        _organization("water-org", "water", "local", "111"),
        _organization("sewer-org", "wastewater", "public", pd.NA),
        _organization("electric-org", "electric", "municipal", "222"),
        _organization("gas-org", "natural_gas", pd.NA, pd.NA),
    ])
    units = pd.DataFrame({
        "CENSUS_ID_PID6": ["333", "111", "222"],
        "UNIT_NAME": ["City Water", "Other Name", "Another Name"],
        "STATE": ["TX", "TX", "TX"],
    })
    assert link_cross_sector_governments(organizations, units, source_id="census", as_of="2025").empty
    linked = organizations.copy()
    linked.loc[linked["org_id"].eq("sewer-org"), "government_unit_id"] = "111"
    result = link_cross_sector_governments(linked, units, source_id="census", as_of="2025")
    assert len(result) == 1
    assert set(result.iloc[0][["subject_org_id", "related_org_id"]]) == {"water-org", "sewer-org"}
    assert result.iloc[0]["govid"] == "111"


def test_filing_relationships_deduplicates_years_and_mints_holding_orgs():
    filings = pd.DataFrame({
        "parent_company_name": ["Holding Corp", "Holding Corp", "N/A"],
        "subsidiary_company_name": ["Local Power", "Local Power", "Local Power"],
        "parent_company_utility_id_eia": [pd.NA, pd.NA, pd.NA],
        "subsidiary_company_utility_id_eia": [10, 10, 10],
        "report_date": ["2022-10-01", "2023-10-01", "2023-10-01"],
    })
    minted: dict[str, dict[str, object]] = {}
    rels, rejects = filing_relationships(
        filings,
        source_id="sec",
        confidence=0.6,
        experimental=True,
        coverage_note=SEC_COVERAGE_NOTE,
        org_by_utility={10: "ORG_EIA_10"},
        minted_orgs=minted,
    )
    assert len(rels) == 1
    assert len(rejects) == 2
    assert set(rejects["reason"]) == {"superseded_filing_duplicate", "placeholder_parent_name"}
    assert rels.iloc[0]["as_of"] == "2023-10-01"
    assert rels.iloc[0]["subject_org_id"] == "ORG_EIA_10"
    assert str(rels.iloc[0]["related_org_id"]).startswith("ORG_HOLD_")
    assert str(rels.iloc[0]["related_org_id"]) in minted


def test_parent_customers_are_not_multiplied_by_filings():
    filings = pd.DataFrame({
        "parent_company_name": ["Big", "Big"],
        "subsidiary_company_name": ["Small", "Small"],
        "parent_company_utility_id_eia": [1, 1],
        "subsidiary_company_utility_id_eia": [2, 2],
        "report_date": ["2023-10-01", "2022-10-01"],
    })
    customers = pd.DataFrame({"utility_id": [2], "customers": [10.0]})
    totals = parent_customer_totals(
        filings,
        customers,
        source_id="sec",
        experimental=True,
        coverage_note=SEC_COVERAGE_NOTE,
    )
    assert float(totals.iloc[0]["customers"]) == 10.0
    ambiguous = filings.copy()
    ambiguous.loc[1, "parent_company_name"] = "Other"
    ambiguous["report_date"] = "2023-10-01"
    none_assigned = parent_customer_totals(
        ambiguous,
        customers,
        source_id="sec",
        experimental=True,
        coverage_note=SEC_COVERAGE_NOTE,
    )
    assert none_assigned.empty or none_assigned["customers"].isna().all()


def test_parent_review_is_unverified_and_experimental(tmp_path: Path):
    totals = pd.DataFrame([{
        "parent_name": "Big",
        "parent_utility_id": 1,
        "customers": 10.0,
        "linked_utilities": 1,
        "utilities_missing_customers": 0,
        "source_id": "sec",
        "as_of": "2023-10-01",
        "experimental": True,
        "coverage_note": SEC_COVERAGE_NOTE,
    }])
    review = rank_parents(totals)
    path = tmp_path / "parents_top100.csv"
    write_parent_review(review, path)
    text = path.read_text(encoding="utf-8")
    assert "experimental and incomplete" in text
    assert "Cole" not in text
    saved = pd.read_csv(path)
    assert saved["verified"].tolist() == [False]
    assert saved["verified_by"].isna().all()


def test_draft_and_empty_geometry_layers_are_not_selected():
    sources = [
        _source("kept", True),
        _source("drafted", True),
        _source("empty", True),
        _source("unread", False),
    ]
    layers = pd.DataFrame([
        {"source_id": "kept", "layer": "0", "status": "collected"},
        {"source_id": "drafted", "layer": "0", "status": "draft"},
        {"source_id": "empty", "layer": "0", "status": "no_geometry"},
        {"source_id": "unread", "layer": "0", "status": "collected"},
    ])
    jobs, skipped = select_layers(sources, layers, grain="facility")
    assert [job.source.source_id for job in jobs] == ["kept"]
    assert {row["source_id"] for row in skipped} == {"drafted", "empty", "unread"}
    assert all(job.status == "collected" for job in jobs)
    drafted = next(job for job in skipped if job["source_id"] == "drafted")
    with pytest.raises(ValueError, match="draft"):
        read_layer(
            Path("."),
            "2026-Q4",
            LayerJob(sources[1], sources[1].layers[0], "draft"),
            layers,
        )
    assert drafted["status"] == "draft"


def test_csv_points_follow_the_declared_coordinate_pair():
    job = _point_job({"longitude": "LON", "latitude": "LAT"})
    assert csv_points(pd.DataFrame({"LON": ["0"], "LAT": ["0"]}), _point_job({})) is None
    with pytest.raises(ValueError, match="declares only longitude"):
        csv_points(pd.DataFrame({"LON": ["0"]}), _point_job({"longitude": "LON"}))
    points = csv_points(pd.DataFrame({"LON": ["", " -97.5", " "], "LAT": ["30", "30.2", "30"]}), job)
    assert points is not None
    assert points[0] is None
    assert points[2] is None
    assert points[1].x == pytest.approx(-97.5)
    assert points[1].y == pytest.approx(30.2)
    edge = csv_points(pd.DataFrame({"LON": ["180", "-180"], "LAT": ["90", "-90"]}), job)
    assert edge is not None
    assert edge[0] is not None and edge[1] is not None
    with pytest.raises(ValueError, match="not numeric"):
        csv_points(pd.DataFrame({"LON": ["abc"], "LAT": ["30"]}), job)
    with pytest.raises(ValueError, match="outside the valid range"):
        csv_points(pd.DataFrame({"LON": ["181"], "LAT": ["30"]}), job)
    with pytest.raises(ValueError, match="outside the valid range"):
        csv_points(pd.DataFrame({"LON": ["0"], "LAT": ["-90.1"]}), job)


def test_plant_capacity_comes_only_from_the_declared_column():
    vocabulary = FacilityVocabulary(frozenset({"power_plant"}), {})
    declared = _plant_layer({"plant_capacity_mw": "CAP"})
    frame = pd.DataFrame({"ID": ["1", "2"], "NAME": ["One", "Two"], "CAP": ["12.5", ""]})
    kept, rejects, _mask = normalize_frame(frame, declared.layers[0], declared, vocabulary)
    assert rejects.empty
    facilities, _units, _capacity_rejects = facilities_from_frame(kept, None, declared.layers[0], declared)
    assert float(facilities.loc[0, "capacity_mw"]) == 12.5
    assert pd.isna(facilities.loc[1, "capacity_mw"])
    bare = _plant_layer({})
    bare_frame = pd.DataFrame({"ID": ["1"], "NAME": ["One"]})
    kept, rejects, _mask = normalize_frame(bare_frame, bare.layers[0], bare, vocabulary)
    assert rejects.empty
    facilities, _units, _capacity_rejects = facilities_from_frame(kept, None, bare.layers[0], bare)
    assert pd.isna(facilities.loc[0, "capacity_mw"])


def test_eia_plant_id_keeps_same_named_projects_apart():
    vocabulary = FacilityVocabulary(frozenset({"wind_turbine"}), {})
    source = _unit_source({"eia_plant_id": "EIA", "unit_capacity_kw": "KW"})
    frame = pd.DataFrame({
        "ID": ["1", "2", "3", "4"],
        "NAME": ["Ranch", "Ranch", "Ranch", "Ranch"],
        "EIA": ["10", "20", "10", ""],
        "KW": ["1500", "1500", "1500", "1500"],
        "STATE": ["TX", "TX", "TX", "TX"],
    })
    kept, rejects, _mask = normalize_frame(frame, source.layers[0], source, vocabulary)
    assert rejects.empty
    facilities, units, _capacity_rejects = facilities_from_frame(kept, None, source.layers[0], source)
    assert len(units) == 4
    assert len(facilities) == 3
    assert set(facilities["unit_count"].astype(int)) == {1, 2}


def test_state_inventory_rejects_national_rows_and_keeps_its_own():
    state_source = _unit_source({}, source_id="state_wind", state_fixed="MI")
    other = _unit_source({}, source_id="state_units", state_fixed="NJ", facility_type="generating_unit")
    national = _unit_source({"eia_plant_id": "EIA"}, source_id="national_wind")
    covered = covered_unit_states([state_source, other, national])
    assert covered == {"wind_turbine": {"MI"}, "generating_unit": {"NJ"}}
    kept = pd.DataFrame({"feature_id": ["1", "2"], "name": ["North", "South"], "state": ["MI", "TX"]})
    job = LayerJob(national, national.layers[0], "collected")
    remaining, geometries, rejected = _without_state_inventory(kept, [None, None], job, covered)
    assert geometries == [None]
    assert remaining["state"].tolist() == ["TX"]
    assert rejected["reason"].tolist() == ["state_unit_inventory"]
    assert rejected["source_feature_id"].tolist() == ["1"]
    own_job = LayerJob(state_source, state_source.layers[0], "collected")
    own_kept, _geometries, own_rejected = _without_state_inventory(kept, None, own_job, covered)
    assert len(own_kept) == 2
    assert own_rejected.empty


def _unit_source(
    fields: dict[str, str],
    *,
    source_id: str = "turbines",
    state_fixed: str | None = None,
    facility_type: str = "wind_turbine",
) -> Source:
    layer = Layer(
        layer="turbines.csv",
        sector="electric",
        grain="facility",
        facility_level="unit",
        facility_type_fixed=facility_type,
        name_field="NAME",
        id_fields={"feature_id": "ID"},
        attribute_fields=fields,
        state_fixed=state_fixed,
        state_field=None if state_fixed else "STATE",
    )
    return Source(
        source_id=source_id,
        publisher="Publisher",
        driver="http",
        url="https://example.test/turbines",
        cadence="irregular",
        licence="unknown",
        reviewed=True,
        paths=["turbines.csv"],
        layers=[layer],
    )


def _point_job(fields: dict[str, str]) -> LayerJob:
    layer = Layer(layer="plants.csv", sector="electric", grain="facility", attribute_fields=fields)
    source = Source(
        source_id="plants",
        publisher="Publisher",
        driver="http",
        url="https://example.test/plants",
        cadence="irregular",
        licence="unknown",
        reviewed=True,
        paths=["plants.csv"],
        layers=[layer],
    )
    return LayerJob(source, layer, "nonspatial")


def _plant_layer(fields: dict[str, str]) -> Source:
    layer = Layer(
        layer="plants",
        sector="electric",
        grain="facility",
        facility_level="plant",
        facility_type_fixed="power_plant",
        name_field="NAME",
        id_fields={"feature_id": "ID"},
        attribute_fields=fields,
        state_fixed="TX",
    )
    return Source(
        source_id="plants",
        publisher="Publisher",
        driver="http",
        url="https://example.test/plants",
        cadence="irregular",
        licence="unknown",
        reviewed=True,
        paths=["plants.csv"],
        layers=[layer],
    )


def _facility(facility_id: str, sector: str, source_id: str, longitude: float, latitude: float) -> dict[str, object]:
    return {
        "facility_id": facility_id,
        "sector": sector,
        "source_id": source_id,
        "name": "City Plant",
        "name_norm": "city plant",
        "state": "TX",
        "longitude": longitude,
        "latitude": latitude,
    }


def _organization(org_id: str, sector: str, owner_type: object, govid: object) -> dict[str, object]:
    return {
        "org_id": org_id,
        "name": "City Water",
        "name_norm": "city water",
        "sector": sector,
        "state": "TX",
        "owner_type": owner_type,
        "government_unit_id": govid,
    }


def _source(source_id: str, reviewed: bool) -> Source:
    payload = {
        "source_id": source_id,
        "reviewed": reviewed,
        "layers": [{"layer": "0", "sector": "electric", "grain": "facility"}],
    }
    if reviewed:
        payload.update({
            "publisher": "Publisher",
            "driver": "arcgis",
            "url": "https://example.test/layer",
            "cadence": "irregular",
            "licence": "unknown",
            "paths": ["gis/example"],
        })
    return Source.model_validate(payload)
