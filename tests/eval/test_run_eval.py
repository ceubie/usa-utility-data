"""The question runner skips the model and checks the bank shape."""

import json
from pathlib import Path

import duckdb
import pytest

from app.eval.run_eval import (
    ApiFailure,
    evaluate,
    load_questions,
    percentile,
    qlever_decision,
)

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "app" / "eval" / "questions.json"
RUNNER = ROOT / "app" / "eval" / "run_eval.py"


class BoomTransport:
    """A transport that fails if a blocked question is executed."""

    def get_json(self, path: str) -> tuple[dict[str, object], float]:
        raise AssertionError(path)

    def post_json(self, path: str, payload: dict[str, object]) -> tuple[dict[str, object], float]:
        raise AssertionError(path)


class FakeTransport:
    """Canned JSON for one local endpoint."""

    def __init__(self, body: dict[str, object]) -> None:
        self.body = body
        self.calls: list[str] = []

    def get_json(self, path: str) -> tuple[dict[str, object], float]:
        self.calls.append(path)
        if path.startswith("/api/ask"):
            raise AssertionError(path)
        return self.body, 12.5

    def post_json(self, path: str, payload: dict[str, object]) -> tuple[dict[str, object], float]:
        self.calls.append(path)
        if path.startswith("/api/ask"):
            raise AssertionError(path)
        return self.body, 20.0


def test_bank_has_sixty_questions_and_named_origins():
    questions = load_questions(BANK)
    assert len(questions) >= 60
    origins = {item.origin for item in questions}
    assert origins <= {"plan", "agent_example", "release"}
    assert any(item.requires_model for item in questions)
    assert any(item.blocked_reason for item in questions)
    text = BANK.read_text(encoding="utf-8").casefold()
    assert "colleague" not in text
    assert "verified_by" not in text
    runner = RUNNER.read_text(encoding="utf-8")
    assert "llm_client" not in runner
    assert "AZURE_OPENAI" not in runner
    assert "import qlever" not in runner.casefold()


def test_model_questions_are_blocked_without_a_call():
    questions = [item for item in load_questions(BANK) if item.requires_model or item.blocked_reason]
    report = evaluate(questions, BoomTransport(), home=None)
    assert len(report.outcomes) == len(questions)
    assert report.blocked_model == sum(item.requires_model for item in questions)
    assert report.blocked_unproven == sum(bool(item.blocked_reason) for item in questions)
    assert report.passed == 0
    assert report.failed == 0
    assert all(item.latency_ms is None for item in report.outcomes)


def test_sparql_check_matches_a_literal_and_an_iri():
    question = next(item for item in load_questions(BANK) if item.id == "plan-travis-served-count")
    body = {
        "kind": "select",
        "row_count": 1,
        "rows": [{"value": {"kind": "literal", "value": "84"}}],
    }
    report = evaluate([question], FakeTransport(body), home=None)
    assert report.outcomes[0].status == "pass"
    assert report.outcomes[0].latency_ms == 20.0


def test_who_serves_requires_the_pepco_id():
    question = next(item for item in load_questions(BANK) if item.id == "plan-pepco-point")
    body = {
        "count": 1,
        "systems": [{
            "system_id": "SYS_EIA_15270",
            "name": "Potomac Electric Power Co",
            "iri": "http://utilities.local/system/SYS_EIA_15270",
        }],
    }
    transport = FakeTransport(body)
    report = evaluate([question], transport, home=None)
    assert report.outcomes[0].status == "pass"
    assert transport.calls[0].startswith("/api/geo/who-serves?lat=38.9072&lon=-77.0369&sector=electric")


def test_duckdb_reads_a_relative_file_under_the_data_root(tmp_path: Path):
    destination = tmp_path / "core" / "2026-Q4"
    destination.mkdir(parents=True)
    connection = duckdb.connect()
    try:
        connection.execute(
            "COPY (SELECT 'SYS_EIA_19876' AS system_id, 'Virginia Electric & Power Co' AS name) "
            "TO ? (FORMAT parquet)",
            [str(destination / "electric_system.parquet")],
        )
    finally:
        connection.close()
    question = next(item for item in load_questions(BANK) if item.id == "plan-dominion-name")
    report = evaluate([question], BoomTransport(), tmp_path)
    assert report.outcomes[0].status == "pass"
    assert report.outcomes[0].latency_ms is not None


def test_absolute_sql_is_rejected(tmp_path: Path):
    payload = [{
        "id": "bad-path",
        "category": "release_table",
        "origin": "release",
        "question": "Bad",
        "expect_iri_fragments": [],
        "reference_sparql": None,
        "reference_value_column": "value",
        "requires_model": False,
        "expect_values": ["1"],
        "exact": True,
        "check": {"kind": "duckdb", "files": ["core/system.parquet"], "sql": "SELECT 1 AS value FROM read_parquet('C:\\\\secret.parquet')"},
    }]
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="machine path"):
        load_questions(path)


def test_percentiles_and_qlever_gate():
    assert percentile([], 0.95) is None
    assert percentile([10, 20, 30, 40, 50], 0.50) == 30
    assert percentile([10, 20, 30, 40, 50], 0.95) == pytest.approx(48)
    assert qlever_decision(5000)[0] == "skipped"
    assert qlever_decision(5000.1)[0] == "gate_open"
    assert qlever_decision(None)[0] == "not_measured"


def test_http_failure_keeps_latency(tmp_path: Path):
    class Failing:
        def get_json(self, path: str) -> tuple[dict[str, object], float]:
            raise ApiFailure("HTTP 503: timeout", 21000)

        def post_json(self, path: str, payload: dict[str, object]) -> tuple[dict[str, object], float]:
            raise AssertionError(path)

    question = next(item for item in load_questions(BANK) if item.id == "release-stats-state")
    report = evaluate([question], Failing(), tmp_path)
    assert report.outcomes[0].status == "fail"
    assert report.outcomes[0].latency_ms == 21000
