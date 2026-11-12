import zipfile
from pathlib import Path

import pytest

from utilitydata.bronze.archive import materialize_archive_member


def test_shapefile_member_extracts_sidecars_and_rejects_a_missing_dbf(tmp_path: Path):
    archive = tmp_path / "areas.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for suffix in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
            bundle.writestr(f"nested/areas{suffix}", suffix.encode())
        bundle.writestr("nested/areas.qpj", b"skip")
    destination = tmp_path / "out"
    destination.mkdir()
    extracted = materialize_archive_member(archive, "nested/areas.shp", destination)
    assert extracted.name == "areas.shp"
    assert extracted.parent == destination.resolve()
    assert {path.name for path in destination.iterdir()} == {
        "areas.shp",
        "areas.dbf",
        "areas.shx",
        "areas.prj",
        "areas.cpg",
    }

    incomplete = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(incomplete, "w") as bundle:
        bundle.writestr("areas.shp", b"shp")
        bundle.writestr("areas.shx", b"shx")
    rejected = tmp_path / "bad"
    rejected.mkdir()
    with pytest.raises(ValueError, match="missing areas.dbf"):
        materialize_archive_member(incomplete, "areas.shp", rejected)


def test_archive_member_path_cannot_escape(tmp_path: Path):
    archive = tmp_path / "areas.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("areas.shp", b"shp")
        bundle.writestr("areas.dbf", b"dbf")
        bundle.writestr("areas.shx", b"shx")
    destination = tmp_path / "out"
    destination.mkdir()
    with pytest.raises(ValueError, match="Invalid archive member"):
        materialize_archive_member(archive, "../escape.shp", destination)
    with pytest.raises(ValueError, match="Invalid archive member"):
        materialize_archive_member(archive, "nested/../../escape.shp", destination)
    assert list(destination.iterdir()) == []
