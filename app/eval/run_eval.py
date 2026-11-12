"""Run the question bank against the local API and release tables.

Questions that need the Azure model are reported as blocked. This module does
not call a model. Aggregate latency is measured from the queries that finish.
QLever is not installed when that p95 does not exceed 5 seconds.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Never, Protocol
from urllib.parse import urlsplit

import duckdb

_ORIGINS = frozenset({"plan", "agent_example", "release"})
_LOOPBACK = frozenset({"127.0.0.1", "localhost"})
_DEFAULT_API = "http://127.0.0.1:8000"
_AGGREGATE_GATE_MS = 5000.0


@dataclass(frozen=True)
class Question:
    """One bank entry. Model questions have no check and are not executed."""

    id: str
    category: str
    origin: str
    question: str
    expect_iri_fragments: tuple[str, ...]
    reference_sparql: str | None
    reference_value_column: str | None
    requires_model: bool
    blocked_reason: str | None
    expect_values: tuple[str, ...]
    expect_row: dict[str, tuple[str, ...]]
    exact: bool
    compare: str
    min_rows: int | None
    check: dict[str, object] | None


@dataclass(frozen=True)
class Outcome:
    """The result of one question. Blocked questions have no latency."""

    id: str
    origin: str
    category: str
    status: str
    blocked_on: str | None
    latency_ms: float | None
    detail: str


@dataclass(frozen=True)
class Report:
    """Pass rate and latency for one run. Blocked questions are separate."""

    outcomes: tuple[Outcome, ...]
    p50_ms: float | None
    p95_ms: float | None
    aggregate_p50_ms: float | None
    aggregate_p95_ms: float | None
    qlever: str
    qlever_reason: str

    @property
    def passed(self) -> int:
        return sum(item.status == "pass" for item in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(item.status == "fail" for item in self.outcomes)

    @property
    def blocked_model(self) -> int:
        return sum(item.blocked_on == "model" for item in self.outcomes)

    @property
    def blocked_unproven(self) -> int:
        return sum(item.blocked_on == "unproven" for item in self.outcomes)


class Transport(Protocol):
    """JSON calls to the local API. Implementations must not call a model."""

    def get_json(self, path: str) -> tuple[dict[str, object], float]:
        """Return a JSON object and the elapsed milliseconds."""

    def post_json(self, path: str, payload: dict[str, object]) -> tuple[dict[str, object], float]:
        """Return a JSON object and the elapsed milliseconds."""


class ApiFailure(ValueError):
    """An HTTP response that is not success. The elapsed time is kept."""

    def __init__(self, detail: str, latency_ms: float) -> None:
        super().__init__(detail)
        self.latency_ms = latency_ms


class ApiTransport:
    """Loopback HTTP client for the local API."""

    def __init__(self, base: str, timeout_s: float = 120.0) -> None:
        self.base = _require_loopback(base)
        self.timeout_s = timeout_s

    def get_json(self, path: str) -> tuple[dict[str, object], float]:
        return self._read(path, None)

    def post_json(self, path: str, payload: dict[str, object]) -> tuple[dict[str, object], float]:
        return self._read(path, payload)

    def _read(self, path: str, payload: dict[str, object] | None) -> tuple[dict[str, object], float]:
        if not path.startswith("/api/") or path.startswith("/api/ask"):
            raise ValueError("This runner only calls read endpoints on the local API")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.load(response)
                elapsed = (time.perf_counter() - started) * 1000
        except urllib.error.HTTPError as exc:
            elapsed = (time.perf_counter() - started) * 1000
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise ApiFailure(f"HTTP {exc.code}: {detail}", elapsed) from exc
        if not isinstance(body, dict):
            raise ValueError("The API response was not an object")
        return body, elapsed


def load_questions(path: Path) -> list[Question]:
    """Read the bank and reject a question the runner cannot classify."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("questions.json must be a list")
    questions = [_question(item, index) for index, item in enumerate(payload, start=1)]
    identifiers = [item.id for item in questions]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Question ids are not unique")
    return questions


def evaluate(questions: list[Question], transport: Transport, home: Path | None) -> Report:
    """Run every question. None are dropped. Model questions are not sent anywhere."""
    outcomes = tuple(_one(item, transport, home) for item in questions)
    if len(outcomes) != len(questions):
        raise ValueError("The report dropped a question")
    timed = [item.latency_ms for item in outcomes if item.latency_ms is not None]
    aggregate = [
        item.latency_ms
        for item in outcomes
        if item.category == "aggregate" and item.latency_ms is not None
    ]
    aggregate_p95 = percentile(aggregate, 0.95)
    decision, reason = qlever_decision(aggregate_p95)
    return Report(
        outcomes,
        percentile(timed, 0.50),
        percentile(timed, 0.95),
        percentile(aggregate, 0.50),
        aggregate_p95,
        decision,
        reason,
    )


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear percentile. An empty sample has no percentile."""
    if not values:
        return None
    if fraction < 0 or fraction > 1:
        raise ValueError("Percentile is outside 0 to 1")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def qlever_decision(aggregate_p95_ms: float | None) -> tuple[str, str]:
    """Decide the optional store comparison from measured aggregate latency."""
    if aggregate_p95_ms is None:
        return "not_measured", "No aggregate query completed, so QLever was not compared."
    if aggregate_p95_ms > _AGGREGATE_GATE_MS:
        return "gate_open", "Aggregate p95 exceeded 5 seconds."
    return "skipped", "Aggregate p95 did not exceed 5 seconds, so QLever was not installed or compared."


def data_home() -> Path:
    """Return the data root. A relative or missing setting is an error."""
    configured = os.environ.get("UTILITYDATA_HOME")
    if not configured:
        raise ValueError("Set UTILITYDATA_HOME to the platform data directory")
    home = Path(configured).expanduser()
    if not home.is_absolute():
        raise ValueError("UTILITYDATA_HOME must be an absolute path")
    return home.resolve()


def write_report(report: Report, home: Path) -> None:
    """Write the run under the data root. The file contains no machine path."""
    destination = home / "eval"
    destination.mkdir(parents=True, exist_ok=True)
    payload = _payload(report)
    (destination / "wp14_report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    """Evaluate the bank beside this file and print the summary."""
    questions = load_questions(Path(__file__).resolve().parent / "questions.json")
    home = data_home()
    base = os.environ.get("UTILITYDATA_API_BASE", _DEFAULT_API)
    report = evaluate(questions, ApiTransport(base), home)
    write_report(report, home)
    _print_summary(report)
    return 1 if report.failed else 0


def _question(item: object, index: int) -> Question:
    if not isinstance(item, dict):
        raise ValueError(f"Question {index} is not an object")
    identifier = _text(item, "id")
    origin = _text(item, "origin")
    if origin not in _ORIGINS:
        raise ValueError(f"{identifier} has origin {origin}")
    requires_model = item.get("requires_model")
    if not isinstance(requires_model, bool):
        raise ValueError(f"{identifier} requires_model must be a boolean")
    blocked = item.get("blocked_reason")
    if blocked is not None and not isinstance(blocked, str):
        raise ValueError(f"{identifier} blocked_reason must be a string")
    check = item.get("check")
    if check is not None and not isinstance(check, dict):
        raise ValueError(f"{identifier} check must be an object")
    if requires_model and (blocked or check is not None):
        raise ValueError(f"{identifier} is a model question and cannot also be checked")
    if blocked and check is not None:
        raise ValueError(f"{identifier} is unproven and cannot also be checked")
    if not requires_model and not blocked and check is None:
        raise ValueError(f"{identifier} needs a check")
    reference = item.get("reference_sparql")
    if reference is not None and not isinstance(reference, str):
        raise ValueError(f"{identifier} reference_sparql must be a string")
    column = item.get("reference_value_column")
    if column is not None and not isinstance(column, str):
        raise ValueError(f"{identifier} reference_value_column must be a string")
    fragments = _strings(item.get("expect_iri_fragments"), f"{identifier} expect_iri_fragments")
    expected = _strings(item.get("expect_values", []), f"{identifier} expect_values")
    row = _expect_row(item.get("expect_row"), identifier)
    exact = item.get("exact", False)
    if not isinstance(exact, bool):
        raise ValueError(f"{identifier} exact must be a boolean")
    compare = item.get("compare", "equal")
    if compare not in {"equal", "substring"}:
        raise ValueError(f"{identifier} compare must be equal or substring")
    minimum = item.get("min_rows")
    if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0):
        raise ValueError(f"{identifier} min_rows must be a non-negative integer")
    if expected and column is None and not row:
        raise ValueError(f"{identifier} names values without a column")
    if row and column is not None and column not in row:
        raise ValueError(f"{identifier} reference column is absent from expect_row")
    if isinstance(check, dict):
        _validate_check(identifier, check, reference)
    return Question(
        identifier,
        _text(item, "category"),
        origin,
        _text(item, "question"),
        tuple(fragments),
        reference,
        column,
        requires_model,
        blocked,
        tuple(expected),
        row,
        exact,
        str(compare),
        minimum,
        dict(check) if isinstance(check, dict) else None,
    )


def _validate_check(identifier: str, check: dict[str, object], reference: str | None) -> None:
    kind = check.get("kind")
    if not isinstance(kind, str):
        raise ValueError(f"{identifier} check has no kind")
    if kind == "sparql" and not (reference and reference.strip()):
        raise ValueError(f"{identifier} sparql check needs reference_sparql")
    if kind == "duckdb":
        files = check.get("files")
        sql = check.get("sql")
        if not isinstance(files, list) or not files or not all(isinstance(item, str) for item in files):
            raise ValueError(f"{identifier} duckdb check needs relative files")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError(f"{identifier} duckdb check needs sql")
        _reject_absolute_sql(identifier, sql)
        for relative in files:
            _relative_file(identifier, relative)
    if kind == "who_serves":
        for name in ("lat", "lon", "sector"):
            if name not in check:
                raise ValueError(f"{identifier} who_serves check needs {name}")
    if kind == "stats" and (not isinstance(check.get("group"), str) or not isinstance(check.get("name"), str)):
        raise ValueError(f"{identifier} stats check needs a group and a name")
    if kind == "search" and not isinstance(check.get("q"), str):
        raise ValueError(f"{identifier} search check needs q")
    if kind == "scorecard" and (not isinstance(check.get("state"), str) or not isinstance(check.get("sector"), str)):
        raise ValueError(f"{identifier} scorecard check needs state and sector")
    if kind == "entity" and not isinstance(check.get("iri"), str):
        raise ValueError(f"{identifier} entity check needs an iri")
    if kind not in {"sparql", "duckdb", "who_serves", "stats", "search", "scorecard", "entity"}:
        raise ValueError(f"{identifier} has an unknown check")


def _one(question: Question, transport: Transport, home: Path | None) -> Outcome:
    if question.requires_model:
        return _blocked(question, "model", "The question needs the Azure model, which this run does not call.")
    if question.blocked_reason:
        return _blocked(question, "unproven", question.blocked_reason)
    try:
        return _execute(question, transport, home)
    except ApiFailure as exc:
        return _finish(question, "fail", exc.latency_ms, _public(exc, home))
    except urllib.error.URLError:
        return _finish(question, "fail", None, "The local API is not accepting connections.")
    except (OSError, ValueError, json.JSONDecodeError, duckdb.Error) as exc:
        return _finish(question, "fail", None, _public(exc, home))


def _execute(question: Question, transport: Transport, home: Path | None) -> Outcome:
    check = question.check
    if check is None:
        raise ValueError(f"{question.id} has no check")
    kind = check["kind"]
    match kind:
        case "sparql":
            observed, latency = _sparql(question, transport)
        case "duckdb":
            observed, latency = _duckdb(question, home)
        case "who_serves":
            observed, latency = _who_serves(check, transport)
        case "stats":
            observed, latency = _stats(check, transport)
        case "search":
            observed, latency = _search(check, transport)
        case "scorecard":
            observed, latency = _scorecard(check, transport)
        case "entity":
            observed, latency = _entity(check, transport)
        case _ as other:
            _unknown_kind(str(other))
    detail = _judge(question, observed)
    return _finish(question, "pass" if detail is None else "fail", latency, detail or "matched")


def _unknown_kind(kind: str) -> Never:
    raise ValueError(f"Unknown check: {kind}")


def _sparql(question: Question, transport: Transport) -> tuple[_Observed, float]:
    if question.reference_sparql is None:
        raise ValueError(f"{question.id} is missing reference_sparql")
    body, latency = transport.post_json("/api/sparql/query", {"query": question.reference_sparql})
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("SPARQL response did not contain rows")
    return _from_cells(rows, _count(body, len(rows))), latency


def _duckdb(question: Question, home: Path | None) -> tuple[_Observed, float]:
    if home is None:
        raise ValueError("Set UTILITYDATA_HOME to the platform data directory")
    check = question.check or {}
    files = check.get("files")
    sql = check.get("sql")
    if not isinstance(files, list) or not isinstance(sql, str):
        raise ValueError(f"{question.id} duckdb check is incomplete")
    paths = [_resolve(home, relative) for relative in files if isinstance(relative, str)]
    connection = duckdb.connect()
    started = time.perf_counter()
    try:
        cursor = connection.execute(sql, paths)
        rows = cursor.fetchall()
        names = [item[0] for item in cursor.description] if cursor.description else []
    finally:
        connection.close()
    latency = (time.perf_counter() - started) * 1000
    columns: dict[str, list[object]] = {name: [] for name in names}
    for row in rows:
        for name, value in zip(names, row, strict=True):
            columns[name].append(value)
    return _Observed(columns, [], len(rows)), latency


def _who_serves(check: dict[str, object], transport: Transport) -> tuple[_Observed, float]:
    lat = _number(check.get("lat"), "lat")
    lon = _number(check.get("lon"), "lon")
    sector = check.get("sector")
    if not isinstance(sector, str) or not sector:
        raise ValueError("who_serves sector is missing")
    path = "/api/geo/who-serves?" + urllib.parse.urlencode({"lat": lat, "lon": lon, "sector": sector})
    body, latency = transport.get_json(path)
    systems = body.get("systems")
    if not isinstance(systems, list):
        raise ValueError("who-serves response did not contain systems")
    columns: dict[str, list[object]] = {"count": [body.get("count")]}
    iris: list[str] = []
    for system in systems:
        if not isinstance(system, dict):
            continue
        for key, value in system.items():
            columns.setdefault(str(key), []).append(value)
            if key == "iri" and isinstance(value, str):
                iris.append(value)
    return _Observed(columns, iris, len(systems)), latency


def _stats(check: dict[str, object], transport: Transport) -> tuple[_Observed, float]:
    body, latency = transport.get_json("/api/stats")
    group = str(check.get("group"))
    name = str(check.get("name"))
    rows = body.get(group)
    if not isinstance(rows, list):
        raise ValueError("Stats response did not contain the requested group")
    found = [row.get("count") for row in rows if isinstance(row, dict) and row.get("name") == name]
    return _Observed({"count": found}, [], len(found)), latency


def _search(check: dict[str, object], transport: Transport) -> tuple[_Observed, float]:
    params: dict[str, str] = {"q": str(check.get("q"))}
    limit = check.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool):
        params["limit"] = str(limit)
    state = check.get("state")
    if isinstance(state, str) and state:
        params["state"] = state
    body, latency = transport.get_json("/api/search?" + urllib.parse.urlencode(params))
    return _plain_rows(body, latency)


def _scorecard(check: dict[str, object], transport: Transport) -> tuple[_Observed, float]:
    params = {"state": str(check.get("state")), "sector": str(check.get("sector"))}
    body, latency = transport.get_json("/api/coverage/scorecard?" + urllib.parse.urlencode(params))
    return _plain_rows(body, latency)


def _entity(check: dict[str, object], transport: Transport) -> tuple[_Observed, float]:
    path = "/api/entity?" + urllib.parse.urlencode({"iri": str(check.get("iri"))})
    body, latency = transport.get_json(path)
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Entity response did not contain rows")
    return _from_cells(rows, _count(body, len(rows))), latency


def _plain_rows(body: dict[str, object], latency: float) -> tuple[_Observed, float]:
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("The API response did not contain rows")
    columns: dict[str, list[object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            columns.setdefault(str(key), []).append(value)
    return _Observed(columns, [], len(rows)), latency


def _from_cells(rows: list[object], row_count: int) -> _Observed:
    columns: dict[str, list[object]] = {}
    iris: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, cell in row.items():
            if isinstance(cell, dict):
                columns.setdefault(str(key), []).append(cell.get("value"))
                if cell.get("kind") == "iri" and isinstance(cell.get("value"), str):
                    iris.append(str(cell["value"]))
            else:
                columns.setdefault(str(key), []).append(cell)
    return _Observed(columns, iris, row_count)


def _judge(question: Question, observed: _Observed) -> str | None:
    if question.min_rows is not None and observed.rows < question.min_rows:
        return f"row count {observed.rows} is below {question.min_rows}"
    for fragment in question.expect_iri_fragments:
        if not any(fragment in iri for iri in observed.iris):
            return f"IRI fragment {fragment} was absent"
    expected = dict(question.expect_row)
    if question.expect_values:
        if question.reference_value_column is None:
            return "values were named without a column"
        expected[question.reference_value_column] = question.expect_values
    for column, wanted in expected.items():
        actual = observed.columns.get(column, [])
        if not _values_match(actual, wanted, exact=question.exact, compare=question.compare):
            return f"column {column} did not match"
    if question.reference_value_column and question.reference_value_column not in observed.columns and not expected:
        return f"column {question.reference_value_column} was absent"
    return None


def _values_match(actual: list[object], wanted: tuple[str, ...], *, exact: bool, compare: str) -> bool:
    found = [_normalize(value) for value in actual]
    needed = [_normalize(value) for value in wanted]
    if compare == "substring":
        folded = [item.casefold() for item in found]
        return all(any(item.casefold() in candidate for candidate in folded) for item in needed)
    if compare != "equal":
        raise ValueError(f"Unknown compare: {compare}")
    if exact:
        return sorted(found) == sorted(needed)
    return all(item in found for item in needed)


def _normalize(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    text = str(value).strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if number == number.to_integral_value():
        return str(number.to_integral_value())
    return format(number.normalize(), "f")


def _blocked(question: Question, kind: str, detail: str) -> Outcome:
    return Outcome(question.id, question.origin, question.category, "blocked", kind, None, detail)


def _finish(question: Question, status: str, latency: float | None, detail: str) -> Outcome:
    return Outcome(question.id, question.origin, question.category, status, None, latency, detail)


def _payload(report: Report) -> dict[str, object]:
    executed = report.passed + report.failed
    return {
        "questions": len(report.outcomes),
        "ran": executed,
        "passed": report.passed,
        "failed": report.failed,
        "blocked_model": report.blocked_model,
        "blocked_unproven": report.blocked_unproven,
        "pass_rate_by_category": _rates(report),
        "p50_ms": report.p50_ms,
        "p95_ms": report.p95_ms,
        "aggregate_p50_ms": report.aggregate_p50_ms,
        "aggregate_p95_ms": report.aggregate_p95_ms,
        "qlever": report.qlever,
        "qlever_reason": report.qlever_reason,
        "ask_called": False,
        "by_origin": _origin_counts(report),
        "outcomes": [
            {
                "id": item.id,
                "origin": item.origin,
                "category": item.category,
                "status": item.status,
                "blocked_on": item.blocked_on,
                "latency_ms": item.latency_ms,
                "detail": item.detail,
            }
            for item in report.outcomes
        ],
    }


def _rates(report: Report) -> dict[str, dict[str, object]]:
    categories = sorted({item.category for item in report.outcomes})
    rates: dict[str, dict[str, object]] = {}
    for category in categories:
        rows = [item for item in report.outcomes if item.category == category]
        passed = sum(item.status == "pass" for item in rows)
        failed = sum(item.status == "fail" for item in rows)
        executed = passed + failed
        rates[category] = {
            "passed": passed,
            "failed": failed,
            "blocked": sum(item.status == "blocked" for item in rows),
            "pass_rate": None if executed == 0 else passed / executed,
        }
    return rates


def _origin_counts(report: Report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in report.outcomes:
        counts[item.origin] = counts.get(item.origin, 0) + 1
    return counts


def _print_summary(report: Report) -> None:
    print(
        f"questions {len(report.outcomes)}; ran {report.passed + report.failed}; "
        f"passed {report.passed}; failed {report.failed}; "
        f"blocked model {report.blocked_model}; blocked unproven {report.blocked_unproven}"
    )
    print(
        f"p50_ms {report.p50_ms}; p95_ms {report.p95_ms}; "
        f"aggregate_p50_ms {report.aggregate_p50_ms}; aggregate_p95_ms {report.aggregate_p95_ms}"
    )
    print(f"qlever {report.qlever}: {report.qlever_reason}")
    print("report: UTILITYDATA_HOME/eval/wp14_report.json")
    for item in report.outcomes:
        if item.status == "fail":
            print(f"fail {item.id}: {item.detail}")


def _require_loopback(base: str) -> str:
    parsed = urlsplit(base.strip())
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK:
        raise ValueError("The API must use the loopback interface")
    return base.strip().rstrip("/")


def _resolve(home: Path, relative: str) -> str:
    _relative_file("duckdb", relative)
    path = (home / relative).resolve()
    if not path.is_relative_to(home.resolve()) or not path.is_file():
        raise ValueError(f"Release file is missing: {relative}")
    return str(path)


def _relative_file(identifier: str, relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative:
        raise ValueError(f"{identifier} file path must stay under UTILITYDATA_HOME")


def _reject_absolute_sql(identifier: str, sql: str) -> None:
    if ":\\" in sql or "/Users/" in sql or "/home/" in sql:
        raise ValueError(f"{identifier} sql contains a machine path")


def _public(exc: Exception, home: Path | None) -> str:
    text = " ".join(str(exc).split())
    if home is not None:
        text = text.replace(str(home.resolve()), "UTILITYDATA_HOME")
        text = text.replace(str(home), "UTILITYDATA_HOME")
    return text[:500] or exc.__class__.__name__


def _text(item: dict[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Question is missing {key}")
    return value


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return list(value)


def _expect_row(value: object, identifier: str) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{identifier} expect_row must be an object")
    row: dict[str, tuple[str, ...]] = {}
    for key, expected in value.items():
        row[str(key)] = tuple(_strings(expected, f"{identifier} expect_row {key}"))
    return row


def _count(body: dict[str, object], fallback: int) -> int:
    value = body.get("row_count", fallback)
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _number(value: object, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is not a number")
    return str(value)


@dataclass(frozen=True)
class _Observed:
    columns: dict[str, list[object]]
    iris: list[str]
    rows: int


if __name__ == "__main__":
    raise SystemExit(main())
