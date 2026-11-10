import json
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from utilitydata.checks.runner import run_checks, write_report
from utilitydata.cli import app


def test_contract_checks_and_file_checks(tmp_path):
    data = tmp_path / "data"
    contracts = tmp_path / "contracts"
    vocab = tmp_path / "vocab"
    for directory in (data, contracts, vocab):
        directory.mkdir()
    pq.write_table(pa.table({"id": ["one", "two"]}), data / "parent.parquet")
    pq.write_table(pa.table({"id": ["a", "a", "b"], "parent": ["one", "missing", None], "sector": ["water", "other", "water"], "geometry_wkb": [b"a", b"b", b"c"], "location": ["C:/private/file", "ordinary", "ordinary"]}), data / "child.parquet")
    (vocab / "sector.yaml").write_text("- water\n", encoding="utf-8")
    (contracts / "parent.yaml").write_text("table: parent\npath: parent.parquet\nprimary_key: [id]\ncolumns: [{name: id, type: string, nullable: false}]\n", encoding="utf-8")
    (contracts / "child.yaml").write_text("table: child\npath: child.parquet\nprimary_key: [id]\ncolumns:\n  - {name: id, type: string, nullable: false}\n  - {name: parent, references: parent.id}\n  - {name: sector, vocab: sector}\nmin_fill: {parent: 1.0}\n", encoding="utf-8")
    result = run_checks(contracts, data, vocab)
    checks = {c["name"]: c for c in result["checks"]}
    assert result["status"] == "fail"
    assert checks["primary_key:child"]["violations"] == 1
    assert checks["foreign_key:child.parent->parent.id"]["violations"] == 1
    assert checks["vocab:child.sector"]["violations"] == 1
    assert checks["min_fill:child.parent"]["filled"] == 2
    assert checks["geoparquet:child.parquet"]["violations"] == 1
    assert checks["absolute_paths:child.parquet"]["violations"] == 1
    output = tmp_path / "report.json"
    write_report(output, result)
    assert json.loads(output.read_text())["status"] == "fail"
    assert "C:/private/file" not in output.read_text()


def test_missing_contract_column_fails_closed(tmp_path):
    pq.write_table(pa.table({"id": ["one"]}), tmp_path / "table.parquet")
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "table.yaml").write_text("table: t\npath: table.parquet\ncolumns: [{name: absent}]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing column"):
        run_checks(contracts, tmp_path)


def test_cli_check_returns_failure_for_violations(tmp_path, monkeypatch):
    home = tmp_path / "home"
    data = home / "legacy"
    data.mkdir(parents=True)
    pq.write_table(pa.table({"id": ["same", "same"]}), data / "table.parquet")
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "table.yaml").write_text("table: t\npath: table.parquet\nprimary_key: [id]\ncolumns: [{name: id}]\n", encoding="utf-8")
    monkeypatch.setenv("UTILITYDATA_HOME", str(home))
    report = tmp_path / "report.json"
    result = CliRunner().invoke(app, ["check", "--contracts", str(contracts), "--data", "legacy", "--report", str(report)])
    assert result.exit_code == 1
    assert json.loads(report.read_text())["status"] == "fail"
