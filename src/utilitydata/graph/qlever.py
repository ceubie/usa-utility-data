"""QLever index and query server. Fuseki stays the default until parity is shown.

The server binds to the loopback interface and has no update access. The index
lives under ``data/qlever/<release_id>``. This module does not start a live
server when Docker or the index is missing.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from utilitydata.core.config import GRAPH_QLEVER_PORT, GRAPH_QUERY_HOST
from utilitydata.pipeline import validate_release_id

# No image digest is recorded. The live server is not started until a digest is pinned and parity is shown.
QLEVER_IMAGE = None
INDEX_DIR_NAME = "qlever"


@dataclass(frozen=True)
class QleverStatus:
    """Result of a QLever load. started is false when no live server was launched."""

    docker_available: bool
    started: bool
    loaded: bool
    reason: str
    index_dir: str
    query_url: str


def qlever_query_url(host: str = GRAPH_QUERY_HOST, port: int = GRAPH_QLEVER_PORT) -> str:
    """Return the loopback QLever query URL."""
    if host != "127.0.0.1":
        raise ValueError("QLever must bind to the loopback interface")
    if port < 1 or port > 65535:
        raise ValueError("QLever port is invalid")
    return f"http://{host}:{port}"


def index_dir(home: Path, release_id: str) -> Path:
    """Return the release index directory. The path stays under the data root."""
    destination = home / INDEX_DIR_NAME / validate_release_id(release_id)
    if not destination.resolve().is_relative_to(home.resolve()):
        raise ValueError("QLever index path escapes the data root")
    return destination


def load_and_serve(home: Path, release_id: str, nt_path: Path) -> QleverStatus:
    """Report whether a live QLever server can be used. Do not become the default engine."""
    url = qlever_query_url()
    directory = index_dir(home, release_id)
    resolved = nt_path.resolve()
    if not resolved.is_file() or not resolved.is_relative_to(home.resolve()):
        raise ValueError("N-Triples export is outside the data directory")
    if shutil.which("docker") is None:
        return QleverStatus(False, False, False, "Docker is not available", directory.as_posix(), url)
    if not directory.is_dir():
        return QleverStatus(True, False, False, "QLever index is not built; live server was not started", directory.as_posix(), url)
    return QleverStatus(
        True,
        False,
        False,
        "QLever stays off by default until parity with Fuseki is shown",
        directory.as_posix(),
        url,
    )
