"""Command line entry point for validation."""

import json
from pathlib import Path
from typing import Annotated

import duckdb
import pandas as pd
import typer

from utilitydata.bronze.refresh import refresh as refresh_sources
from utilitydata.bronze.snapshot import freeze, inventory
from utilitydata.checks.runner import run_checks, write_report
from utilitydata.core.build import build_water_core
from utilitydata.core.config import DEFAULT_QUARTER, DEFAULT_RELEASE_ID
from utilitydata.cross.build import build_cross_sector
from utilitydata.electric.build import build_electric
from utilitydata.gas.build import build_gas
from utilitydata.geography import build_reference, download_census
from utilitydata.gold.build import build_water_gold
from utilitydata.gold.schema import TRUTH_COLUMNS
from utilitydata.graph.export_nt import write_ntriples
from utilitydata.graph.export_tables import export_graph, travis_served_ids
from utilitydata.graph.fuseki import load_and_serve
from utilitydata.graph.qlever import load_and_serve as load_qlever
from utilitydata.graph.store import (
    SparqlStore,
    system_ids_from_bindings,
    travis_water_query,
)
from utilitydata.paths import DataPaths
from utilitydata.pipeline import StageContext, next_stage, release_dir, run_pipeline
from utilitydata.registry import load_registry
from utilitydata.release.accuracy import load_truth
from utilitydata.release.build import build_water_release
from utilitydata.release.calibration import (
    require_measurement_record,
    sample_rows,
    score_labels,
)
from utilitydata.release.reports import reject_absolute_paths, write_manifest
from utilitydata.silver.boundaries import build_water_silver
from utilitydata.stages import STAGE_FUNCTIONS
from utilitydata.wastewater.build import build_wastewater

_WRITE_RELEASE_HELP = "An open release id. A finished or sealed release is refused."

app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
app.add_typer(registry_app, name="registry")
snapshot_app = typer.Typer(no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")
reference_app = typer.Typer(no_args_is_help=True)
app.add_typer(reference_app, name="reference")
silver_app = typer.Typer(no_args_is_help=True)
app.add_typer(silver_app, name="silver")
core_app = typer.Typer(no_args_is_help=True)
app.add_typer(core_app, name="core")
gold_app = typer.Typer(no_args_is_help=True)
app.add_typer(gold_app, name="gold")
release_app = typer.Typer(no_args_is_help=True)
app.add_typer(release_app, name="release")
graph_app = typer.Typer(no_args_is_help=True)
app.add_typer(graph_app, name="graph")


@app.callback()
def main() -> None:
    """Validate utility data against its declared contracts."""


@registry_app.command("validate")
def validate_registry(
    directory: Annotated[Path, typer.Option(help="Directory of source YAML files.")] = Path("registry/sources"),
    allow_unreviewed: Annotated[bool, typer.Option(help="Validate drafts without making them eligible for a build.")] = False,
) -> None:
    """Validate source declarations and reviewed field mappings."""
    try:
        paths = DataPaths.from_environment()
        sources = load_registry(
            directory,
            require_reviewed=not allow_unreviewed,
            raw_root=paths.raw,
            home_root=paths.home,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Registry invalid: {exc}", err=True)
        raise typer.Exit(1) from exc
    reviewed = sum(source.reviewed for source in sources)
    typer.echo(f"Registry valid: {len(sources)} sources, {reviewed} reviewed, {len(sources) - reviewed} drafts")


@registry_app.command("coverage")
def registry_coverage(
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
    unused: Annotated[Path, typer.Option()] = Path("registry/unused.yaml"),
    report: Annotated[Path, typer.Option()] = Path("registry/coverage_report.json"),
) -> None:
    """List raw files without an explicit registry disposition."""
    try:
        paths = DataPaths.from_environment()
        sources = load_registry(directory, require_reviewed=False, raw_root=paths.raw)
        owners, omitted, missing = inventory(paths.raw, sources, unused)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"assigned": len(owners), "unused": len(omitted), "unassigned": missing}, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        typer.echo(f"Coverage check failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{len(owners)} assigned; {len(omitted)} unused; {len(missing)} unassigned; report: {report}")
    if missing:
        raise typer.Exit(1)


@snapshot_app.command("freeze")
def freeze_snapshot(
    quarter: str,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
    unused: Annotated[Path, typer.Option()] = Path("registry/unused.yaml"),
) -> None:
    """Copy and hash the collection. Draft sources are carried as not buildable."""
    try:
        paths = DataPaths.from_environment()
        result = freeze(quarter, home=paths.home, raw_root=paths.raw, registry_dir=directory, unused_path=unused)
    except (OSError, ValueError) as exc:
        typer.echo(f"Snapshot failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Snapshot frozen: {result}")


@app.command("refresh")
def refresh_command(
    snapshot: Annotated[str, typer.Option("--snapshot", help="Quarter to refresh, for example 2027-Q1.")],
    previous: Annotated[str, typer.Option("--previous")] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    source: Annotated[list[str] | None, typer.Option("--source", help="Refresh this source id. Repeat the option to name more than one.")] = None,
) -> None:
    """Refresh registry sources. A named source stays draft and is not copied into the release."""
    try:
        paths = DataPaths.from_environment()
        repository = Path(__file__).resolve().parents[2]
        result = refresh_sources(
            snapshot,
            previous=previous,
            home=paths.home,
            raw_root=paths.raw,
            registry_dir=directory,
            script_dir=None if dry_run else repository / "collection",
            dry_run=dry_run,
            limit=limit,
            source_ids=tuple(source) if source else None,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Refresh failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    matched = sum(source.hashes_match for source in result.sources)
    carried = sum(source.action == "carried_forward" for source in result.sources)
    typer.echo(
        f"refresh {result.snapshot}: {len(result.sources)} sources; hashes match {matched}; "
        f"carried forward {carried}; report: refresh/{result.snapshot}/triage_report.md"
    )


@reference_app.command("download")
def reference_download(
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Download Census reference files into the data root."""
    try:
        download_census(DataPaths.from_environment().home, directory)
    except (OSError, ValueError) as exc:
        typer.echo(f"Reference download failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("Census reference files are in the data root")


@reference_app.command("build")
def reference_build_command(
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build reference geography tables from the Census files in the data root."""
    try:
        summary = build_reference(DataPaths.from_environment().home, directory, quarter=quarter)
    except (OSError, ValueError) as exc:
        typer.echo(f"Reference build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"ref_block rows: {summary['ref_block_rows']}; 50 states + DC pop20: {summary['pop20_states_dc']}; "
        f"counties: {summary['ref_county_rows']}; places: {summary['ref_place_rows']}; "
        f"government units: {summary['ref_government_unit_rows']}; "
        f"2020 place codes absent from the 2025 place file: {summary['block_place_codes_outside_2025']}"
    )


@silver_app.command("water")
def silver_water(
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build drinking-water Silver from reviewed sources in one frozen snapshot."""
    try:
        summary = build_water_silver(DataPaths.from_environment().home, directory, quarter=quarter)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Water Silver build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    tables = summary["tables"]
    authority = summary["authority_counts"]["CWS"]
    typer.echo(
        f"boundary assertions: {tables['boundary_assertion']}; rejects: {tables['rejects']}; "
        f"CWS federal_submitted: {authority.get('federal_submitted')}; "
        f"CWS federal_modeled: {authority.get('federal_modeled')}; "
        f"PWSID 090600058: {summary['pwsid_090600058']}; "
        f"GeoParquet metadata: {summary['geoparquet_metadata']}"
    )


@core_app.command("water")
def core_water(
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build the drinking-water core from reviewed Silver for one quarter."""
    try:
        summary = build_water_core(DataPaths.from_environment().home, directory, quarter=quarter)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Water core build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"systems: {summary['system_rows']}; service areas: {summary['service_area_rows']}; "
        f"decisions: {summary['match_decision_rows']}; organizations: {summary['organization_rows']}; "
        f"review queue assertions: {summary['review_queue_assertions']}; methods: {summary['method_counts']}"
    )


@gold_app.command("water")
def gold_water(
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
    rebuild_coverage: Annotated[bool, typer.Option()] = True,
) -> None:
    """Build drinking-water Gold tables for one quarter."""
    try:
        summary = build_water_gold(
            DataPaths.from_environment().home,
            directory,
            quarter=quarter,
            rebuild_coverage=rebuild_coverage,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Water Gold build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"territories: {summary['territories_water']}; facilities: {summary['water_facilities']}; "
        f"search rows: {summary['entity_search']['rows']}"
    )


@release_app.command("water")
def release_water(
    release_id: Annotated[str, typer.Option("--release-id", help=_WRITE_RELEASE_HELP)],
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
    rebuild_coverage: Annotated[bool, typer.Option()] = True,
) -> None:
    """Build the first drinking-water release under the data root."""
    try:
        repository_root = Path(__file__).resolve().parents[2]
        summary = build_water_release(
            DataPaths.from_environment().home,
            directory,
            repository_root,
            quarter=quarter,
            release_id=release_id,
            rebuild_coverage=rebuild_coverage,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Water release failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"release: {summary['release']}; Travis County served systems: {summary['travis_county_served_systems']}; "
        f"verified truth rows: {summary['truth']['verified_rows']}"
    )


@app.command("electric")
def electric_build(
    release_id: Annotated[str, typer.Option("--release-id", help=_WRITE_RELEASE_HELP)],
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build the electric sector beside the drinking-water release."""
    try:
        repository_root = Path(__file__).resolve().parents[2]
        summary = build_electric(
            DataPaths.from_environment().home,
            directory,
            repository_root,
            quarter=quarter,
            release_id=release_id,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Electric build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    agreement = summary["county_agreement"]
    typer.echo(
        f"active retail: {summary['active_retail']}; territories: {summary['territories_electric']}; "
        f"county agreement {agreement['utilities_equal']}/{agreement['utilities_compared']}; "
        f"verified truth rows: {summary['verified_truth_rows']}"
    )


@app.command("wastewater")
def wastewater_build(
    release_id: Annotated[str, typer.Option("--release-id", help=_WRITE_RELEASE_HELP)],
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build the wastewater sector beside the existing release."""
    try:
        repository_root = Path(__file__).resolve().parents[2]
        summary = build_wastewater(
            DataPaths.from_environment().home,
            directory,
            repository_root,
            quarter=quarter,
            release_id=release_id,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Wastewater build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"systems: {summary['systems']}; unlinked zones: {summary['unlinked_zones']}/{summary['local_zones']}; "
        f"sewershed systems missing population: {summary['sewershed_systems_missing_population']}"
    )


@app.command("gas")
def gas_build(
    release_id: Annotated[str, typer.Option("--release-id", help=_WRITE_RELEASE_HELP)],
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build the natural-gas sector beside the existing release."""
    try:
        repository_root = Path(__file__).resolve().parents[2]
        summary = build_gas(
            DataPaths.from_environment().home,
            directory,
            repository_root,
            quarter=quarter,
            release_id=release_id,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Gas build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"systems: {summary['systems']}; EIA-176 links: {summary['eia_links']}; "
        f"zones linked: {summary['zones_linked']}"
    )


@app.command("cross")
def cross_build(
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Build cross-sector organizations, facilities, and networks."""
    try:
        repository_root = Path(__file__).resolve().parents[2]
        summary = build_cross_sector(
            DataPaths.from_environment().home,
            directory,
            repository_root,
            quarter=quarter,
        )
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Cross-sector build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    wind = summary["michigan_wind"]
    typer.echo(
        f"govid links: {summary['govid_links']}; facilities: {summary['facilities']}; "
        f"units: {summary['units']}; relationships: {summary['relationships']}; "
        f"michigan wind equal: {wind.get('equal')}"
    )


@graph_app.command("export")
def graph_export(
    release_id: Annotated[str, typer.Option("--release-id", help=_WRITE_RELEASE_HELP)],
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
    write_nt: Annotated[bool, typer.Option("--nt/--no-nt")] = True,
) -> None:
    """Export node and edge tables, then N-Triples, for one release."""
    try:
        home = DataPaths.from_environment().home
        repository_root = Path(__file__).resolve().parents[2]
        summary = export_graph(
            home,
            repository_root,
            quarter=quarter,
            release_id=release_id,
            registry_dir=directory,
        )
        triples = None
        release = release_dir(home, release_id)
        if write_nt:
            triples = write_ntriples(release / "graph")
        gold_ids, edge_ids = travis_served_ids(home, quarter, release_id)
        if gold_ids != edge_ids:
            raise ValueError("Travis County water systems do not match Gold")
        if (release / "release_manifest.json").is_file():
            write_manifest(release, home, quarter, home / "gold" / quarter, repository_root)
            reject_absolute_paths(release)
    except (OSError, ValueError, TypeError, duckdb.Error) as exc:
        typer.echo(f"Graph export failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    triple_count = triples["triples"] if isinstance(triples, dict) else "not written"
    typer.echo(
        f"release {summary['release']}: nodes {summary['node_rows']}; edges {summary['edge_rows']}; "
        f"Travis County water served {len(gold_ids)}; triples {triple_count}"
    )


@graph_app.command("load")
def graph_load(
    quarter: Annotated[str, typer.Option()] = DEFAULT_QUARTER,
    release_id: Annotated[str, typer.Option()] = DEFAULT_RELEASE_ID,
    engine: Annotated[str, typer.Option("--engine")] = "fuseki",
) -> None:
    """Load the N-Triples export. Fuseki is the default until QLever parity is shown."""
    try:
        home = DataPaths.from_environment().home
        repository_root = Path(__file__).resolve().parents[2]
        nt_path = release_dir(home, release_id) / "graph" / "graph.nt"
        if not nt_path.is_file():
            raise ValueError("N-Triples export is missing")
        if engine == "fuseki":
            status = load_and_serve(home, repository_root, release_id, nt_path)
            store_url = None
        elif engine == "qlever":
            status = load_qlever(home, release_id, nt_path)
            store_url = status.query_url
        else:
            raise ValueError("Graph engine must be fuseki or qlever")
        gold_ids, edge_ids = travis_served_ids(home, quarter, release_id)
        answered_by = "DuckDB"
        if status.started:
            store = SparqlStore(url=store_url) if store_url else SparqlStore()
            answered = system_ids_from_bindings(store.select(travis_water_query()))
            if answered != gold_ids:
                raise ValueError(f"{engine} Travis County result does not match Gold")
            answered_by = engine
        if edge_ids != gold_ids:
            raise ValueError("Edge table Travis County result does not match Gold")
    except (OSError, ValueError, TypeError, duckdb.Error) as exc:
        typer.echo(f"Graph load failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"{engine} started: {status.started}; loaded: {status.loaded}; "
        f"Travis County answered by {answered_by}; {status.reason}"
    )
    if not status.started:
        load_command = getattr(status, "load_command", "")
        server_command = getattr(status, "server_command", "")
        if load_command:
            typer.echo(load_command)
        if server_command:
            typer.echo(server_command)
        if status.docker_available and engine == "fuseki":
            raise typer.Exit(1)


calibrate_app = typer.Typer(no_args_is_help=True)
app.add_typer(calibrate_app, name="calibrate")
truth_app = typer.Typer(no_args_is_help=True)
app.add_typer(truth_app, name="truth")
pipeline_app = typer.Typer(no_args_is_help=True)
app.add_typer(pipeline_app, name="pipeline")


@calibrate_app.command("sample")
def calibrate_sample(
    decisions: Annotated[Path, typer.Option("--decisions")],
    method_column: Annotated[str, typer.Option("--method-column")] = "method",
    size: Annotated[int, typer.Option("--size")] = 200,
    output: Annotated[Path, typer.Option("--output")] = Path("registry/calibration/sample.csv"),
) -> None:
    """Write an unlabelled seeded sample. This command does not add truth rows."""
    frame = pd.read_csv(decisions, dtype=str, keep_default_na=False)
    sampled = sample_rows(frame, method_column=method_column, size=size)
    output.parent.mkdir(parents=True, exist_ok=True)
    sampled.to_csv(output, index=False)
    typer.echo(f"unlabelled sample rows: {len(sampled)}; wrote {output}")


@calibrate_app.command("score")
def calibrate_score(
    labels: Annotated[Path, typer.Option("--labels")],
) -> None:
    """Score labelled rows. This command never changes a calibrated flag."""
    frame = pd.read_csv(labels, dtype=str, keep_default_na=False)
    scored = score_labels(frame)
    require_measurement_record(Path("registry/calibration/measurements.csv"))
    for row in scored.itertuples(index=False):
        typer.echo(
            f"{row.method}: precision {row.precision:.3f} "
            f"interval {row.interval_low:.3f}-{row.interval_high:.3f} on {row.rows} rows"
        )


@truth_app.command("check")
def truth_check(
    directory: Annotated[Path, typer.Option()] = Path("registry/truth"),
) -> None:
    """Validate truth files. A verified_by value is refused because nothing is verified."""
    files = sorted(directory.glob("*.csv"))
    if not files:
        typer.echo("No truth files", err=True)
        raise typer.Exit(1)
    for path in files:
        frame = load_truth(path)
        missing = [name for name in TRUTH_COLUMNS if name not in frame.columns]
        if missing:
            typer.echo(f"Truth file is missing columns: {missing[0]}", err=True)
            raise typer.Exit(1)
        labelled = frame["verified_by"].fillna("").astype(str).str.strip().ne("")
        if bool(labelled.any()):
            typer.echo(f"{path.name} has a verified_by value; nothing is marked verified", err=True)
            raise typer.Exit(1)
        typer.echo(f"{path.name}: {len(frame)} rows, none verified")


@pipeline_app.command("run")
def pipeline_run(
    release_id: Annotated[str, typer.Option("--release-id", help="A new release id, or an open one with --resume.")],
    quarter: Annotated[str, typer.Option("--quarter")] = DEFAULT_QUARTER,
    from_stage: Annotated[str | None, typer.Option("--from-stage")] = None,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    directory: Annotated[Path, typer.Option()] = Path("registry/sources"),
) -> None:
    """Run every release stage that is not done. Status is kept in the release folder."""
    try:
        paths = DataPaths.from_environment()
        context = StageContext(
            home=paths.home,
            raw=paths.raw,
            repository_root=Path(__file__).resolve().parents[2],
            registry_dir=directory,
            quarter=quarter,
            release_id=release_id,
        )
        status = run_pipeline(context, STAGE_FUNCTIONS, resume=resume, from_stage=from_stage, echo=typer.echo)
    except Exception as exc:
        typer.echo(f"Pipeline stopped: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    remaining = next_stage(status)
    if remaining is None:
        typer.echo(f"{release_id} pipeline is complete and sealed")
        return
    reason = status["reasons"].get(remaining, "")
    typer.echo(f"{release_id} is open at {remaining}: {reason}. Run again with --resume.")


@app.command()
def check(
    contracts: Annotated[Path, typer.Option(help="Directory of YAML contracts.")],
    data: Annotated[Path, typer.Option(help="Data directory relative to UTILITYDATA_HOME.")],
    report: Annotated[Path, typer.Option(help="Output JSON report.")] = Path("check_report.json"),
) -> None:
    """Check tables and files, returning a non-zero exit on failure."""
    try:
        home = DataPaths.from_environment().home
        if data.is_absolute() or ".." in data.parts:
            raise ValueError("--data must be relative to UTILITYDATA_HOME")
        result = run_checks(contracts, home / data)
        write_report(report, result)
    except (OSError, ValueError) as exc:
        typer.echo(f"Check failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"{result['status']}: {len(result['checks'])} checks; report: {report}")
    if result["status"] != "pass":
        raise typer.Exit(1)
