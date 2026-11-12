"""Choose the newest file linked from a landing page and download that file."""

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from utilitydata.bronze.blobs import sha256_bytes
from utilitydata.bronze.drivers.local import fetch_local
from utilitydata.bronze.drivers.protocol import (
    CandidateFile,
    FetchRequest,
    FetchResult,
    Transport,
)

_DATA_SUFFIXES = (".zip", ".csv", ".gz", ".tgz", ".gpkg", ".geojson", ".json", ".xlsx", ".xls", ".parquet", ".txt")
_DATE = re.compile(r"(20\d{2})(?:[-_.]?(0[1-9]|1[0-2])(?:[-_.]?([0-2]\d|3[01]))?)?")


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def fetch_discover(request: FetchRequest) -> FetchResult:
    """Read the local file, or take the newest file linked from the landing page."""
    if request.dry_run or request.transport is None:
        return fetch_local(request)
    if len(request.source.paths) != 1:
        raise ValueError(f"Discover source needs exactly one path: {request.source.source_id}")
    if not request.source.url:
        raise ValueError(f"Discover source needs a landing page: {request.source.source_id}")
    transport = request.transport
    page = transport.request("GET", request.source.url, params=None, headers=None, data=None, timeout=request.timeout_seconds)
    if page.status_code != 200:
        raise ValueError(f"Landing page returned HTTP {page.status_code} for {request.source.source_id}")
    chosen = _newest(request.source.url, page.content.decode("utf-8", errors="replace"), transport, request.timeout_seconds)
    downloaded = transport.request("GET", chosen, params=None, headers=None, data=None, timeout=request.timeout_seconds)
    if downloaded.status_code != 200:
        raise ValueError(f"Discovered file returned HTTP {downloaded.status_code} for {request.source.source_id}")
    relative = request.source.paths[0]
    digest = sha256_bytes(downloaded.content)
    previous = request.previous[0] if len(request.previous) == 1 else None
    if len(request.previous) > 1:
        raise ValueError(f"Discover source has more than one previous file: {request.source.source_id}")
    differences: tuple[str, ...] = ()
    unchanged = previous is not None and digest == previous.sha256
    if previous is not None and not unchanged:
        differences = (f"{relative} snapshot {previous.sha256} current {digest}",)
    return FetchResult(unchanged, (CandidateFile(relative, downloaded.content),), differences)


def _newest(page_url: str, html: str, transport: Transport, timeout: float) -> str:
    parser = _Links()
    parser.feed(html)
    links = []
    for href in parser.hrefs:
        if href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        path = urlparse(absolute).path.casefold()
        if path.endswith(_DATA_SUFFIXES):
            links.append(absolute)
    unique = list(dict.fromkeys(links))
    if not unique:
        raise ValueError("Landing page has no data file")
    dated = [(link, _date_score(link)) for link in unique]
    scores = [score for _link, score in dated if score is not None]
    if scores and len(scores) != len(dated):
        raise ValueError("Landing page mixes dated and undated files")
    if scores:
        best = max(scores)
        winners = [link for link, score in dated if score == best]
        if len(winners) != 1:
            raise ValueError("Landing page has more than one newest file")
        return winners[0]
    modified = [_last_modified(transport, link, timeout) for link in unique]
    best_time = max(modified)
    winners = [link for link, stamp in zip(unique, modified, strict=True) if stamp == best_time]
    if len(winners) != 1:
        raise ValueError("Landing page has more than one newest file")
    return winners[0]


def _date_score(link: str) -> tuple[int, int, int] | None:
    matches = list(_DATE.finditer(urlparse(link).path))
    if not matches:
        return None
    scores = []
    for match in matches:
        year = int(match.group(1))
        month = int(match.group(2) or 0)
        day = int(match.group(3) or 0)
        scores.append((year, month, day))
    return max(scores)


def _last_modified(transport: Transport, link: str, timeout: float) -> datetime:
    response = transport.request("HEAD", link, params=None, headers=None, data=None, timeout=timeout)
    if response.status_code != 200:
        raise ValueError(f"Discovered file returned HTTP {response.status_code}")
    raw = None
    for key, value in response.headers.items():
        if key.lower() == "last-modified":
            raw = value
    if not raw:
        raise ValueError("Discovered file has no Last-Modified date")
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Discovered file has an unreadable Last-Modified date") from exc
    if parsed.tzinfo is None:
        raise ValueError("Discovered file has an unreadable Last-Modified date")
    return parsed
