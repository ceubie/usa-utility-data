"""Fetch one HTTP file with a conditional request and compare its SHA-256."""

from datetime import datetime
from email.utils import format_datetime

from utilitydata.bronze.blobs import sha256_bytes
from utilitydata.bronze.drivers.local import fetch_local
from utilitydata.bronze.drivers.protocol import CandidateFile, FetchRequest, FetchResult


def fetch_http(request: FetchRequest) -> FetchResult:
    """Read the local file, or request it when this is not a dry run."""
    if request.dry_run or request.transport is None:
        return fetch_local(request)
    if len(request.source.paths) != 1:
        raise ValueError(f"HTTP source needs exactly one path: {request.source.source_id}")
    if not request.source.url:
        raise ValueError(f"HTTP source needs a URL: {request.source.source_id}")
    if len(request.previous) > 1:
        raise ValueError(f"HTTP source has more than one previous file: {request.source.source_id}")
    headers: dict[str, str] = {}
    previous = request.previous[0] if request.previous else None
    if previous is not None:
        headers["If-None-Match"] = f'"{previous.sha256}"'
        modified = _http_date(previous.retrieved_utc)
        if modified is not None:
            headers["If-Modified-Since"] = modified
    response = request.transport.request(
        "GET",
        request.source.url,
        params=None,
        headers=headers,
        data=None,
        timeout=request.timeout_seconds,
    )
    relative = request.source.paths[0]
    if response.status_code == 304:
        if previous is None:
            raise ValueError(f"HTTP 304 without a previous file for {request.source.source_id}")
        content = request.read_previous(relative)
        if sha256_bytes(content) != previous.sha256:
            raise ValueError(f"Previous file hash does not match the manifest for {relative}")
        return FetchResult(True, (CandidateFile(relative, content),), ())
    if response.status_code != 200:
        raise ValueError(f"HTTP status {response.status_code} for {request.source.source_id}")
    digest = sha256_bytes(response.content)
    differences: tuple[str, ...] = ()
    unchanged = previous is not None and digest == previous.sha256
    if previous is not None and not unchanged:
        differences = (f"{relative} snapshot {previous.sha256} current {digest}",)
    return FetchResult(unchanged, (CandidateFile(relative, response.content),), differences)


def _http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return format_datetime(parsed, usegmt=True)
