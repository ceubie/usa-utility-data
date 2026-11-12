import pandas as pd
import pytest

from utilitydata.release.diff import diff_release


def test_release_diff_reports_added_removed_renamed_and_area_changes():
    previous_systems = pd.DataFrame({"system_id": ["a", "b", "c"], "name": ["Alpha", "Beta", "Gamma"]})
    current_systems = pd.DataFrame({"system_id": ["b", "c", "d"], "name": ["Beta Two", "Gamma", "Delta"]})
    previous_areas = pd.DataFrame({"service_area_id": ["s1", "s2", "s3", "s4"], "area_km2": [100.0, 100.0, 100.0, 50.0]})
    current_areas = pd.DataFrame({"service_area_id": ["s1", "s2", "s3", "s5"], "area_km2": [100.0, 111.0, 110.0, 80.0]})
    diff = diff_release(previous_systems, current_systems, previous_areas, current_areas)
    assert diff.systems.added == ("d",)
    assert diff.systems.removed == ("a",)
    assert diff.systems.renamed == (("b", "Beta", "Beta Two"),)
    assert [(item.service_area_id, item.previous_area, item.current_area) for item in diff.boundaries] == [("s2", 100.0, 111.0)]
    assert diff.areas_added == ("s5",)
    assert diff.areas_removed == ("s4",)


def test_release_diff_requires_named_columns_and_unique_ids():
    systems = pd.DataFrame({"system_id": ["a"], "name": ["Alpha"]})
    areas = pd.DataFrame({"service_area_id": ["s1"], "area_km2": [1.0]})
    with pytest.raises(ValueError, match="missing columns"):
        diff_release(systems.drop(columns=["name"]), systems, areas, areas)
    duplicated = pd.DataFrame({"system_id": ["a", "a"], "name": ["Alpha", "Alpha"]})
    with pytest.raises(ValueError, match="duplicated system_id"):
        diff_release(duplicated, systems, areas, areas)
