from pathlib import Path

import pytest

from utilitydata.paths import DataPaths


def test_paths_follow_configured_data_home(monkeypatch, tmp_path):
    home = tmp_path / "platform"
    repo = tmp_path / "repo"
    monkeypatch.setenv("UTILITYDATA_HOME", str(home))
    paths = DataPaths.from_environment(repository_root=repo)
    assert paths.home == home
    assert paths.raw == repo / "collection" / "data"
    assert paths.legacy == home / "legacy"
    assert paths.snapshots == home / "snapshots"
    assert paths.releases == home / "releases"


def test_home_must_be_configured(monkeypatch):
    monkeypatch.delenv("UTILITYDATA_HOME", raising=False)
    with pytest.raises(ValueError, match="Set UTILITYDATA_HOME"):
        DataPaths.from_environment()


def test_home_must_be_absolute(monkeypatch):
    monkeypatch.setenv("UTILITYDATA_HOME", str(Path("relative") / "data"))
    with pytest.raises(ValueError, match="absolute"):
        DataPaths.from_environment()
