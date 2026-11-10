"""Resolve platform storage locations without machine-specific paths."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    """Storage roots; generated data lives under the configured data home."""

    home: Path
    raw: Path

    @classmethod
    def from_environment(cls, *, repository_root: Path | None = None) -> "DataPaths":
        """Resolve storage, requiring an explicit home to prevent accidental moves."""
        configured_home = os.environ.get("UTILITYDATA_HOME")
        if not configured_home:
            raise ValueError("Set UTILITYDATA_HOME to the platform data directory")
        home = Path(configured_home).expanduser()
        if not home.is_absolute():
            raise ValueError("UTILITYDATA_HOME must be an absolute path")
        root = repository_root if repository_root is not None else Path(__file__).resolve().parents[2]
        return cls(home=home.resolve(), raw=root.resolve() / "collection" / "data")

    @property
    def legacy(self) -> Path:
        return self.home / "legacy"

    @property
    def snapshots(self) -> Path:
        return self.home / "snapshots"

    @property
    def silver(self) -> Path:
        return self.home / "silver"

    @property
    def core(self) -> Path:
        return self.home / "core"

    @property
    def releases(self) -> Path:
        return self.home / "releases"

    @property
    def state(self) -> Path:
        return self.home / "state"
