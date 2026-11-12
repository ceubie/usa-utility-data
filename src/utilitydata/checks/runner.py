"""Run declarative table contracts and inspect legacy release files."""

import json
import re
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

ABSOLUTE_PATH = (
    r"(?m)(^|[^A-Za-z0-9+./:-])([A-Za-z]:[\\/]|\\\\)"
    r"|^/[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$"
    r"|(^|[='\"(])/(?:[A-Za-z0-9._~-]+/)+[A-Za-z0-9._~-]+"
    r"|(^|[\s='\"(])/(?:tmp|home|etc|var|usr|root|opt|mnt|srv|private|Users|Volumes)(/|[\s\"',;)]|$)"
)
POSSIBLE_POSIX_PATH = r"(?m)(^|[\s='\"(])/(?:[A-Za-z0-9._~-]+/)+[A-Za-z0-9._~-]+"
TYPE_NAMES = {"string": "VARCHAR", "integer": "BIGINT", "float": "DOUBLE", "boolean": "BOOLEAN", "date": "DATE", "binary": "BLOB"}

# Narrowly scoped reviewed exceptions for inspected upstream SDWA and SEC 10-K entity names
# containing slashes (per WP1 review gate follow-through). Scoped by (filename, column, exact_value).
REVIEWED_PATH_EXCEPTIONS: dict[tuple[str, str], frozenset[str]] = {
    ("entity_search.parquet", "label"): frozenset({"WDW-PUMP STA. B /EPCOT/MGM"}),
    ("system.parquet", "name"): frozenset({"WDW-PUMP STA. B /EPCOT/MGM"}),
    ("organization.parquet", "name"): frozenset({"WDW-PUMP STA. B /EPCOT/MGM"}),
    ("organization.parquet", "name_norm"): frozenset({"wdw-pump sta. b /epcot/mgm"}),
    ("water_facilities.parquet", "facility_name"): frozenset({
        "/I",
        "4 /1HP/20GPM",
        "6 /146/66-74'",
        "BRW 1 /1/2' FROM PH",
        "BRW 2 /UPPER/35' N OF MCLEAN CABIN",
        "BRW 2 /WING/HOLLOW WELL//INACTIVE",
        "BRW 33 /APW3/1070' ENE OF ANGLE POND PH",
        "CAUSTIC /HYPO/FILTRATION",
        "GPW 1 /1/4 MILE E OF PS",
        "SPR /1/4 MILE BEHIND FARMHOUSE ON HILL",
        "WELL 2 TP (MERGED /0108006--07/15/99)",
        "WELL 2/6 /114'/135/70GPM",
        "WELL 3 FISHER /ARTS/2 CABINS- AA818885",
    }),
    ("facility.parquet", "name"): frozenset({
        "/I",
        "4 /1HP/20GPM",
        "6 /146/66-74'",
        "BRW 1 /1/2' FROM PH",
        "BRW 2 /UPPER/35' N OF MCLEAN CABIN",
        "BRW 2 /WING/HOLLOW WELL//INACTIVE",
        "BRW 33 /APW3/1070' ENE OF ANGLE POND PH",
        "CAUSTIC /HYPO/FILTRATION",
        "GPW 1 /1/4 MILE E OF PS",
        "SPR /1/4 MILE BEHIND FARMHOUSE ON HILL",
        "WELL 2 TP (MERGED /0108006--07/15/99)",
        "WELL 2/6 /114'/135/70GPM",
        "WELL 3 FISHER /ARTS/2 CABINS- AA818885",
    }),
    ("facility.parquet", "name_norm"): frozenset({
        "/i",
        "4 /1hp/20gpm",
        "6 /146/66-74'",
        "brw 1 /1/2' from ph",
        "brw 2 /upper/35' n of mclean cabin",
        "brw 2 /wing/hollow well//inactive",
        "brw 33 /apw3/1070' ene of angle pond ph",
        "caustic /hypo/filtration",
        "gpw 1 /1/4 mile e of ps",
        "spr /1/4 mile behind farmhouse on hill",
        "well 2 tp (merged /0108006--07/15/99)",
        "well 2/6 /114'/135/70gpm",
        "well 3 fisher /arts/2 cabins- aa818885",
    }),
    ("organization_relationship.parquet", "related_name"): frozenset({
        "navistar international corp /de/new",
        "west coast bancorp /new/or/",
    }),
    ("organization_relationship.parquet", "subject_name"): frozenset({
        "arthur s. wolcott /s/kraig h. kayser president",
        "communicaitons company l.p. (/10/ucom,)inc",
        "devra a. bevona /s/jeffrey l. van riper",
        "edward o. gaylord /s/g. brymer humphreys",
        "g. brymer humphreys /s/michael a. schaeffer",
        "geo /del/r/02, inc",
        "gregory john brand /7/limited liability",
        "michael a. schaeffer /s/susan w. stuart",
        "ugti /d.b.a./underground",
    }),
}


class ColumnContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    type: str | None = None
    nullable: StrictBool = True
    description: str | None = None
    references: str | None = None
    vocab: str | None = None
    group_by: str | None = None

    @field_validator("type")
    @classmethod
    def valid_type(cls, value):
        if value is not None and value not in {*TYPE_NAMES, "geometry"}:
            raise ValueError(f"Unsupported type: {value}")
        return value


class TableContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    table: str = Field(min_length=1)
    path: str = Field(min_length=1)
    primary_key: list[str] = Field(default_factory=list)
    columns: list[ColumnContract] = Field(default_factory=list)
    min_fill: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_columns(self):
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate column declarations")
        if len(self.primary_key) != len(set(self.primary_key)):
            raise ValueError("Duplicate primary-key columns")
        if any(not 0 <= value <= 1 for value in self.min_fill.values()):
            raise ValueError("Fill rates must be between 0 and 1")
        return self


def ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes data directory: {relative}")
    return path


def _query_check(con, checks, name, query, params=(), group_by=None):
    count = con.execute(f"SELECT count(*) FROM ({query}) AS violations", params).fetchone()[0]
    result = {"name": name, "status": "fail" if count else "pass", "violations": count, "query": query}
    if params:
        result["parameters"] = list(params)
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
        try:
            contract = TableContract.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).model_dump(exclude_none=True)
        except ValueError as exc:
            raise ValueError(f"Invalid contract {path.name}: {exc}") from exc
        if contract["table"] in contracts:
            raise ValueError(f"Duplicate contract: {contract['table']}")
        contracts[contract["table"]] = contract
    return contracts


def _geo_error(schema, required):
    raw = (schema.metadata or {}).get(b"geo")
    if raw is None:
        return "missing geo metadata"
    try:
        geo = json.loads(raw)
        columns = geo["columns"]
        primary = geo["primary_column"]
        if not isinstance(geo["version"], str) or not geo["version"]:
            raise ValueError("missing version")
        if not isinstance(columns, dict) or primary not in columns:
            raise ValueError("invalid primary geometry column")
        for name in required | {primary}:
            info = columns[name]
            if name not in schema.names or not isinstance(info, dict):
                raise ValueError("geometry column missing from schema")
            if info.get("encoding") not in {"WKB", "point", "linestring", "polygon", "multipoint", "multilinestring", "multipolygon"}:
                raise ValueError("missing or unsupported geometry encoding")
            if not isinstance(info.get("geometry_types"), list):
                raise TypeError("missing geometry types")
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
        return f"invalid geo metadata: {exc}"
    return None


def _col_expr(file_name: str | None, col: str) -> str:
    allowed = REVIEWED_PATH_EXCEPTIONS.get((file_name or "", col))
    base = f"CAST({ident(col)} AS VARCHAR)"
    if not allowed:
        return base
    literals = ", ".join("'" + val.replace("'", "''") + "'" for val in sorted(allowed))
    return f"(CASE WHEN {base} IN ({literals}) THEN NULL ELSE {base} END)"


def _path_counts(con, relation, columns, params=(), *, file_name: str | None = None):
    """Count certain paths and ambiguous multi-component Unix-like values."""
    certain = " OR ".join(f"coalesce(regexp_matches({_col_expr(file_name, col)}, ?), false)" for col in columns)
    possible = " OR ".join(f"coalesce(regexp_matches({_col_expr(file_name, col)}, ?), false)" for col in columns)
    sql = f"SELECT count(*) FILTER (WHERE {certain}), count(*) FILTER (WHERE ({possible}) AND NOT ({certain})) FROM {relation}"
    return con.execute(sql, [*([ABSOLUTE_PATH] * len(columns)), *([POSSIBLE_POSIX_PATH] * len(columns)), *([ABSOLUTE_PATH] * len(columns)), *params]).fetchone()


def _record_path_counts(checks, name, confirmed, candidates):
    checks.append({"name": f"absolute_paths:{name}", "status": "fail" if confirmed else "pass", "violations": confirmed})
    if candidates:
        checks.append({"name": f"possible_absolute_paths:{name}", "status": "fail", "violations": candidates, "reason": "ambiguous slash-containing values require review"})


def _check_files(con, root, checks, geometries):
    text_suffixes = {".json", ".jsonl", ".sql", ".yaml", ".yml", ".csv", ".txt", ".md", ".ttl", ".nt", ".rq", ".toml", ".xml", ".html", ".js", ".ts", ".css"}
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(root).as_posix()
        if any(part.startswith("_") or part.endswith("_work") for part in Path(rel).parts[:-1]):
            continue
        if file.suffix.lower() == ".parquet":
            schema = pq.read_schema(file)
            geometry_columns = {n for n in schema.names if n.lower() in {"geometry", "geometry_wkb"}} | geometries.get(rel, set())
            if geometry_columns or b"geo" in (schema.metadata or {}):
                error = _geo_error(schema, geometry_columns)
                checks.append({"name": f"geoparquet:{rel}", "status": "fail" if error else "pass", "violations": int(bool(error)), **({"reason": error} if error else {})})
            text_columns = [field.name for field in schema if str(field.type) in {"string", "large_string"} or str(field.type).startswith(("list<", "large_list<", "struct<", "map<"))]
            if text_columns:
                confirmed, candidates = _path_counts(con, "read_parquet(?)", text_columns, [str(file)], file_name=file.name)
                _record_path_counts(checks, rel, confirmed, candidates)
        elif file.suffix.lower() == ".duckdb":
            db = duckdb.connect(str(file), read_only=True)
            try:
                views = db.execute("SELECT view_name, sql FROM duckdb_views() WHERE NOT internal").fetchall()
                tables = db.execute("SELECT database_name, schema_name, table_name FROM duckdb_tables() WHERE NOT internal").fetchall()
                for database, namespace, table in tables:
                    columns = db.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_catalog = ? AND table_schema = ? AND table_name = ?", [database, namespace, table]).fetchall()
                    text_columns = [name for name, kind in columns if kind in {"VARCHAR", "JSON"} or kind.startswith(("STRUCT", "MAP", "UNION")) or kind.endswith("[]")]
                    if text_columns:
                        confirmed, candidates = _path_counts(db, f"{ident(database)}.{ident(namespace)}.{ident(table)}", text_columns)
                        _record_path_counts(checks, f"{rel}:table:{namespace}.{table}", confirmed, candidates)
            finally:
                db.close()
            bad = [name for name, sql in views if re.search(ABSOLUTE_PATH, sql or "")]
            checks.append({"name": f"absolute_paths:{rel}:views", "status": "fail" if bad else "pass", "violations": len(bad), "views": bad})
            candidates = [name for name, sql in views if any(not re.search(ABSOLUTE_PATH, match.group()) for match in re.finditer(POSSIBLE_POSIX_PATH, sql or ""))]
            if candidates:
                checks.append({"name": f"possible_absolute_paths:{rel}:views", "status": "fail", "violations": len(candidates), "views": candidates, "reason": "ambiguous slash-containing values require review"})
        elif file.suffix.lower() in text_suffixes:
            content = file.read_text(encoding="utf-8")
            count = len(re.findall(ABSOLUTE_PATH, content))
            candidates = sum(not re.search(ABSOLUTE_PATH, match.group()) for match in re.finditer(POSSIBLE_POSIX_PATH, content))
            _record_path_counts(checks, rel, count, candidates)
        else:
            checks.append({"name": f"absolute_paths:{rel}", "status": "fail", "violations": 1, "reason": "unsupported format; cannot verify embedded paths"})


def run_checks(contract_dir: Path, data_dir: Path, vocab_dir: Path = Path("registry/vocab")) -> dict:
    contracts = _load_contracts(contract_dir)
    if not data_dir.is_dir():
        raise ValueError(f"Data directory does not exist: {data_dir}")
    checks = []
    geometries = {}
    con = duckdb.connect()
    try:
        for name, contract in contracts.items():
            path = _inside(data_dir, contract["path"])
            if not path.is_file():
                raise ValueError(f"Missing table file: {contract['path']}")
            rel = path.relative_to(data_dir.resolve()).as_posix()
            geometries.setdefault(rel, set()).update(c["name"] for c in contract["columns"] if c.get("type") == "geometry")
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
                    expected = "BLOB" if spec["type"] == "geometry" else TYPE_NAMES[spec["type"]]
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
                    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values):
                        raise ValueError(f"Vocabulary must be a nonempty list of unique strings: {vocab_path.name}")
                    placeholders = ",".join("?" for _ in values)
                    _query_check(con, checks, f"vocab:{name}.{col}", f"SELECT * FROM {table} WHERE {column} IS NOT NULL AND {column} NOT IN ({placeholders})", values)
            key = contract.get("primary_key", [])
            if key:
                keys = ", ".join(ident(x) for x in key)
                nulls = " OR ".join(f"{ident(x)} IS NULL" for x in key)
                query = f"SELECT * EXCLUDE (__utilitydata_key_count) FROM (SELECT *, count(*) OVER (PARTITION BY {keys}) AS __utilitydata_key_count FROM {table}) WHERE __utilitydata_key_count > 1 OR {nulls}"
                _query_check(con, checks, f"primary_key:{name}", query)
            for col, minimum in contract.get("min_fill", {}).items():
                if col not in actual or not 0 <= minimum <= 1:
                    raise ValueError(f"Invalid fill constraint: {name}.{col}")
                total, filled = con.execute(f"SELECT count(*), count({ident(col)}) FROM {table}").fetchone()
                rate = filled / total if total else 0.0
                checks.append({"name": f"min_fill:{name}.{col}", "status": "pass" if rate >= minimum else "fail", "violations": total - filled, "rows": total, "filled": filled, "fill_rate": rate, "minimum": minimum, "query": f"SELECT * FROM {table} WHERE {ident(col)} IS NULL"})
        _check_files(con, data_dir, checks, geometries)
    finally:
        con.close()
    return {"status": "fail" if any(x["status"] == "fail" for x in checks) else "pass", "checks": checks}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
