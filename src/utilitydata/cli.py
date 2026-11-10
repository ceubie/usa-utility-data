"""Command line entry point for validation."""

from pathlib import Path

import typer

from utilitydata.checks.runner import run_checks, write_report
from utilitydata.paths import DataPaths

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Validate utility data against its declared contracts."""


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
