"""Rebuild display, scorecard, search, and sector reports from current tables.

Sector builds no longer append those products. This step reads the core tables
and the per-sector report JSON that exist and writes each product again.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from utilitydata.gold.display import rebuild_display
from utilitydata.gold.schema import SEARCH_COLUMNS
from utilitydata.gold.scorecard import write_multi_sector_scorecard
from utilitydata.gold.search import build_entity_search
from utilitydata.pipeline import writable_release
from utilitydata.registry import STATES, Source
from utilitydata.release.editions import split_sector_table
from utilitydata.sectors.overrides import load_match_overrides, require_overrides_used

_TERRITORIES = (
    "territories_water.parquet",
    "territories_electric.parquet",
    "territories_wastewater.parquet",
    "territories_gas.parquet",
)
_SECTOR_TABLES = (
    ("system.parquet", "system_identifier.parquet", "organization.parquet", "match_decision.parquet", "boundary_assertion.parquet"),
    ("electric_system.parquet", "electric_system_identifier.parquet", "electric_organization.parquet", None, None),
    ("wastewater_system.parquet", "wastewater_system_identifier.parquet", "wastewater_organization.parquet", None, None),
    ("gas_system.parquet", "gas_system_identifier.parquet", "gas_organization.parquet", None, None),
)
_USED = (
    "electric_overrides_used.csv",
    "wastewater_overrides_used.csv",
    "gas_overrides_used.csv",
)
_EMPTY_ASSERTIONS = ("system_id", "label", "licence", "source_id")
_EMPTY_ORGANIZATIONS = ("org_id", "name", "source_id")
_EMPTY_IDENTIFIERS = ("system_id", "scheme", "value", "source_id")


def assemble(
    home: Path,
    registry_sources: list[Source],
    *,
    quarter: str,
    registry_dir: Path,
    release_id: str | None = None,
) -> dict[str, object]:
    """Rebuild the shared gold products. Missing sector tables are skipped, not invented."""
    release = writable_release(home, release_id) if release_id else None
    gold = home / "gold" / quarter
    core = home / "core" / quarter
    gold.mkdir(parents=True, exist_ok=True)
    territory_paths = [gold / name for name in _TERRITORIES if (gold / name).is_file()]
    display = rebuild_display(territory_paths, gold / "service_area_display.parquet") if territory_paths else {"rows": 0}
    scorecard = None
    if (home / "silver" / quarter / "ref_block.parquet").is_file() and any((core / row[0]).is_file() for row in _SECTOR_TABLES):
        scorecard = write_multi_sector_scorecard(home, quarter)
    search = write_entity_search(home, quarter, registry_sources)
    _require_sector_overrides(registry_dir, gold)
    if release is not None:
        if (gold / "service_area_display.parquet").is_file():
            split_sector_table(gold / "service_area_display.parquet", release, geographic=True)
        if (gold / "entity_search.parquet").is_file():
            split_sector_table(gold / "entity_search.parquet", release, geographic=False)
        if (gold / "state_sector_scorecard.parquet").is_file():
            (release / "internal").mkdir(parents=True, exist_ok=True)
            (release / "internal" / "state_sector_scorecard.parquet").write_bytes(
                (gold / "state_sector_scorecard.parquet").read_bytes()
            )
    report = _write_sector_report(gold, release)
    return {
        "display_rows": display.get("rows", 0),
        "search_rows": 0 if search is None else len(search),
        "scorecard": scorecard is not None,
        "report": report,
    }


def write_entity_search(home: Path, quarter: str, sources: list[Source]) -> pd.DataFrame | None:
    """Build one search table for every sector core file that is present."""
    licence_by_source = {source.source_id: source.licence or "unknown" for source in sources}
    frames: list[pd.DataFrame] = []
    core = home / "core" / quarter
    silver = home / "silver" / quarter
    for system_name, identifier_name, organization_name, decision_name, assertion_name in _SECTOR_TABLES:
        system_path = core / system_name
        if not system_path.is_file():
            continue
        systems = pd.read_parquet(system_path)
        identifiers = (
            pd.read_parquet(core / identifier_name)
            if (core / identifier_name).is_file()
            else pd.DataFrame(columns=list(_EMPTY_IDENTIFIERS))
        )
        organizations = (
            pd.read_parquet(core / organization_name)
            if (core / organization_name).is_file()
            else pd.DataFrame(columns=list(_EMPTY_ORGANIZATIONS))
        )
        assertions = _sector_assertions(core, silver, decision_name, assertion_name)
        federal_licence = _sector_federal_licence(systems, identifiers, licence_by_source)
        frames.append(build_entity_search(
            systems,
            identifiers,
            assertions,
            organizations,
            state_codes=set(STATES),
            federal_licence=federal_licence,
            licence_by_source=licence_by_source,
        ))
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.loc[:, list(SEARCH_COLUMNS)].sort_values(
        ["entity_id", "label_role", "label", "scheme"], kind="mergesort"
    ).reset_index(drop=True)
    destination = home / "gold" / quarter / "entity_search.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(destination, index=False)
    return combined


def _sector_assertions(
    core: Path,
    silver: Path,
    decision_name: str | None,
    assertion_name: str | None,
) -> pd.DataFrame:
    if not decision_name or not assertion_name:
        return pd.DataFrame(columns=list(_EMPTY_ASSERTIONS))
    decisions = core / decision_name
    assertions = silver / assertion_name
    if not decisions.is_file() or not assertions.is_file():
        return pd.DataFrame(columns=list(_EMPTY_ASSERTIONS))
    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            SELECT d.system_id, a.raw_name AS label, a.licence, a.source_id
            FROM read_parquet(?) d
            JOIN read_parquet(?) a USING (assertion_id)
            WHERE d.system_id IS NOT NULL
            """,
            [str(decisions), str(assertions)],
        ).fetchdf()
    finally:
        connection.close()


def _sector_federal_licence(
    systems: pd.DataFrame,
    identifiers: pd.DataFrame,
    licence_by_source: dict[str, str],
) -> str:
    if systems.empty or identifiers.empty:
        return "unknown"
    federal_ids = set(systems.loc[systems["in_federal_registry"].fillna(False), "system_id"].astype(str))
    if not federal_ids:
        return "unknown"
    sources = identifiers.loc[identifiers["system_id"].astype(str).isin(federal_ids), "source_id"].dropna().astype(str)
    licences = {licence_by_source[source_id] for source_id in sources if source_id in licence_by_source}
    return next(iter(licences)) if len(licences) == 1 else "unknown"


def _require_sector_overrides(registry_dir: Path, gold: Path) -> None:
    path = registry_dir.parent / "overrides" / "match_overrides.csv"
    if not path.is_file():
        return
    overrides = load_match_overrides(path)
    used = []
    for name in _USED:
        used_path = gold / name
        if used_path.is_file():
            used.append(pd.read_csv(used_path, dtype=str, keep_default_na=False))
        elif not overrides.empty:
            raise ValueError(f"Override check is missing {name}")
    if overrides.empty:
        return
    require_overrides_used(overrides, used)


def _write_sector_report(gold: Path, release: Path | None) -> str | None:
    """Rewrite the sector report from the JSON files. The file is replaced, not appended."""
    sections = []
    for path in sorted(gold.glob("*_report.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        sections.append(f"## {path.stem}\n\n```json\n{json.dumps(payload, indent=2, default=str)}\n```")
    if not sections:
        return None
    text = "# Sector reports\n\n" + "\n\n".join(sections) + "\n"
    destination = gold / "sector_reports.md"
    destination.write_text(text, encoding="utf-8")
    if release is not None and release.is_dir():
        (release / "sector_reports.md").write_text(text, encoding="utf-8")
    return destination.as_posix()
