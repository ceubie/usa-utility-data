"""Command line entry point for validation."""

import json
from pathlib import Path
from typing import Annotated

import typer

from utilitydata.bronze.snapshot import freeze, inventory
from utilitydata.checks.runner import run_checks, write_report
from utilitydata.paths import DataPaths
from utilitydata.registry import load_registry

app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
app.add_typer(registry_app, name="registry")
snapshot_app = typer.Typer(no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")


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
        sources = load_registry(directory, require_reviewed=not allow_unreviewed, raw_root=paths.raw)
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
    """Copy and hash a fully reviewed collection as an immutable snapshot."""
    try:
        paths = DataPaths.from_environment()
        result = freeze(quarter, home=paths.home, raw_root=paths.raw, registry_dir=directory, unused_path=unused)
    except (OSError, ValueError) as exc:
        typer.echo(f"Snapshot failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Snapshot frozen: {result}")


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
