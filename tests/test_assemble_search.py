"""Assembled search finds each sector by name and by identifier."""

from pathlib import Path

import pandas as pd

from utilitydata.gold.search import resolve_entities
from utilitydata.registry import STATES
from utilitydata.sectors.assemble import write_entity_search
from utilitydata.sectors.overrides import apply_match_overrides


class _Source:
    def __init__(self, source_id: str, licence: str) -> None:
        self.source_id = source_id
        self.licence = licence


def _system(system_id: str, name: str, sector: str) -> dict[str, object]:
    return {
        "system_id": system_id,
        "sector": sector,
        "name": name,
        "status": "active",
        "system_type": None,
        "primary_state": "TX",
        "population_served": 10,
        "service_connections": None,
        "customers": None,
        "sales_mwh": None,
        "owner_org_id": None,
        "operator_org_id": None,
        "in_federal_registry": False,
        "first_seen_release": "2026-Q4",
        "last_seen_release": "2026-Q4",
    }


def test_search_finds_electric_wastewater_and_gas(tmp_path: Path):
    core = tmp_path / "core" / "2026-Q4"
    core.mkdir(parents=True)
    rows = {
        "electric_system.parquet": [_system("SYS_E", "Example Electric", "electric")],
        "wastewater_system.parquet": [_system("SYS_W", "Example Sewer", "wastewater")],
        "gas_system.parquet": [_system("SYS_G", "Example Gas", "natural_gas")],
    }
    identifiers = {
        "electric_system_identifier.parquet": [("SYS_E", "eia", "EIA-100", "src_e")],
        "wastewater_system_identifier.parquet": [("SYS_W", "cwns", "CWNS-200", "src_w")],
        "gas_system_identifier.parquet": [("SYS_G", "phmsa", "PHMSA-300", "src_g")],
    }
    for name, records in rows.items():
        pd.DataFrame(records).to_parquet(core / name, index=False)
    for name, records in identifiers.items():
        pd.DataFrame(records, columns=["system_id", "scheme", "value", "source_id"]).to_parquet(core / name, index=False)
    sources = [_Source("src_e", "unknown"), _Source("src_w", "unknown"), _Source("src_g", "unknown")]
    frame = write_entity_search(tmp_path, "2026-Q4", sources)
    assert frame is not None
    codes = set(STATES)
    assert resolve_entities(frame, "Example Electric", state_codes=codes) == {"SYS_E"}
    assert resolve_entities(frame, "Example Sewer", state_codes=codes) == {"SYS_W"}
    assert resolve_entities(frame, "Example Gas", state_codes=codes) == {"SYS_G"}
    assert resolve_entities(frame, "EIA-100", state_codes=codes) == {"SYS_E"}
    assert resolve_entities(frame, "CWNS-200", state_codes=codes) == {"SYS_W"}
    assert resolve_entities(frame, "PHMSA-300", state_codes=codes) == {"SYS_G"}
    again = write_entity_search(tmp_path, "2026-Q4", sources)
    assert again is not None
    assert list(again["entity_id"]) == list(frame["entity_id"])


def _override_case(method: str) -> None:
    decisions = pd.DataFrame([{
        "assertion_id": "A1",
        "system_id": "SYS_OLD",
        "method": method,
        "score": None,
        "evidence": "before",
        "decided_by": "rule",
        "release": "2026-Q4",
    }])
    systems = pd.DataFrame([{"system_id": "SYS_NEW"}])
    overrides = pd.DataFrame([{
        "assertion_id": "A1",
        "system_id": "SYS_NEW",
        "decided_by": "Cole",
        "notes": "sector test",
    }])
    updated, used = apply_match_overrides(decisions, systems, overrides)
    assert updated.iloc[0]["method"] == "override"
    assert updated.iloc[0]["system_id"] == "SYS_NEW"
    assert updated.iloc[0]["evidence"] == "sector test"
    assert list(used["assertion_id"]) == ["A1"]


def test_electric_override_changes_the_decision():
    _override_case("eia_id")


def test_wastewater_override_changes_the_decision():
    _override_case("sewershed_overlap")


def test_gas_override_changes_the_decision():
    _override_case("exact_name_state")
