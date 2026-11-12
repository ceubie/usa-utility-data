"""Load N-Triples into Fuseki and publish only the local query service."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from utilitydata.core.config import (
    GRAPH_QUERY_HOST,
    GRAPH_QUERY_PORT,
)
from utilitydata.graph.ontology import write_assembler
from utilitydata.graph.store import SparqlStore, query_url

JENA_VERSION = "6.2.0"
IMAGE = f"utilitydata-fuseki:{JENA_VERSION}"
CONTAINER = "utilitydata-fuseki"
DATABASE_VOLUME_PREFIX = "utilitydata-tdb2-"
_RELEASE = re.compile(r"[A-Za-z0-9._-]+")
_LOADER = f"/opt/apache-jena-{JENA_VERSION}/bin/tdb2.tdbloader"
_SERVER = f"/opt/apache-jena-fuseki-{JENA_VERSION}/fuseki-server"


@dataclass(frozen=True)
class FusekiStatus:
    """Result of a local Fuseki load. started is false when the server is not running."""

    docker_available: bool
    started: bool
    loaded: bool
    reason: str
    load_command: str
    server_command: str
    query_url: str


def database_volume(release_id: str) -> str:
    """Return the TDB2 volume for one release, so a load never replaces another release's store."""
    if not _RELEASE.fullmatch(release_id):
        raise ValueError("Release id has an unexpected form")
    return DATABASE_VOLUME_PREFIX + release_id


def documented_commands(release_id: str) -> tuple[str, str]:
    """Return the load and server commands without a machine-specific path."""
    volume = database_volume(release_id)
    load = (
        "docker run --rm --entrypoint "
        f"{_LOADER} -e JAVA_TOOL_OPTIONS=-Xmx4g "
        f'-v "$UTILITYDATA_HOME/releases/{release_id}/graph:/staging:ro" '
        f"-v {volume}:/fuseki/databases/utility "
        f"{IMAGE} --loc /fuseki/databases/utility /staging/graph.nt"
    )
    server = (
        "docker run --detach --name "
        f"{CONTAINER} -p {GRAPH_QUERY_HOST}:{GRAPH_QUERY_PORT}:3030 "
        '-e JAVA_TOOL_OPTIONS=-Xmx4g -e FUSEKI_BASE=/tmp/fuseki-base '
        f"-v {volume}:/fuseki/databases/utility "
        '-v "$REPOSITORY/graph/fuseki/assembler.ttl:/fuseki/assembler.ttl:ro" '
        f"--entrypoint {_SERVER} {IMAGE} --conf=/fuseki/assembler.ttl"
    )
    return load, server


def load_and_serve(home: Path, repository_root: Path, release_id: str, nt_path: Path) -> FusekiStatus:
    """Bulk-load TDB2 and start Fuseki on the loopback interface when Docker is available."""
    load_text, server_text = documented_commands(release_id)
    resolved = nt_path.resolve()
    if not resolved.is_file() or not resolved.is_relative_to(home.resolve()):
        raise ValueError("N-Triples export is outside the data directory")
    if GRAPH_QUERY_HOST != "127.0.0.1":
        raise ValueError("Fuseki must be published on the loopback interface")
    if shutil.which("docker") is None:
        return FusekiStatus(False, False, False, "Docker is not available", load_text, server_text, query_url())
    info = subprocess.run(["docker", "info"], check=False, capture_output=True, text=True)
    if info.returncode != 0:
        return FusekiStatus(False, False, False, "Docker is not running", load_text, server_text, query_url())
    image_dir = repository_root / "graph" / "fuseki"
    build = subprocess.run(["docker", "build", "-t", IMAGE, str(image_dir)], check=False, capture_output=True, text=True)
    if build.returncode != 0:
        return FusekiStatus(True, False, False, _tail(build.stderr), load_text, server_text, query_url())
    volume = database_volume(release_id)
    subprocess.run(["docker", "volume", "rm", "--force", volume], check=False, capture_output=True, text=True)
    created = subprocess.run(["docker", "volume", "create", volume], check=False, capture_output=True, text=True)
    if created.returncode != 0:
        return FusekiStatus(True, False, False, _tail(created.stderr or created.stdout), load_text, server_text, query_url())
    assembler = write_assembler(repository_root)
    load = subprocess.run(
        _load_command(nt_path, volume),
        check=False,
        capture_output=True,
        text=True,
        timeout=90 * 60,
    )
    if load.returncode != 0:
        return FusekiStatus(True, False, False, _tail(load.stderr or load.stdout), load_text, server_text, query_url())
    subprocess.run(["docker", "rm", "--force", CONTAINER], check=False, capture_output=True, text=True)
    server = subprocess.run(_server_command(assembler, volume), check=False, capture_output=True, text=True)
    if server.returncode != 0:
        return FusekiStatus(True, False, True, _tail(server.stderr or server.stdout), load_text, server_text, query_url())
    try:
        ready = _wait_until_ready()
    except (OSError, ValueError) as exc:
        return FusekiStatus(True, False, True, str(exc), load_text, server_text, query_url())
    if not ready:
        return FusekiStatus(True, True, True, "Fuseki answered but the dataset is empty", load_text, server_text, query_url())
    return FusekiStatus(True, True, True, "Fuseki is serving the query endpoint", load_text, server_text, query_url())


def _wait_until_ready() -> bool:
    """Poll the query service until Fuseki accepts a request or a minute passes."""
    deadline = time.monotonic() + 60
    last = "SPARQL query service did not answer"
    while True:
        try:
            return SparqlStore(timeout_s=5).ask("ASK { ?s ?p ?o }")
        except (OSError, ValueError) as exc:
            last = str(exc)
            if time.monotonic() >= deadline:
                raise ValueError(last) from exc
            time.sleep(1)


def _load_command(nt_path: Path, volume: str) -> list[str]:
    return [
        "docker", "run", "--rm",
        "--entrypoint", _LOADER,
        "-e", "JAVA_TOOL_OPTIONS=-Xmx4g",
        "-v", f"{nt_path.parent.resolve()}:/staging:ro",
        "-v", f"{volume}:/fuseki/databases/utility",
        IMAGE,
        "--loc", "/fuseki/databases/utility",
        f"/staging/{nt_path.name}",
    ]


def _server_command(assembler: Path, volume: str) -> list[str]:
    publish = f"{GRAPH_QUERY_HOST}:{GRAPH_QUERY_PORT}:3030"
    if not publish.startswith("127.0.0.1:"):
        raise ValueError("Fuseki must be published on the loopback interface")
    return [
        "docker", "run", "--detach",
        "--name", CONTAINER,
        "-p", publish,
        "-e", "JAVA_TOOL_OPTIONS=-Xmx4g",
        "-e", "FUSEKI_BASE=/tmp/fuseki-base",
        "-v", f"{volume}:/fuseki/databases/utility",
        "-v", f"{assembler.resolve()}:/fuseki/assembler.ttl:ro",
        "--entrypoint", _SERVER,
        IMAGE,
        "--conf=/fuseki/assembler.ttl",
    ]


def _tail(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-12:]) if lines else "Docker command failed"
