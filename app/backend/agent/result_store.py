"""Per-request map from a result id to the full columns and rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class StoredResult:
    """One tool result kept until the request ends."""

    columns: list[str]
    rows: list[dict]


@dataclass
class ResultStore:
    """Rows for the current request. Drop the object when the request ends."""

    _results: dict[str, StoredResult] = field(default_factory=dict)

    def put(self, columns: list[str], rows: list[dict]) -> str:
        """Store a full result and return its id."""
        result_id = uuid4().hex
        self._results[result_id] = StoredResult(list(columns), list(rows))
        return result_id

    def get(self, result_id: str) -> StoredResult | None:
        """Return a stored result, or None when the id is unknown."""
        return self._results.get(result_id)
