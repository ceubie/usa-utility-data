"""Run the release stages in order and resume from a status file.

A release folder is written only while its pipeline status is open. A folder
without a status file, such as data/releases/2026Q4.1, is a finished release and
is refused, as is a run that finished every stage and was sealed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

STAGES = (
    "validate",
    "promote",
    "silver_water",
    "core_water",
    "release_water",
    "electric",
    "wastewater",
    "gas",
    "cross",
    "assemble",
    "graph_export",
    "contracts",
    "graph_load",
)
STATES = frozenset({"pending", "running", "done", "failed", "skipped"})


@dataclass(frozen=True)
class StageContext:
    home: Path
    raw: Path
    repository_root: Path
    registry_dir: Path
    quarter: str
    release_id: str

    @property
    def release(self) -> Path:
        return self.home / "releases" / self.release_id


class StageSkipped(Exception):
    """A stage that cannot run here. It is retried on the next run."""


Stage = Callable[[StageContext], Mapping[str, object] | None]


def status_path(home: Path, release_id: str) -> Path:
    return home / "releases" / release_id / "pipeline_status.json"


def _new_status() -> dict[str, object]:
    return {"sealed": False, "stages": {stage: "pending" for stage in STAGES}, "reasons": {}}


def _read(path: Path) -> dict[str, object]:
    status = json.loads(path.read_text(encoding="utf-8"))
    stages = status.get("stages") if isinstance(status, dict) else None
    if not isinstance(stages, dict) or set(stages) != set(STAGES) or not set(stages.values()) <= STATES:
        raise ValueError(f"Pipeline status does not list the stages {', '.join(STAGES)}: {path.name}")
    return status


def _refuse_closed(home: Path, release_id: str) -> None:
    path = status_path(home, release_id)
    if not path.is_file():
        raise ValueError(f"{release_id} is a finished release without a pipeline status; build into a new release id")
    if _read(path)["sealed"]:
        raise ValueError(f"{release_id} is sealed; build into a new release id")


def open_release(home: Path, release_id: str) -> Path:
    """Return the release folder for writing, creating it with an open status when it is new.

    Only the commands that start a release call this; the sector builds add to one.
    """
    release = home / "releases" / release_id
    if not release.exists():
        release.mkdir(parents=True)
        _write(status_path(home, release_id), _new_status())
        return release
    _refuse_closed(home, release_id)
    return release


def writable_release_if_present(home: Path, release_id: str) -> Path | None:
    """Return an open release folder, or None when it has not been started."""
    release = home / "releases" / release_id
    if not release.exists():
        return None
    _refuse_closed(home, release_id)
    return release


def writable_release(home: Path, release_id: str) -> Path:
    """Return an open release folder that `release water` or `pipeline run` already started."""
    release = writable_release_if_present(home, release_id)
    if release is None:
        raise FileNotFoundError(f"Release {release_id} has not been started; run `release water` or `pipeline run` first")
    return release


def begin_run(home: Path, release_id: str, *, resume: bool, from_stage: str | None) -> dict[str, object]:
    """Create or reopen the status file. A finished, sealed, or unresumed folder is refused."""
    if from_stage is not None and from_stage not in STAGES:
        raise ValueError(f"Unknown pipeline stage: {from_stage}")
    release = home / "releases" / release_id
    existed = release.exists()
    open_release(home, release_id)
    if existed and not resume and from_stage is None:
        raise FileExistsError(f"Release folder already exists: {release_id}; pass --resume or --from-stage")
    path = status_path(home, release_id)
    status = _read(path)
    if from_stage is not None:
        stages = status["stages"]
        for stage in STAGES[STAGES.index(from_stage):]:
            stages[stage] = "pending"
    _write(path, status)
    return status


def mark(home: Path, release_id: str, stage: str, state: str, reason: str | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unknown pipeline stage: {stage}")
    if state not in STATES:
        raise ValueError(f"Unknown pipeline state: {state}")
    path = status_path(home, release_id)
    status = _read(path)
    status["stages"][stage] = state
    reasons = status["reasons"]
    if reason:
        reasons[stage] = reason
    else:
        reasons.pop(stage, None)
    _write(path, status)


def next_stage(status: Mapping[str, object]) -> str | None:
    stages = status["stages"]
    for stage in STAGES:
        if stages.get(stage) != "done":
            return stage
    return None


def run_pipeline(
    context: StageContext,
    stages: Mapping[str, Stage],
    *,
    resume: bool,
    from_stage: str | None,
    echo: Callable[[str], None] = print,
) -> dict[str, object]:
    """Run every stage that is not done, in order. A failure stops the run; a skip is retried later."""
    missing = [stage for stage in STAGES if stage not in stages]
    if missing or set(stages) - set(STAGES):
        raise ValueError(f"Stage functions do not match the pipeline stages: {', '.join(missing) or 'extra stages'}")
    status = begin_run(context.home, context.release_id, resume=resume, from_stage=from_stage)
    summaries = context.release / "pipeline"
    for stage in STAGES:
        if status["stages"][stage] == "done":
            continue
        mark(context.home, context.release_id, stage, "running")
        echo(f"{stage}: running")
        try:
            summary = stages[stage](context)
        except StageSkipped as exc:
            mark(context.home, context.release_id, stage, "skipped", str(exc))
            echo(f"{stage}: skipped; {exc}")
            continue
        except Exception as exc:
            mark(context.home, context.release_id, stage, "failed", f"{type(exc).__name__}: {exc}")
            raise
        summaries.mkdir(parents=True, exist_ok=True)
        (summaries / f"{stage}.json").write_text(json.dumps(summary or {}, indent=2, default=str) + "\n", encoding="utf-8")
        mark(context.home, context.release_id, stage, "done")
        echo(f"{stage}: done")
    path = status_path(context.home, context.release_id)
    status = _read(path)
    if next_stage(status) is None:
        status["sealed"] = True
        _write(path, status)
    return status


def _write(path: Path, status: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
