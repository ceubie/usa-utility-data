"""The function behind each pipeline stage. Each one calls an existing build step."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from utilitydata.checks.runner import run_checks, write_report
from utilitydata.core.build import build_water_core
from utilitydata.cross.build import build_cross_sector
from utilitydata.electric.build import build_electric
from utilitydata.gas.build import build_gas
from utilitydata.graph.export_nt import write_ntriples
from utilitydata.graph.export_tables import export_graph, travis_served_ids
from utilitydata.graph.fuseki import load_and_serve
from utilitydata.graph.store import (
    SparqlStore,
    system_ids_from_bindings,
    travis_water_query,
)
from utilitydata.pipeline import STAGES, SUMMARY_DIR, Stage, StageContext, StageSkipped
from utilitydata.registry import load_registry, relaxed_restrictions
from utilitydata.release.build import build_water_release
from utilitydata.release.reports import reject_absolute_paths, write_manifest
from utilitydata.sectors.assemble import assemble
from utilitydata.sectors.promote import PROMOTION_BACKUPS, promote_reviewed_collection
from utilitydata.silver.boundaries import build_water_silver
from utilitydata.wastewater.build import build_wastewater


def validate(context: StageContext) -> Mapping[str, object]:
    sources = load_registry(context.registry_dir, require_reviewed=False, raw_root=context.raw, home_root=context.home)
    frozen = context.home / "snapshots" / context.quarter / "registry"
    if not frozen.is_dir():
        raise ValueError(f"Snapshot registry is missing for {context.quarter}")
    relaxed = relaxed_restrictions(load_registry(frozen, require_reviewed=False), sources)
    if relaxed:
        raise ValueError(f"Licence restrictions were relaxed without approval: {', '.join(relaxed)}")
    reviewed = sum(source.reviewed for source in sources)
    return {"sources": len(sources), "reviewed": reviewed, "drafts": len(sources) - reviewed}


def promote(context: StageContext) -> Mapping[str, object]:
    """Promote reviewed sources the freeze left draft. The promotion backs up the snapshot tables first."""
    snapshot = context.home / "snapshots" / context.quarter
    sources = load_registry(context.registry_dir, require_reviewed=False)
    layers = pd.read_parquet(snapshot / "layers.parquet", columns=["source_id", "status"])
    draft = set(layers.loc[layers["status"].eq("draft"), "source_id"])
    selected = {source.source_id for source in sources if source.reviewed and source.storage == "collection" and source.source_id in draft}
    promoted = promote_reviewed_collection(context.home, context.quarter, sources, selected) if selected else []
    backups = sorted(path.relative_to(context.home).as_posix() for path in (snapshot / PROMOTION_BACKUPS).glob("*") if path.is_dir())
    return {"promoted": promoted, "backups": backups}


def silver_water(context: StageContext) -> Mapping[str, object]:
    return build_water_silver(context.home, context.registry_dir, quarter=context.quarter)


def core_water(context: StageContext) -> Mapping[str, object]:
    return build_water_core(context.home, context.registry_dir, quarter=context.quarter)


def release_water(context: StageContext) -> Mapping[str, object]:
    return build_water_release(
        context.home,
        context.registry_dir,
        context.repository_root,
        quarter=context.quarter,
        release_id=context.release_id,
        rebuild_coverage=True,
    )


def electric(context: StageContext) -> Mapping[str, object]:
    return build_electric(context.home, context.registry_dir, context.repository_root, quarter=context.quarter, release_id=context.release_id)


def wastewater(context: StageContext) -> Mapping[str, object]:
    return build_wastewater(context.home, context.registry_dir, context.repository_root, quarter=context.quarter, release_id=context.release_id)


def gas(context: StageContext) -> Mapping[str, object]:
    return build_gas(context.home, context.registry_dir, context.repository_root, quarter=context.quarter, release_id=context.release_id)


def cross(context: StageContext) -> Mapping[str, object]:
    return build_cross_sector(context.home, context.registry_dir, context.repository_root, quarter=context.quarter)


def assemble_products(context: StageContext) -> Mapping[str, object]:
    sources = load_registry(context.registry_dir, require_reviewed=False)
    summary = assemble(context.home, sources, quarter=context.quarter, registry_dir=context.registry_dir, release_id=context.release_id)
    write_manifest(context.release, context.home, context.quarter, context.home / "gold" / context.quarter, context.repository_root)
    reject_absolute_paths(context.release)
    return summary


def graph_export(context: StageContext) -> Mapping[str, object]:
    manifest = export_graph(
        context.home,
        context.repository_root,
        quarter=context.quarter,
        release_id=context.release_id,
        registry_dir=context.registry_dir,
    )
    triples = write_ntriples(context.release / "graph")
    gold_ids, edge_ids = travis_served_ids(context.home, context.quarter, context.release_id)
    if gold_ids != edge_ids:
        raise ValueError("Travis County water systems in the graph edges do not match Gold")
    write_manifest(context.release, context.home, context.quarter, context.home / "gold" / context.quarter, context.repository_root)
    reject_absolute_paths(context.release)
    return {"manifest": manifest, "triples": triples, "travis_county_water_served": len(gold_ids)}


def contracts(context: StageContext) -> Mapping[str, object]:
    reports: dict[str, str] = {}
    failed: list[str] = []
    for layer in ("core", "gold"):
        result = run_checks(
            context.repository_root / "contracts" / layer,
            context.home / layer / context.quarter,
            context.repository_root / "registry" / "vocab",
        )
        write_report(context.release / SUMMARY_DIR / f"contracts_{layer}.json", result)
        reports[layer] = result["status"]
        if result["status"] != "pass":
            failed.append(layer)
    reject_absolute_paths(context.release)
    if failed:
        raise ValueError(f"Contract checks failed for {', '.join(failed)}; see pipeline/contracts_<layer>.json")
    return reports


def graph_load(context: StageContext) -> Mapping[str, object]:
    status = load_and_serve(context.home, context.repository_root, context.release_id, context.release / "graph" / "graph.nt")
    if not status.started:
        if not status.docker_available:
            raise StageSkipped(status.reason)
        raise ValueError(f"Fuseki did not start: {status.reason}")
    gold_ids, _edge_ids = travis_served_ids(context.home, context.quarter, context.release_id)
    answered = system_ids_from_bindings(SparqlStore().select(travis_water_query()))
    if answered != gold_ids:
        raise ValueError("Fuseki Travis County result does not match Gold")
    return {"loaded": status.loaded, "travis_county_water_served": len(answered)}


STAGE_FUNCTIONS: dict[str, Stage] = {
    "validate": validate,
    "promote": promote,
    "silver_water": silver_water,
    "core_water": core_water,
    "release_water": release_water,
    "electric": electric,
    "wastewater": wastewater,
    "gas": gas,
    "cross": cross,
    "assemble": assemble_products,
    "graph_export": graph_export,
    "contracts": contracts,
    "graph_load": graph_load,
}
if tuple(STAGE_FUNCTIONS) != STAGES:
    raise RuntimeError("STAGE_FUNCTIONS must list every pipeline stage in order")
