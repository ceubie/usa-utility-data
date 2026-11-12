"""SPARQL query guard."""

import pytest

from app.backend.agent.query_guard import check

_FORBIDDEN = (
    "INSERT",
    "DELETE",
    "LOAD",
    "CLEAR",
    "DROP",
    "CREATE",
    "COPY",
    "MOVE",
    "ADD",
    "CONSTRUCT",
    "DESCRIBE",
    "SERVICE",
)


def test_select_and_ask_pass():
    selected = check("SELECT ?s WHERE { ?s ?p ?o }")
    assert selected.error is None
    assert selected.kind == "select"
    assert selected.query is not None
    assert "SELECT" in selected.query
    assert "LIMIT 1000" in selected.query
    assert "PREFIX ud:" in selected.query

    asked = check("ASK { ?s ?p ?o }")
    assert asked.error is None
    assert asked.kind == "ask"
    assert asked.query is not None
    assert "ASK" in asked.query


@pytest.mark.parametrize("keyword", _FORBIDDEN)
def test_update_construct_describe_and_service_are_rejected(keyword: str):
    result = check(f"{keyword} {{ ?s ?p ?o }}")
    assert result.query is None
    assert result.error is not None
    assert keyword in result.error


def test_keyword_inside_a_literal_or_comment_passes():
    words = " ".join(_FORBIDDEN)
    literal = check(f'SELECT ?s WHERE {{ ?s ?p "{words}" }}')
    assert literal.error is None
    assert literal.query is not None

    comment = check(f"SELECT ?s WHERE {{ ?s ?p ?o }} # {words}\n")
    assert comment.error is None
    assert comment.query is not None

    iri = check("SELECT ?s WHERE { ?s ?p <http://example.org/DELETE> }")
    assert iri.error is None
    assert iri.query is not None


def test_missing_limit_is_added_and_a_large_limit_is_lowered():
    missing = check("SELECT ?s WHERE { ?s ?p ?o }")
    assert missing.query is not None
    assert "LIMIT 1000" in missing.query

    lowered = check("SELECT ?s WHERE { ?s ?p ?o } LIMIT 50000")
    assert lowered.error is None
    assert lowered.query is not None
    assert "LIMIT 1000" in lowered.query
    assert "50000" not in lowered.query

    kept = check("SELECT ?s WHERE { ?s ?p ?o } LIMIT 10")
    assert kept.query is not None
    assert "LIMIT 10" in kept.query
    assert "LIMIT 1000" not in kept.query


def test_limit_inside_a_subquery_is_left_alone():
    result = check(
        """
        SELECT ?s WHERE {
          { SELECT ?s WHERE { ?s ?p ?o } LIMIT 5 }
        }
        """
    )
    assert result.error is None
    assert result.query is not None
    assert "LIMIT 5" in result.query
    assert "LIMIT 1000" in result.query


def test_syntax_error_comes_back_as_text():
    result = check("SELECT WHERE {")
    assert result.query is None
    assert isinstance(result.error, str)
    assert result.error


def test_empty_and_overlong_queries_are_rejected():
    assert check("  \n").error
    assert check("SELECT ?s WHERE { ?s ?p ?o }" + (" " * 24_000)).query is None


def test_prefixed_names_are_not_keywords_and_a_service_clause_is():
    service = check("PREFIX : <http://example.org/> SELECT ?s WHERE { SERVICE :sparql { ?s ?p ?o } }")
    assert service.query is None
    assert service.error is not None
    assert "SERVICE" in service.error

    spaced = check("SELECT ?s WHERE { SERVICE\t:sparql { ?s ?p ?o } }")
    assert spaced.query is None
    assert spaced.error is not None
    assert "SERVICE" in spaced.error

    empty_prefix = check("PREFIX : <http://example.org/> SELECT ?s WHERE { ?s :DELETE ?o }")
    assert empty_prefix.error is None

    local_colon = check("PREFIX ex: <http://example.org/> SELECT ?s WHERE { ?s ex:foo:DELETE ?o }")
    assert local_colon.error is None


def test_a_non_ascii_limit_digit_is_a_syntax_error():
    result = check("SELECT ?s WHERE { ?s ?p ?o } LIMIT ²")
    assert result.query is None
    assert isinstance(result.error, str)
    assert result.error


def test_triple_quoted_literal_and_an_existing_prefix_are_kept():
    literal = check('SELECT ?s WHERE { ?s ?p """DELETE INSERT SERVICE""" }')
    assert literal.error is None
    declared = check("PREFIX ud: <http://utilities.local/ontology/>\nSELECT ?s WHERE { ?s a ud:County }")
    assert declared.error is None
    assert declared.query is not None
    assert declared.query.lower().count("prefix ud:") == 1


def test_limit_is_inserted_before_a_values_clause():
    result = check("SELECT ?s WHERE { ?s ?p ?o } VALUES ?s { <http://example.org/a> }")
    assert result.error is None
    assert result.query is not None
    assert result.query.index("LIMIT 1000") < result.query.index("VALUES")
