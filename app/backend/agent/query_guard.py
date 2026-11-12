"""Accept a read-only SPARQL query, or return an error message."""

from __future__ import annotations

from dataclasses import dataclass

from rdflib.plugins.sparql import prepareQuery

from app.backend.agent.prefixes import standard_prefixes

_MAX_CHARS = 24_000
_DEFAULT_LIMIT = 1000
_DEFAULT_BASE = "http://utilities.local/"
_FORBIDDEN = frozenset({
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
})
_FORMS = frozenset({"SELECT", "ASK"})
_PROLOGUE = frozenset({"PREFIX", "BASE"})
_SPACE = frozenset(" \t\r\n")
_IRI_STOP = set('<>"{}|\\^`') | _SPACE | {chr(code) for code in range(32)}


@dataclass(frozen=True)
class GuardResult:
    """A query that may be executed, or a plain-text error."""

    query: str | None
    error: str | None
    kind: str | None = None


@dataclass
class _Scan:
    words: list[tuple[str, int]]
    prefixes: set[str]
    limits: list[tuple[int, int, int, int]]
    values_at: int | None


def check(
    query: str,
    *,
    row_limit: int = _DEFAULT_LIMIT,
    base_iri: str = _DEFAULT_BASE,
) -> GuardResult:
    """Return a guarded query, or an error message.

    String literals, comments, and IRIs are blanked before keywords are read.
    The outer limit is capped. A limit inside a subquery is left alone.
    """
    if query is None or not str(query).strip():
        return GuardResult(None, "Query is empty.")
    text = str(query)
    if len(text) > _MAX_CHARS:
        return GuardResult(None, "Query is longer than 24000 characters.")
    if row_limit < 1:
        return GuardResult(None, "Row limit must be at least 1.")
    scan = _scan(text)
    for word, _start in scan.words:
        if word in _FORBIDDEN:
            return GuardResult(None, f"{word} is not allowed.")
    index = 0
    while index < len(scan.words) and scan.words[index][0] in _PROLOGUE:
        index += 1
    if index >= len(scan.words) or scan.words[index][0] not in _FORMS:
        return GuardResult(None, "Only SELECT and ASK queries are allowed.")
    kind = scan.words[index][0].lower()
    rewritten = _cap_outer_limit(text, scan, row_limit)
    rewritten = _add_prefixes(rewritten, scan.prefixes, base_iri)
    try:
        prepareQuery(rewritten)
    except Exception as exc:  # noqa: BLE001 - rdflib raises bare Exception for an unknown prefix
        message = " ".join(str(exc).split()) or "SPARQL syntax error"
        return GuardResult(None, message)
    return GuardResult(rewritten, None, kind)


def _scan(text: str) -> _Scan:
    """Tokenize bare words after blanking literals, comments, and IRIs."""
    words: list[tuple[str, int]] = []
    prefixes: set[str] = set()
    limits: list[tuple[int, int, int, int]] = []
    values_at: int | None = None
    expect_prefix = False
    expect_limit = False
    limit_depth = 0
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in _SPACE:
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if text.startswith('"""', index) or text.startswith("'''", index):
            index = _skip_long_string(text, index)
            expect_prefix = False
            expect_limit = False
            continue
        if char in "'\"":
            index = _skip_short_string(text, index)
            expect_prefix = False
            expect_limit = False
            continue
        if char == "<":
            closing = _closing_iri(text, index)
            if closing is None:
                index += 1
            else:
                index = closing
            expect_prefix = False
            expect_limit = False
            continue
        if char == "{":
            depth += 1
            index += 1
            expect_prefix = False
            expect_limit = False
            continue
        if char == "}":
            depth = max(0, depth - 1)
            index += 1
            expect_prefix = False
            expect_limit = False
            continue
        if char in "?$":
            index = _skip_local(text, index + 1)
            expect_prefix = False
            expect_limit = False
            continue
        if char == "@" or text.startswith("_:", index):
            index = _skip_local(text, index + (2 if char == "_" else 1))
            expect_prefix = False
            expect_limit = False
            continue
        if char == ":":
            index = _skip_local(text, index + 1, colons=True)
            expect_prefix = False
            expect_limit = False
            continue
        if "0" <= char <= "9":
            start = index
            while index < length and "0" <= text[index] <= "9":
                index += 1
            if expect_limit:
                try:
                    number = int(text[start:index])
                except ValueError:
                    number = None
                if number is not None:
                    limits.append((limit_depth, start, index, number))
            expect_limit = False
            expect_prefix = False
            continue
        if char.isalpha() or char == "_":
            start = index
            while index < length and (text[index].isalnum() or text[index] == "_"):
                index += 1
            token = text[start:index]
            colon_at = index if index < length and text[index] == ":" else None
            if colon_at is None and expect_prefix:
                peeked = _peek(text, index)
                if peeked < length and text[peeked] == ":":
                    colon_at = peeked
            if colon_at is not None:
                if expect_prefix:
                    prefixes.add(token.casefold())
                index = _skip_local(text, colon_at + 1, colons=True)
                expect_prefix = False
                expect_limit = False
                continue
            word = token.upper()
            words.append((word, start))
            if word == "PREFIX":
                expect_prefix = True
                expect_limit = False
            elif word == "LIMIT":
                expect_limit = True
                limit_depth = depth
                expect_prefix = False
            elif word == "VALUES" and depth == 0 and values_at is None:
                values_at = start
                expect_prefix = False
                expect_limit = False
            else:
                expect_prefix = False
                expect_limit = False
            continue
        index += 1
        expect_prefix = False
        expect_limit = False
    return _Scan(words, prefixes, limits, values_at)


def _cap_outer_limit(text: str, scan: _Scan, row_limit: int) -> str:
    """Lower an outer limit above the cap, or add one. Subquery limits stay."""
    outer = [item for item in scan.limits if item[0] == 0]
    if outer:
        rewritten = text
        for _depth, start, end, value in reversed(outer):
            if value > row_limit:
                rewritten = rewritten[:start] + str(row_limit) + rewritten[end:]
        return rewritten
    clause = f"\nLIMIT {row_limit}\n"
    if scan.values_at is None:
        return text + clause
    return text[: scan.values_at] + clause + text[scan.values_at :]


def _add_prefixes(text: str, declared: set[str], base_iri: str) -> str:
    """Prepend standard prefixes that the query does not already declare."""
    missing = [
        f"PREFIX {name}: <{iri}>"
        for name, iri in standard_prefixes(base_iri)
        if name.casefold() not in declared
    ]
    if not missing:
        return text
    return "\n".join(missing) + "\n" + text


def _peek(text: str, index: int) -> int:
    while index < len(text) and text[index] in _SPACE:
        index += 1
    return index


def _skip_long_string(text: str, index: int) -> int:
    quote = text[index : index + 3]
    cursor = index + 3
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text.startswith(quote, cursor):
            return cursor + 3
        cursor += 1
    return len(text)


def _skip_short_string(text: str, index: int) -> int:
    quote = text[index]
    cursor = index + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == quote:
            return cursor + 1
        if text[cursor] == "\n":
            return cursor
        cursor += 1
    return len(text)


def _closing_iri(text: str, start: int) -> int | None:
    """Return the index after an IRI, or None when `<` is an operator."""
    cursor = start + 1
    while cursor < len(text):
        char = text[cursor]
        if char == ">":
            return cursor + 1
        if char in _IRI_STOP or ord(char) < 32:
            return None
        cursor += 1
    return None


def _skip_local(text: str, index: int, *, colons: bool = False) -> int:
    while index < len(text):
        char = text[index]
        if char.isalnum() or char in "_-." or (colons and char == ":"):
            index += 1
            continue
        if char == "%" and index + 2 < len(text) and text[index + 1 : index + 3].isalnum():
            index += 3
            continue
        if char == "\\":
            index += 2
            continue
        break
    return index
