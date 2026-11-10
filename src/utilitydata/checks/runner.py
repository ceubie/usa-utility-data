"""Run declarative table contracts and inspect legacy release files."""

import json
import re
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import yaml

ABSOLUTE_PATH = r"(^/|[A-Za-z]:[\\/]|\\\\)"
TYPE_NAMES = {"string": "VARCHAR", "integer": "BIGINT", "float": "DOUBLE", "boolean": "BOOLEAN", "date": "DATE", "binary": "BLOB"}


def ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes data directory: {relative}")
    return path


def _query_check(con, checks, name, query, params=(), group_by=None):
    count = con.execute(f"SELECT count(*) FROM ({query}) AS violations", params).fetchone()[0]
    result = {"name": name, "status": "fail" if count else "pass", "violations": count}
    if count and group_by:
        column = ident(group_by)
        rows = con.execute(f"SELECT {column}, count(*) FROM ({query}) AS violations GROUP BY 1 ORDER BY 2 DESC", params).fetchall()
        result["groups"] = [{"value": str(value), "violations": n} for value, n in rows]
    checks.append(result)


def _load_contracts(directory):
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise ValueError(f"No contracts in {directory}")
    contracts = {}
    for path in files:
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict) or not contract.get("table") or not contract.get("path"):
            raise ValueError(f"Invalid contract: {path.name}")
        if contract["table"] in contracts:
            raise ValueError(f"Duplicate contract: {contract['table']}")
        contracts[contract["table"]] = contract
    return contracts


def _check_files(con, root, checks):
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(root).as_posix()
        if file.suffix.lower() == ".parquet":
            schema = pq.read_schema(file)
            geometry_columns = [n for n in schema.names if n.lower() in {"geometry", "geometry_wkb"}]
            if geometry_columns:
                missing = b"geo" not in (schema.metadata or {})
                checks.append({"name": f"geoparquet:{rel}", "status": "fail" if missing else "pass", "violations": int(missing)})
            text_columns = [field.name for field in schema if str(field.type) in {"string", "large_string"}]
            if text_columns:
                condition = " OR ".join(f"regexp_matches({ident(col)}, ?)" for col in text_columns)
                count = con.execute(f"SELECT count(*) FROM read_parquet(?) WHERE {condition}", [str(file), *([ABSOLUTE_PATH] * len(text_columns))]).fetchone()[0]
                checks.append({"name": f"absolute_paths:{rel}", "status": "fail" if count else "pass", "violations": count})
        elif file.suffix.lower() == ".duckdb":
            db = duckdb.connect(str(file), read_only=True)
            try:
                views = db.execute("SELECT view_name, sql FROM duckdb_views() WHERE NOT internal").fetchall()
            finally:
                db.close()
            # SQL may contain paths inside string literals, not only at the start.
            bad = [name for name, sql in views if re.search(r"(?:[A-Za-z]:[\\/]|['\"]/|\\\\)", sql or "")]
            checks.append({"name": f"absolute_paths:{rel}:views", "status": "fail" if bad else "pass", "violations": len(bad), "views": bad})
        elif file.suffix.lower() in {".json", ".sql", ".yaml", ".yml", ".csv", ".txt", ".md"}:
            content = file.read_text(encoding="utf-8")
            count = len(re.findall(r"(?:[A-Za-z]:[\\/]|['\"]/|\\\\)", content))
            checks.append({"name": f"absolute_paths:{rel}", "status": "fail" if count else "pass", "violations": count})


def run_checks(contract_dir: Path, data_dir: Path, vocab_dir: Path = Path("registry/vocab")) -> dict:
    contracts = _load_contracts(contract_dir)
    if not data_dir.is_dir():
        raise ValueError(f"Data directory does not exist: {data_dir}")
    checks = []
    con = duckdb.connect()
    try:
        for name, contract in contracts.items():
            path = _inside(data_dir, contract["path"])
            if not path.is_file():
                raise ValueError(f"Missing table file: {contract['path']}")
            # Parameter binding is unavailable in CREATE VIEW.
            quoted_path = str(path).replace("'", "''")
            con.execute(f"CREATE VIEW {ident(name)} AS SELECT * FROM read_parquet('{quoted_path}')")
        for name, contract in contracts.items():
            table = ident(name)
            actual = {row[0]: row[1] for row in con.execute(f"DESCRIBE {table}").fetchall()}
            cols = {c["name"]: c for c in contract.get("columns", [])}
            for col, spec in cols.items():
                if col not in actual:
                    raise ValueError(f"Missing column {name}.{col}")
                if spec.get("type"):
                    expected = TYPE_NAMES.get(spec["type"])
                    if expected is None:
                        raise ValueError(f"Unsupported type {spec['type']}")
                    if actual[col] != expected:
                        checks.append({"name": f"type:{name}.{col}", "status": "fail", "violations": 1, "expected": expected, "actual": actual[col]})
                    else:
                        checks.append({"name": f"type:{name}.{col}", "status": "pass", "violations": 0})
                column = ident(col)
                if spec.get("nullable") is False:
                    _query_check(con, checks, f"not_null:{name}.{col}", f"SELECT * FROM {table} WHERE {column} IS NULL")
                if spec.get("references"):
                    ref = spec["references"].split(".")
                    if len(ref) != 2 or ref[0] not in contracts:
                        raise ValueError(f"Unknown reference: {spec['references']}")
                    query = f"SELECT child.* FROM {table} child WHERE child.{column} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {ident(ref[0])} parent WHERE parent.{ident(ref[1])} = child.{column})"
                    _query_check(con, checks, f"foreign_key:{name}.{col}->{spec['references']}", query, group_by=spec.get("group_by"))
                if spec.get("vocab"):
                    vocab_path = _inside(vocab_dir, spec["vocab"] + ".yaml")
                    values = yaml.safe_load(vocab_path.read_text(encoding="utf-8"))
                    if not isinstance(values, list) or not values:
                        raise ValueError(f"Vocabulary must be a nonempty list: {vocab_path.name}")
                    placeholders = ",".join("?" for _ in values)
                    _query_check(con, checks, f"vocab:{name}.{col}", f"SELECT * FROM {table} WHERE {column} IS NOT NULL AND {column} NOT IN ({placeholders})", values)
            key = contract.get("primary_key", [])
            if key:
                keys = ", ".join(ident(x) for x in key)
                _query_check(con, checks, f"primary_key:{name}", f"SELECT {keys} FROM {table} GROUP BY {keys} HAVING count(*) > 1 OR " + " OR ".join(f"{ident(x)} IS NULL" for x in key))
            for col, minimum in contract.get("min_fill", {}).items():
                if col not in actual or not 0 <= minimum <= 1:
                    raise ValueError(f"Invalid fill constraint: {name}.{col}")
                total, filled = con.execute(f"SELECT count(*), count({ident(col)}) FROM {table}").fetchone()
                rate = filled / total if total else 0.0
                checks.append({"name": f"min_fill:{name}.{col}", "status": "pass" if rate >= minimum else "fail", "violations": total - filled, "rows": total, "filled": filled, "fill_rate": rate, "minimum": minimum})
        _check_files(con, data_dir, checks)
    finally:
        con.close()
    return {"status": "fail" if any(x["status"] == "fail" for x in checks) else "pass", "checks": checks}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
