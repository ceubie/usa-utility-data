"""Command line entry point for validation."""

from pathlib import Path

import typer

from utilitydata.checks.runner import run_checks, write_report
from utilitydata.paths import DataPaths
from utilitydata.registry import load_registry

app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
app.add_typer(registry_app, name="registry")


@app.callback()
def main() -> None:
    """Validate utility data against its declared contracts."""


@registry_app.command("validate")
def validate_registry(
    directory: Path = typer.Option(Path("registry/sources"), help="Directory of source YAML files."),
    allow_unreviewed: bool = typer.Option(False, help="Validate drafts without making them eligible for a build."),
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


@app.command()
def check(
    contracts: Path = typer.Option(..., help="Directory of YAML contracts."),
    data: Path = typer.Option(..., help="Data directory relative to UTILITYDATA_HOME."),
    report: Path = typer.Option(Path("check_report.json"), help="Output JSON report."),
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
