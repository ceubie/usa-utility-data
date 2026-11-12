"""The pipeline runs every stage in order, resumes, and never writes a finished release."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

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
