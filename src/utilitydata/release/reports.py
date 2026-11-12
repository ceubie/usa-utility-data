"""Release manifest, change report, and path checks."""

import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from utilitydata.core.checks import acceptance_blockers
from utilitydata.registry import load_registry


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def blocked_case_reasons(sources: list, consumed: set[str]) -> list[str]:
    """Return reasons for acceptance cases this build has not cleared."""
    return [str(item["reason"]) for item in acceptance_blockers(sources, consumed) if item["status"] == "blocked"]


def write_change_report(
    destination: Path,
    release_id: str,
    prior: list[str],
    home: Path,
    quarter: str,
    gold: Path,
    registry_dir: Path,
) -> None:
    """Describe the release and the acceptance cases its inputs have not cleared."""
    lines = [f"# Change report for {release_id}", ""]
    if prior:
        lines.append("Prior releases: " + ", ".join(prior) + ".")
    else:
        lines.append("This is the first numbered release. There is no prior release.")
    lines.extend(["", "## What this release cannot claim", ""])
    sources = load_registry(registry_dir, require_reviewed=False)
    for reason in blocked_case_reasons(sources, _consumed_source_ids(home, quarter)):
        lines.append("- " + reason)
    manifest = pd.read_parquet(home / "snapshots" / quarter / "manifest.parquet", columns=["status"])
    drafts = int(manifest["status"].isin(["draft", "no_geometry"]).sum())
    lines.append(f"- {drafts} snapshot rows are draft or have no geometry. Those sources were not read.")
    lines.append("- Name and overlap thresholds were not calibrated. The 200-pair sample was not hand-labelled.")
    lines.append("- Best serving areas have boundary representation " + _representations(gold / "territories_water.parquet") + ".")
    lines.append("Unknown, mixed, and modeled geometry is not counted as a non-modeled boundary.")
    lines.append("- The verified truth file has no fabricated rows. Its verified-row count is in the accuracy report.")
    lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")


def reject_absolute_paths(release: Path) -> None:
    """Raise when a text artifact contains a machine path."""
    for path in release.rglob("*"):
        if path.suffix.lower() not in {".md", ".sql", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if ":\\" in text or "/Users/" in text or "/home/" in text:
            raise ValueError(path.name + " contains an absolute path")


def write_manifest(release: Path, home: Path, quarter: str, gold: Path, repository_root: Path) -> None:
    """Record the commit, snapshot, row counts, checksums, and source vintages."""
    files = sorted(path for path in release.rglob("*") if path.is_file() and path.name != "release_manifest.json")
    payload = {
        "release": release.name,
        "quarter": quarter,
        "git": _git(repository_root),
        "snapshot": {
            "quarter": quarter,
            "manifest_sha256": sha256_file(home / "snapshots" / quarter / "manifest.parquet"),
        },
        "row_counts": {
            path.relative_to(release).as_posix(): pq.ParquetFile(path).metadata.num_rows
            for path in files
            if path.suffix == ".parquet"
        },
        "checksums": {path.relative_to(release).as_posix(): sha256_file(path) for path in files},
        "source_vintages": _vintages(gold, repository_root),
    }
    (release / "release_manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _consumed_source_ids(home: Path, quarter: str) -> set[str]:
    """Return source ids present in the Silver boundary assertions for this quarter."""
    path = home / "silver" / quarter / "boundary_assertion.parquet"
    if not path.is_file():
        return set()
    return set(pd.read_parquet(path, columns=["source_id"])["source_id"].dropna().astype(str))


def _representations(path: Path) -> str:
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        rows = connection.execute(
            "SELECT boundary_representation, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 2 DESC",
            [str(path)],
        ).fetchall()
    finally:
        connection.close()
    return ", ".join(f"{name} {count}" for name, count in rows)


def _git(root: Path) -> dict[str, object]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True)
    return {"commit": commit.stdout.strip(), "dirty": bool(status.stdout.strip())}


def _vintages(gold: Path, repository_root: Path) -> list[dict[str, object]]:
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        rows = connection.execute(
            """
            SELECT source_id, min(source_vintage_date), max(source_vintage_date), count(*)
            FROM read_parquet(?)
            GROUP BY 1
            ORDER BY 1
            """,
            [str(gold / "territories_water.parquet")],
        ).fetchall()
        quarter = connection.execute(
            "SELECT DISTINCT submission_year_quarter FROM read_parquet(?)",
            [str(gold / "water_facilities.parquet")],
        ).fetchall()
    finally:
        connection.close()
    vintages: list[dict[str, object]] = [
        {
            "source_id": source_id,
            "min_vintage": None if low is None else str(low),
            "max_vintage": None if high is None else str(high),
            "rows": int(count),
        }
        for source_id, low, high, count in rows
    ]
    vintages.append({"source_id": "sdwa_submission", "values": [str(value[0]) for value in quarter]})
    for source in load_registry(repository_root / "registry" / "sources", require_reviewed=False):
        if source.storage == "home":
            vintages.append({"source_id": source.source_id, "cadence": source.cadence, "licence": source.licence})
    return vintages
