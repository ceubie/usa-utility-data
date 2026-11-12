"""Shared request and result types for one refresh fetch."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from shapely.geometry.base import BaseGeometry

from utilitydata.registry import Source


@dataclass(frozen=True)
class HttpResponse:
    """Status, headers, and body from one driver request."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes


class Transport(Protocol):
    """HTTP caller used by the drivers. Tests supply a fake."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None,
        headers: Mapping[str, str] | None,
        data: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Perform one request or raise TimeoutError when the server does not answer."""


@dataclass(frozen=True)
class PreviousFile:
    """One file recorded in the last good snapshot."""

    relative_path: str
    sha256: str
    byte_count: int
    retrieved_utc: str | None


@dataclass(frozen=True)
class CandidateFile:
    """Bytes a driver is willing to commit for one relative path."""

    relative_path: str
    content: bytes


@dataclass(frozen=True)
class FetchRequest:
    """Everything a driver may use without choosing a source by name."""

    source: Source
    dry_run: bool
    staging: Path
    previous: tuple[PreviousFile, ...]
    read_previous: Callable[[str], bytes]
    read_current: Callable[[str], bytes]
    transport: Transport | None
    page_size: int
    timeout_seconds: float
    expected_state: BaseGeometry | None = None


@dataclass(frozen=True)
class FetchResult:
    """Files read or downloaded for one source, plus hash differences."""

    unchanged: bool
    files: tuple[CandidateFile, ...]
    differences: tuple[str, ...]
