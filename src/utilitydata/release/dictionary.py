"""Generate the release data dictionary from the Gold contracts."""

from pathlib import Path

import yaml

from utilitydata.checks.runner import TableContract


def write_dictionary(contract_dir: Path, destination: Path) -> None:
    """Write a markdown dictionary from the Gold contract files."""
    files = sorted(contract_dir.glob("*.yaml"))
    if not files:
        raise ValueError(f"No contracts in {contract_dir.name}")
    lines = [
        "# Data dictionary",
        "",
        "Generated from the Gold contracts. Column names and types are the contract.",
        "",
        "The release is split into `internal/` and `shareable/`.",
        "Unknown and restricted licences stay internal.",
        "A shareable licence is public_domain, public_unrestricted, attribution_required, or cc-by-4.0.",
        "The state and sector scorecard is internal because it describes boundaries of every licence.",
        "",
    ]
    for path in files:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        contract = TableContract.model_validate(loaded)
        lines.append(f"## {contract.table}")
        lines.append("")
        lines.append(f"File: `{contract.path}`.")
        if contract.primary_key:
            lines.append("Primary key: " + ", ".join(contract.primary_key) + ".")
        lines.append("")
        lines.append("| Column | Type | Nullable | Description |")
        lines.append("| --- | --- | --- | --- |")
        for column in contract.columns:
            description = column.description or ""
            kind = column.type or ""
            lines.append(f"| {column.name} | {kind} | {column.nullable} | {description} |")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")
