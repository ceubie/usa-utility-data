import json

import duckdb
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
    assert checks["primary_key:child"]["violations"] == 2
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


def test_rejects_invalid_contracts_and_vocabularies(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pq.write_table(pa.table({"id": ["a"], "sector": ["forbidden"]}), data / "table.parquet")
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    contract = contracts / "table.yaml"
    contract.write_text("table: t\npath: table.parquet\ncolumns: [{name: id, nullable: flase}]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid contract"):
        run_checks(contracts, data)
    contract.write_text("table: t\npath: table.parquet\ncolumns: [{name: id}, {name: id}]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate column"):
        run_checks(contracts, data)
    contract.write_text("table: t\npath: table.parquet\ncolumns: [{name: sector, vocab: sector}]\n", encoding="utf-8")
    vocab = tmp_path / "vocab"
    vocab.mkdir()
    (vocab / "sector.yaml").write_text("- water\n- null\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique strings"):
        run_checks(contracts, data, vocab)


def test_file_checks_do_not_confuse_urls_and_detect_unverifiable_content(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pq.write_table(pa.table({"id": ["a", "b", "c"], "url": ["https://example.org/data", "ABENAKI WATER /LAKELAND", "WDW-PUMP STA. B /EPCOT/MGM"]}), data / "table.parquet")
    (data / "paths.txt").write_text("https://example.org/data\n/tmp/private/example\nsource: /data/releases/first.parquet\nRead from /custom/releases/first.parquet for results\n", encoding="utf-8")
    (data / "opaque.bin").write_bytes(b"opaque")
    with duckdb.connect(str(data / "stored.duckdb")) as con:
        con.execute("CREATE TABLE stored(path VARCHAR)")
        con.execute("INSERT INTO stored VALUES ('C:/private/file'), ('https://example.org/data')")
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "table.yaml").write_text("table: t\npath: table.parquet\ncolumns: [{name: id}]\n", encoding="utf-8")
    checks = {c["name"]: c for c in run_checks(contracts, data)["checks"]}
    assert checks["absolute_paths:table.parquet"]["violations"] == 0
    assert checks["absolute_paths:paths.txt"]["violations"] == 1
    assert checks["possible_absolute_paths:paths.txt"]["violations"] == 2
    assert checks["possible_absolute_paths:table.parquet"]["violations"] == 1
    assert checks["absolute_paths:opaque.bin"]["status"] == "fail"
    assert checks["absolute_paths:stored.duckdb:table:main.stored"]["violations"] == 1


def test_declared_geometry_requires_valid_geoparquet_metadata(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    table = pa.table({"id": ["a"], "shape": [b"wkb"]}).replace_schema_metadata({b"geo": b"junk"})
    pq.write_table(table, data / "table.parquet")
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "table.yaml").write_text("table: t\npath: table.parquet\ncolumns: [{name: shape, type: geometry}]\n", encoding="utf-8")
    checks = {c["name"]: c for c in run_checks(contracts, data)["checks"]}
    assert checks["geoparquet:table.parquet"]["status"] == "fail"
    assert checks["geoparquet:table.parquet"]["reason"].startswith("invalid geo metadata")
