"""Extract one zip member, including a file geodatabase stored as a directory."""

import shutil
import zipfile
from pathlib import Path

SHAPEFILE_SIDECARS = frozenset({".dbf", ".shx", ".prj", ".cpg"})


def materialize_archive_member(archive: Path, member: str, destination: Path) -> Path:
    """Copy one archive member into destination and return the extracted path.

    A ``.gdb`` member is a directory of files inside the zip. Every file under
    that prefix is extracted. A ``.shp`` member is extracted with the files in
    the same zip folder that share its stem (``.dbf``, ``.shx``, ``.prj``,
    ``.cpg``), because a shapefile cannot be read without them. Any other
    member is one file. Paths that leave the destination raise.
    """
    normalized = member.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
        raise ValueError(f"Invalid archive member: {member}")
    destination = destination.resolve()
    if not zipfile.is_zipfile(archive):
        raise ValueError(f"Invalid geospatial archive: {archive.name}")
    with zipfile.ZipFile(archive) as bundle:
        if normalized.endswith(".gdb"):
            return _extract_directory(bundle, normalized, destination)
        names = {name.replace("\\", "/"): name for name in bundle.namelist()}
        actual = names.get(normalized)
        if actual is None:
            raise ValueError(f"Missing archive member {normalized}")
        extracted = _extract_file(bundle, actual, normalized, destination)
        if normalized.lower().endswith(".shp"):
            stem = normalized[: -len(".shp")]
            for name, raw_name in sorted(names.items()):
                suffix = name[len(stem):]
                is_sidecar = name.startswith(stem) and suffix.lower() in SHAPEFILE_SIDECARS
                if is_sidecar:
                    _extract_file(bundle, raw_name, name, destination)
            required = [extracted.with_suffix(suffix) for suffix in (".dbf", ".shx")]
            present = {path.name.lower() for path in destination.iterdir()}
            missing = [path.name for path in required if path.name.lower() not in present]
            if missing:
                raise ValueError(f"Shapefile member {normalized} is missing {', '.join(missing)}")
        return extracted


def _extract_file(bundle: zipfile.ZipFile, actual: str, normalized: str, destination: Path) -> Path:
    extracted = (destination / Path(normalized).name).resolve()
    if not extracted.is_relative_to(destination):
        raise ValueError("Archive member escapes destination")
    with bundle.open(actual) as raw, extracted.open("xb") as output:
        shutil.copyfileobj(raw, output, 4 * 1024 * 1024)
    return extracted


def _extract_directory(bundle: zipfile.ZipFile, member: str, destination: Path) -> Path:
    prefix = member.rstrip("/") + "/"
    chosen = [
        name
        for name in bundle.namelist()
        if name.replace("\\", "/").startswith(prefix) and not name.endswith("/")
    ]
    if not chosen:
        raise ValueError(f"Missing archive member {member}")
    root = (destination / Path(member).name).resolve()
    if not root.is_relative_to(destination):
        raise ValueError("Archive member escapes destination")
    root.mkdir(parents=True)
    for name in chosen:
        relative = name.replace("\\", "/").removeprefix(prefix)
        if not relative or ".." in Path(relative).parts:
            raise ValueError(f"Invalid archive member path: {name}")
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Archive member escapes destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        with bundle.open(name) as raw, target.open("xb") as output:
            shutil.copyfileobj(raw, output, 4 * 1024 * 1024)
    return root
