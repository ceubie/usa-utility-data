"""The pipeline runs every stage in order, resumes, and never writes a finished release."""

import json
from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from utilitydata import stages as pipeline_stages
from utilitydata.pipeline import (
    STAGES,
    StageContext,
    StageSkipped,
    begin_run,
    open_release,
    run_pipeline,
    status_path,
    writable_release,
    writable_release_if_present,
)
from utilitydata.release import reports
from utilitydata.release.reports import reject_absolute_paths
from utilitydata.sectors.assemble import assemble
from utilitydata.stages import STAGE_FUNCTIONS


def _context(home: Path, release_id: str = "2026Q4.2") -> StageContext:
    return StageContext(
        home=home,
        raw=home / "raw",
        repository_root=home,
        registry_dir=home / "registry",
        quarter="2026-Q4",
        release_id=release_id,
    )


def _recording(calls: list[str], *, fail: str | None = None, skip: str | None = None):
    def stage_for(name: str):
        def run(context: StageContext):
            calls.append(name)
            if name == fail:
                raise ValueError(f"{name} broke")
            if name == skip:
                raise StageSkipped("Docker is not available")
            return {"stage": name}
        return run
    return {name: stage_for(name) for name in STAGES}


def test_every_stage_has_a_function():
    assert tuple(STAGE_FUNCTIONS) == STAGES


def test_a_release_without_a_pipeline_status_is_never_written(tmp_path: Path):
    home = tmp_path / "data"
    (home / "releases" / "2026Q4.1").mkdir(parents=True)
    for guard in (open_release, writable_release, writable_release_if_present):
        with pytest.raises(ValueError, match="finished release"):
            guard(home, "2026Q4.1")
    for resume, from_stage in ((False, None), (True, None), (False, "contracts")):
        with pytest.raises(ValueError, match="finished release"):
            begin_run(home, "2026Q4.1", resume=resume, from_stage=from_stage)
    assert not status_path(home, "2026Q4.1").exists()


def test_only_the_release_starters_create_a_folder(tmp_path: Path):
    home = tmp_path / "data"
    assert writable_release_if_present(home, "2026Q4.2") is None
    with pytest.raises(FileNotFoundError, match="has not been started"):
        writable_release(home, "2026Q4.2")
    assert not (home / "releases" / "2026Q4.2").exists()
    assert open_release(home, "2026Q4.2") == home / "releases" / "2026Q4.2"
    assert writable_release(home, "2026Q4.2").is_dir()
    assert writable_release_if_present(home, "2026Q4.2") == home / "releases" / "2026Q4.2"


def test_an_open_release_needs_resume(tmp_path: Path):
    home = tmp_path / "data"
    open_release(home, "2026Q4.2")
    with pytest.raises(FileExistsError, match="already exists"):
        begin_run(home, "2026Q4.2", resume=False, from_stage=None)
    status = begin_run(home, "2026Q4.2", resume=True, from_stage=None)
    assert set(status["stages"].values()) == {"pending"}


def test_stages_run_in_order_and_a_finished_run_is_sealed(tmp_path: Path):
    home = tmp_path / "data"
    calls: list[str] = []
    status = run_pipeline(_context(home), _recording(calls), resume=False, from_stage=None, echo=lambda _line: None)
    assert calls == list(STAGES)
    assert status["sealed"] is True
    assert json.loads((home / "releases" / "2026Q4.2" / "pipeline" / "contracts.json").read_text()) == {"stage": "contracts"}
    with pytest.raises(ValueError, match="sealed"):
        writable_release(home, "2026Q4.2")
    with pytest.raises(ValueError, match="sealed"):
        run_pipeline(_context(home), _recording([]), resume=True, from_stage="contracts", echo=lambda _line: None)


def test_a_failure_stops_the_run_and_resume_starts_at_the_failed_stage(tmp_path: Path):
    home = tmp_path / "data"
    calls: list[str] = []
    with pytest.raises(ValueError, match="electric broke"):
        run_pipeline(_context(home), _recording(calls, fail="electric"), resume=False, from_stage=None, echo=lambda _line: None)
    assert calls[-1] == "electric"
    status = json.loads(status_path(home, "2026Q4.2").read_text())
    assert status["stages"]["electric"] == "failed"
    assert status["reasons"]["electric"] == "ValueError: electric broke"
    assert status["sealed"] is False
    resumed: list[str] = []
    run_pipeline(_context(home), _recording(resumed), resume=True, from_stage=None, echo=lambda _line: None)
    assert resumed == list(STAGES[STAGES.index("electric"):])


def test_a_skipped_stage_is_retried_and_the_run_stays_open(tmp_path: Path):
    home = tmp_path / "data"
    status = run_pipeline(_context(home), _recording([], skip="graph_load"), resume=False, from_stage=None, echo=lambda _line: None)
    assert status["stages"]["graph_load"] == "skipped"
    assert status["reasons"]["graph_load"] == "Docker is not available"
    assert status["sealed"] is False
    retried: list[str] = []
    status = run_pipeline(_context(home), _recording(retried), resume=True, from_stage=None, echo=lambda _line: None)
    assert retried == ["graph_load"]
    assert status["sealed"] is True


def test_stage_functions_must_match_the_stages(tmp_path: Path):
    stages = _recording([])
    del stages["gas"]
    with pytest.raises(ValueError, match="gas"):
        run_pipeline(_context(tmp_path / "data"), stages, resume=False, from_stage=None, echo=lambda _line: None)


def test_stage_summaries_carry_no_machine_path(tmp_path: Path):
    home = tmp_path / "data"
    context = replace(_context(home), repository_root=tmp_path)
    stages = _recording([])
    stages["validate"] = lambda _context: {"table": home / "core" / "2026-Q4" / "system.parquet", "code": str(tmp_path / "src")}
    run_pipeline(context, stages, resume=False, from_stage=None, echo=lambda _line: None)
    text = (home / "releases" / "2026Q4.2" / "pipeline" / "validate.json").read_text()
    assert str(tmp_path) not in text
    assert json.loads(text) == {"table": "$UTILITYDATA_HOME/core/2026-Q4/system.parquet", "code": "./src"}
    reject_absolute_paths(home / "releases" / "2026Q4.2")


def test_the_release_manifest_leaves_out_the_run_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "data"
    release = open_release(home, "2026Q4.2")
    (release / "pipeline").mkdir()
    (release / "pipeline" / "validate.json").write_text("{}\n")
    (release / "data_dictionary.md").write_text("# Dictionary\n")
    snapshot = home / "snapshots" / "2026-Q4"
    snapshot.mkdir(parents=True)
    (snapshot / "manifest.parquet").write_bytes(b"manifest")
    monkeypatch.setattr(reports, "_git", lambda _root: {"commit": "test"})
    monkeypatch.setattr(reports, "_vintages", lambda _gold, _root: [])
    reports.write_manifest(release, home, "2026-Q4", home / "gold" / "2026-Q4", tmp_path)
    manifest = json.loads((release / "release_manifest.json").read_text())
    assert list(manifest["checksums"]) == ["data_dictionary.md"]


def test_invalid_release_ids_are_refused(tmp_path: Path):
    home = tmp_path / "data"
    bad_ids = ("", ".", "..", ".hidden", "../escaped", "a/b", "/tmp/outside", "a\\b", "has space")
    for bad_id in bad_ids:
        with pytest.raises(ValueError, match="unexpected form"):
            open_release(home, bad_id)
        with pytest.raises(ValueError, match="unexpected form"):
            writable_release_if_present(home, bad_id)
        with pytest.raises(ValueError, match="unexpected form"):
            writable_release(home, bad_id)
        with pytest.raises(ValueError, match="unexpected form"):
            begin_run(home, bad_id, resume=False, from_stage=None)
        with pytest.raises(ValueError, match="unexpected form"):
            _context(home, release_id=bad_id)


def test_from_stage_keeps_earlier_stages_done_and_rejects_unknown(tmp_path: Path):
    home = tmp_path / "data"
    with pytest.raises(ValueError, match="gas broke"):
        run_pipeline(_context(home), _recording([], fail="gas"), resume=False, from_stage=None, echo=lambda _line: None)
    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        begin_run(home, "2026Q4.2", resume=False, from_stage="nonexistent")
    calls: list[str] = []
    status = run_pipeline(_context(home), _recording(calls), resume=False, from_stage="electric", echo=lambda _line: None)
    assert calls == list(STAGES[STAGES.index("electric"):])
    assert status["sealed"] is True
    assert all(state == "done" for state in status["stages"].values())


def test_malformed_pipeline_status_is_refused(tmp_path: Path):
    home = tmp_path / "data"
    release = open_release(home, "2026Q4.2")
    status_path(home, "2026Q4.2").write_text(
        json.dumps({"stages": {stage: "pending" for stage in STAGES}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sealed"):
        writable_release(home, "2026Q4.2")
    assert release.is_dir()


def test_reject_absolute_paths_catches_posix_and_allows_urls(tmp_path: Path):
    release = open_release(tmp_path / "data", "2026Q4.2")
    (release / "change_report.md").write_text("Source: https://www.arcgis.com/home/item.html?id=1\n", encoding="utf-8")
    reject_absolute_paths(release)
    (release / "bad.json").write_text('{"path": "/tmp/leaked/file.parquet"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="absolute path"):
        reject_absolute_paths(release)


def test_assemble_updates_release_editions_and_graph_export_refreshes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "data"
    quarter = "2026-Q4"
    release_id = "2026Q4.2"
    release = open_release(home, release_id)
    gold = home / "gold" / quarter
    core = home / "core" / quarter
    snapshot = home / "snapshots" / quarter
    gold.mkdir(parents=True)
    core.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (snapshot / "manifest.parquet").write_bytes(b"manifest")

    gdf = gpd.GeoDataFrame(
        [{
            "service_area_id": "AREA_1",
            "system_id": "SYS_E1",
            "sector": "electric",
            "zone_role": "active_retail_service",
            "authority": "state_regulator",
            "licence": "public_domain",
            "geometry": shapely.box(-97.8, 30.2, -97.7, 30.3),
        }],
        geometry="geometry",
        crs="EPSG:4326",
    )
    gdf.to_parquet(gold / "territories_electric.parquet", index=False)
    pd.DataFrame([{
        "system_id": "SYS_E1",
        "sector": "electric",
        "name": "Example Electric",
        "status": "active",
        "system_type": None,
        "primary_state": "TX",
        "population_served": 100,
        "service_connections": None,
        "customers": 10.0,
        "sales_mwh": 100.0,
        "owner_org_id": None,
        "operator_org_id": None,
        "in_federal_registry": True,
        "first_seen_release": quarter,
        "last_seen_release": quarter,
    }]).to_parquet(core / "electric_system.parquet", index=False)
    (gold / "electric_report.json").write_text('{"systems": 1}\n', encoding="utf-8")

    monkeypatch.setattr(reports, "_git", lambda _root: {"commit": "test"})
    monkeypatch.setattr(reports, "_vintages", lambda _gold, _root: [])

    assemble(home, [], quarter=quarter, registry_dir=tmp_path / "registry", release_id=release_id)
    assert (release / "shareable" / "service_area_display.parquet").is_file()
    assert (release / "internal" / "service_area_display.parquet").is_file()
    assert (release / "internal" / "entity_search.parquet").is_file()
    assert (release / "shareable" / "entity_search.parquet").is_file()
    assert (release / "sector_reports.md").is_file()

    pd.DataFrame([{"state": "TX", "sector": "water"}]).to_parquet(gold / "state_sector_scorecard.parquet", index=False)
    # Also verify water federal licence + assertion alternate names are preserved by assemble.
    silver = home / "silver" / quarter
    silver.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "system_id": "SYS_W1",
        "sector": "water",
        "name": "Water One",
        "status": "active",
        "system_type": "CWS",
        "primary_state": "TX",
        "population_served": 50,
        "service_connections": 10,
        "customers": None,
        "sales_mwh": None,
        "owner_org_id": None,
        "operator_org_id": None,
        "in_federal_registry": True,
        "first_seen_release": quarter,
        "last_seen_release": quarter,
    }]).to_parquet(core / "system.parquet", index=False)
    pd.DataFrame([{"system_id": "SYS_W1", "scheme": "pwsid", "value": "TX001", "source_id": "sdwa"}]).to_parquet(
        core / "system_identifier.parquet", index=False
    )
    pd.DataFrame([{"assertion_id": "A_W1", "system_id": "SYS_W1"}]).to_parquet(core / "match_decision.parquet", index=False)
    pd.DataFrame([{"assertion_id": "A_W1", "raw_name": "Water One Alt", "licence": "public_domain", "source_id": "sdwa"}]).to_parquet(
        silver / "boundary_assertion.parquet", index=False
    )

    class _DummySource:
        def __init__(self, source_id: str, licence: str) -> None:
            self.source_id = source_id
            self.licence = licence

    assemble(home, [_DummySource("sdwa", "public_domain")], quarter=quarter, registry_dir=tmp_path / "registry", release_id=release_id)
    assert (release / "internal" / "state_sector_scorecard.parquet").is_file()
    shareable_search = pd.read_parquet(release / "shareable" / "entity_search.parquet")
    assert set(shareable_search["label"]) >= {"Water One", "Water One Alt", "TX001"}

    monkeypatch.setattr(pipeline_stages, "export_graph", lambda *_a, **_kw: _write_stub_graph(release))
    monkeypatch.setattr(pipeline_stages, "write_ntriples", lambda graph_dir: _write_stub_nt(graph_dir))
    monkeypatch.setattr(pipeline_stages, "travis_served_ids", lambda *_a, **_kw: ({"SYS_1"}, {"SYS_1"}))
    context = replace(_context(home, release_id=release_id), repository_root=tmp_path)
    pipeline_stages.graph_export(context)
    manifest = json.loads((release / "release_manifest.json").read_text(encoding="utf-8"))
    assert "sector_reports.md" in manifest["checksums"]
    assert "graph/graph.nt" in manifest["checksums"]
    assert "graph/manifest.json" in manifest["checksums"]


def _write_stub_graph(release: Path) -> dict[str, object]:
    graph = release / "graph"
    graph.mkdir(parents=True, exist_ok=True)
    (graph / "manifest.json").write_text('{"release": "2026Q4.2"}\n', encoding="utf-8")
    return {"release": "2026Q4.2"}


def _write_stub_nt(graph_dir: Path) -> dict[str, object]:
    (graph_dir / "graph.nt").write_text("", encoding="utf-8")
    return {"triples": 0}
