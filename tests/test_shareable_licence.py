"""A shareable edition file contains only the shareable licence vocabulary."""

from pathlib import Path

import pandas as pd
import pytest

from utilitydata.core.config import SHAREABLE_LICENCES
from utilitydata.release.editions import _split_attribute


def test_shareable_rows_use_only_shareable_licences(tmp_path: Path):
    source = tmp_path / "gold" / "example.parquet"
    source.parent.mkdir()
    pd.DataFrame([
        {"licence": "public_domain", "name": "open"},
        {"licence": "cc-by-4.0", "name": "credit"},
        {"licence": "unknown", "name": "held"},
        {"licence": "internal_or_no_redistribution", "name": "internal"},
    ]).to_parquet(source, index=False)
    release = tmp_path / "release"
    (release / "internal").mkdir(parents=True)
    (release / "shareable").mkdir()
    _split_attribute(source, release)
    shareable = pd.read_parquet(release / "shareable" / "example.parquet")
    assert set(shareable["licence"]) <= SHAREABLE_LICENCES
    assert set(shareable["name"]) == {"open", "credit"}
    internal = pd.read_parquet(release / "internal" / "example.parquet")
    assert set(internal["name"]) == {"held", "internal"}


def test_an_unclassified_licence_is_not_split(tmp_path: Path):
    source = tmp_path / "gold" / "example.parquet"
    source.parent.mkdir()
    pd.DataFrame([{"licence": "mit", "name": "outside"}]).to_parquet(source, index=False)
    with pytest.raises(ValueError, match="unclassified"):
        _split_attribute(source, tmp_path / "release")
