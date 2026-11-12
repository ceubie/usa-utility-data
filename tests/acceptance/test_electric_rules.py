"""Electric rules that do not need the national build."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely
import yaml

from utilitydata.core.config import (
    ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER,
    ELECTRIC_DIRECT_SERVICE_YEARS,
    ELECTRIC_HIFLD_OVERLAP,
    ELECTRIC_NAME_SIMILARITY,
    ELECTRIC_THRESHOLDS_CALIBRATED,
    IOU_AUTO_ACCEPT,
    NAME_AUTO_ACCEPT,
    NAME_WITH_OVERLAP,
    THRESHOLDS_CALIBRATED,
)
from utilitydata.electric.boundaries import select_electric_layers
from utilitydata.electric.build import _service_areas, boundary_signature
from utilitydata.electric.match import area_is_eligible, zone_overlap
from utilitydata.electric.sales import (
    aggregate_retail,
    direct_service_utilities,
    require_entity_type,
    split_sales,
)
from utilitydata.registry import Source
from utilitydata.silver.boundaries import mailing_state_mismatch


def _sales_row(**overrides: object) -> dict[str, object]:
    row = {
        "utility_id_eia": 1,
        "utility_name_eia": "Example Electric",
        "state": "VA",
        "report_date": "2025-01-01",
        "customer_class": "residential",
        "business_model": "retail",
        "service_type": "bundled",
        "customers": 10,
        "sales_mwh": 20.0,
    }
    row.update(overrides)
    return row


def test_water_match_thresholds_stay_at_their_starting_values():
    assert NAME_AUTO_ACCEPT == 95
    assert NAME_WITH_OVERLAP == 80
    assert IOU_AUTO_ACCEPT == 0.5
    assert THRESHOLDS_CALIBRATED is False
    assert ELECTRIC_HIFLD_OVERLAP == 0.5
    assert ELECTRIC_NAME_SIMILARITY == 70
    assert ELECTRIC_THRESHOLDS_CALIBRATED is False


def test_bundled_and_delivery_are_summed_and_energy_only_is_rejected():
    frame = pd.DataFrame([
        _sales_row(customer_class="residential", service_type="bundled", customers=10, sales_mwh=20),
        _sales_row(customer_class="commercial", service_type="delivery", customers=5, sales_mwh=7),
        _sales_row(customer_class="industrial", service_type="energy", customers=100, sales_mwh=500),
        _sales_row(utility_id_eia=99999, utility_name_eia="Adjustment 2025", customers=-3, sales_mwh=-4),
        _sales_row(utility_id_eia=2, utility_name_eia="Withheld", customers=1, sales_mwh=1),
        _sales_row(report_date="2024-01-01", customers=9, sales_mwh=9),
    ])
    kept, prior, rejects, counts = split_sales(frame, known_states={"VA"})
    retail, _states = aggregate_retail(kept)
    assert len(prior) == 1
    assert set(rejects["reason"]) == {"energy_only_supplier", "nonutility_respondent", "withheld_respondent"}
    assert counts["input_rows"] == len(prior) + len(kept) + len(rejects)
    assert retail.loc[retail["utility_id_eia"].eq(1), "customers"].iloc[0] == 15
    assert retail.loc[retail["utility_id_eia"].eq(1), "sales_mwh"].iloc[0] == 27


def test_an_unmapped_service_type_fails_the_build():
    frame = pd.DataFrame([_sales_row(service_type="other")])
    with pytest.raises(ValueError, match="Unmapped EIA service type"):
        split_sales(frame, known_states={"VA"})


def test_an_unmapped_entity_code_fails_the_build():
    assert require_entity_type("C") == "cooperative"
    assert require_entity_type("Q") == "independent_power_producer"
    with pytest.raises(ValueError, match="Unmapped EIA entity code"):
        require_entity_type("Z")


def test_mailing_state_disagreement_is_a_mismatch_without_using_it_as_the_operating_state():
    assert mailing_state_mismatch("MO", "NM") is True
    assert mailing_state_mismatch("NM", "NM") is False
    assert mailing_state_mismatch(None, "NM") is False
    assert mailing_state_mismatch("NM", None) is False


def test_hifld_registry_has_no_state_field_and_keeps_holding_company():
    registry = Path(__file__).resolve().parents[2] / "registry" / "sources" / "hifld_electric.yaml"
    source = Source.model_validate(yaml.safe_load(registry.read_text(encoding="utf-8"))["sources"][0])
    layer = source.layers[0]
    assert source.reviewed is True
    assert layer.state_field is None
    assert layer.state_from_geometry is True
    assert layer.mailing_state_field == "STATE"
    assert layer.attribute_fields["holding_company"] == "HOLDING_CO"
    assert layer.authority == "federal_modeled"


def test_hifld_marketers_and_aggregators_are_not_retail():
    registry = Path(__file__).resolve().parents[2] / "registry" / "sources" / "hifld_electric.yaml"
    source = Source.model_validate(yaml.safe_load(registry.read_text(encoding="utf-8"))["sources"][0])
    roles = source.layers[0].role_field
    assert roles is not None and roles.field == "TYPE"
    assert roles.values["WHOLESALE POWER MARKETER"] == "regional_wholesale_or_district"
    assert roles.values["MUNICIPAL MKTG AUTHORITY"] == "regional_wholesale_or_district"
    assert roles.values["COMMUNITY CHOICE AGGREGATOR"] == "review_required"
    retail = {value for value, role in roles.values.items() if role == "active_retail_service"}
    assert retail == {"NOT AVAILABLE", "COOPERATIVE", "MUNICIPAL", "INVESTOR OWNED", "POLITICAL SUBDIVISION", "STATE", "FEDERAL"}


def test_direct_service_utilities_exceed_the_limit_in_every_recent_year():
    rows = []
    for year in ("2023-01-01", "2024-01-01", "2025-01-01"):
        rows.append(_sales_row(utility_id_eia=1, report_date=year, customers=60, sales_mwh=21_000_000.0))
        rows.append(_sales_row(utility_id_eia=2, report_date=year, customers=40_000, sales_mwh=500_000.0))
        rows.append(_sales_row(utility_id_eia=4, report_date=year, customers=2, sales_mwh=6_000.0, service_type="energy"))
        rows.append(_sales_row(utility_id_eia=99999, report_date=year, customers=1, sales_mwh=9_000.0))
    rows.append(_sales_row(utility_id_eia=3, report_date="2023-01-01", customers=110_000, sales_mwh=2_500_000.0))
    rows.append(_sales_row(utility_id_eia=3, report_date="2024-01-01", customers=5_000, sales_mwh=200_000.0))
    rows.append(_sales_row(utility_id_eia=3, report_date="2025-01-01", customers=0, sales_mwh=0.0))
    rows.append(_sales_row(utility_id_eia=5, report_date="2022-01-01", customers=1, sales_mwh=90_000.0))
    listed = direct_service_utilities(pd.DataFrame(rows), years=3, mwh_per_customer=ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER)
    assert listed["utility_id_eia"].tolist() == [1]
    assert int(listed["years_measured"].iloc[0]) == 3


def test_direct_service_limit_is_a_starting_value():
    assert ELECTRIC_DIRECT_SERVICE_MWH_PER_CUSTOMER == 2500.0
    assert ELECTRIC_DIRECT_SERVICE_YEARS == 3
    assert ELECTRIC_THRESHOLDS_CALIBRATED is False


def test_draft_electric_service_areas_are_not_selected():
    draft = Source.model_validate({
        "source_id": "draft_electric",
        "reviewed": False,
        "layers": [{"layer": "0", "sector": "electric", "grain": "service_area"}],
    })
    reviewed = Source.model_validate({
        "source_id": "reviewed_electric",
        "publisher": "Publisher",
        "driver": "arcgis",
        "url": "https://example.test/layer",
        "cadence": "irregular",
        "licence": "unknown",
        "reviewed": True,
        "paths": ["gis/reviewed"],
        "layers": [{
            "layer": "0",
            "sector": "electric",
            "grain": "service_area",
            "role": "active_retail_service",
            "authority": "state_regulator",
            "name_field": "NAME",
            "on_missing_name": "preserve_and_review",
        }],
    })
    jobs, drafts = select_electric_layers([draft, reviewed])
    assert drafts == ["draft_electric"]
    assert [source.source_id for source, _layer in jobs] == ["reviewed_electric"]


def test_a_polygon_that_adds_counties_is_not_eligible():
    assert area_is_eligible({"01001", "01002"}, {"01001"}) is False
    assert area_is_eligible({"01001"}, {"01001", "01002"}) is True
    assert area_is_eligible(set(), {"01001"}) is False


def test_overlap_is_the_share_of_the_zone_covered_by_the_territory():
    zone = shapely.box(0, 0, 2, 2)
    territory = shapely.box(0, 0, 2, 1)
    assert zone_overlap(zone, territory) == pytest.approx(0.5, abs=0.01)
    assert zone_overlap(zone, shapely.box(10, 10, 11, 11)) == 0


def test_internal_point_query_uses_the_polygon_that_covers_the_point():
    polygon = shapely.box(0, 0, 1, 1)
    outside = shapely.box(5, 5, 6, 6)
    point = shapely.point_on_surface(polygon)
    areas = gpd.GeoDataFrame({"service_area_id": ["inside", "outside"]}, geometry=[polygon, outside])
    tree = shapely.STRtree(areas.geometry.to_numpy())
    hits = tree.query([point], predicate="covered_by")
    matched = {areas["service_area_id"].iloc[int(index)] for index in hits[1]}
    assert matched == {"inside"}


def _electric_source(role: str, *, source_id: str = "reviewed_electric") -> Source:
    return Source.model_validate({
        "source_id": source_id,
        "publisher": "Publisher",
        "driver": "arcgis",
        "url": "https://example.test/layer",
        "cadence": "irregular",
        "licence": "unknown",
        "reviewed": True,
        "paths": ["gis/reviewed"],
        "layers": [{
            "layer": "0",
            "sector": "electric",
            "grain": "service_area",
            "role": role,
            "authority": "state_regulator",
            "name_field": "NAME",
            "on_missing_name": "preserve_and_review",
        }],
    })


def test_a_direct_service_system_never_gets_a_best_area():
    assertions = gpd.GeoDataFrame(
        {
            "assertion_id": ["a1", "a2"],
            "sector": ["electric", "electric"],
            "zone_role": ["active_retail_service", "active_retail_service"],
            "source_id": ["reviewed_electric", "reviewed_electric"],
            "authority": ["state_regulator", "state_regulator"],
            "grain": ["service_area", "service_area"],
            "source_vintage_date": ["2025-01-01", "2025-01-01"],
            "licence": ["public_domain", "public_domain"],
            "boundary_representation": ["polygon", "polygon"],
        },
        geometry=[shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        crs="EPSG:4326",
    )
    decisions = pd.DataFrame({"assertion_id": ["a1", "a2"], "system_id": ["SYS_EIA_1", "SYS_EIA_2"]})
    areas = _service_areas(assertions, decisions, {}, [], [], {"SYS_EIA_2"})
    best = dict(zip(areas["system_id"], areas["is_best"], strict=True))
    assert best == {"SYS_EIA_1": True, "SYS_EIA_2": False}


def test_the_boundary_cache_signature_follows_roles_and_file_content(tmp_path: Path):
    snapshot = tmp_path / "snapshots" / "2026-Q4"
    snapshot.mkdir(parents=True)
    manifest = pd.DataFrame({"source_id": ["reviewed_electric"], "relative_path": ["gis/reviewed/page_000001.json.gz"], "sha256": ["aa"]})
    manifest.to_parquet(snapshot / "manifest.parquet", index=False)
    retail = boundary_signature(tmp_path, [_electric_source("active_retail_service")], "2026-Q4")
    assert retail == boundary_signature(tmp_path, [_electric_source("active_retail_service")], "2026-Q4")
    assert retail != boundary_signature(tmp_path, [_electric_source("regional_wholesale_or_district")], "2026-Q4")
    manifest.assign(sha256=["bb"]).to_parquet(snapshot / "manifest.parquet", index=False)
    assert retail != boundary_signature(tmp_path, [_electric_source("active_retail_service")], "2026-Q4")
