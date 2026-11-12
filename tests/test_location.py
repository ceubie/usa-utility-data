"""Facility points and place population choose one county each."""

import pandas as pd
import shapely

from utilitydata.cross.location import facility_counties, place_counties


def test_missing_coordinates_are_counted_and_a_boundary_uses_the_lower_geoid():
    counties = [shapely.box(0, 0, 1, 1), shapely.box(1, 0, 2, 1)]
    facilities = pd.DataFrame([
        {"facility_id": "IN", "longitude": 0.5, "latitude": 0.5},
        {"facility_id": "EDGE", "longitude": 1.0, "latitude": 0.5},
        {"facility_id": "NONE", "longitude": None, "latitude": None},
        {"facility_id": "OUT", "longitude": 9.0, "latitude": 9.0},
    ])
    frame, report = facility_counties(facilities, counties, ["10002", "10001"])
    assert report == {"without_coordinates": 1, "outside_counties": 1}
    located = dict(zip(frame["subject_id"], frame["county_geoid"], strict=True))
    assert located["IN"] == "10002"
    assert located["EDGE"] == "10001"
    assert "NONE" not in located
    assert "OUT" not in located


def test_a_place_that_spans_counties_uses_population_then_geoid():
    blocks = pd.DataFrame([
        {"place_geoid": "P1", "county_geoid": "00002", "pop20": 10},
        {"place_geoid": "P1", "county_geoid": "00001", "pop20": 10},
        {"place_geoid": "P2", "county_geoid": "00002", "pop20": 5},
        {"place_geoid": "P2", "county_geoid": "00003", "pop20": 9},
        {"place_geoid": None, "county_geoid": "00001", "pop20": 100},
    ])
    frame = place_counties(blocks)
    chosen = dict(zip(frame["subject_id"], frame["county_geoid"], strict=True))
    assert chosen == {"P1": "00001", "P2": "00003"}
    assert set(frame["subject_class"]) == {"place"}
