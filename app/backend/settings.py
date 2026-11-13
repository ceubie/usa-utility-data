"""Runtime settings. Every value comes from the environment."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utilitydata.core.config import DEFAULT_RELEASE_ID
from utilitydata.graph.literals import require_base
from utilitydata.pipeline import release_dir, validate_release_id

_LOOPBACK = frozenset({"127.0.0.1", "localhost"})


def repository_root() -> Path:
    """Return the repository root that contains this package."""
    return Path(__file__).resolve().parents[2]


def _load_dotenv_defaults() -> None:
    """Populate unset environment variables from .env or app/backend/.env once at import."""
    root = repository_root()
    for candidate in (root / ".env", root / "app" / "backend" / ".env"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value:
                os.environ.setdefault(key, value)


_load_dotenv_defaults()


class Settings(BaseSettings):
    """Process environment for the local API. The model key is never displayed."""

    model_config = SettingsConfigDict(extra="ignore")

    sparql_query_url: str = "http://127.0.0.1:3030/utility/query"
    utilitydata_release: str = DEFAULT_RELEASE_ID
    graph_base_iri: str = "http://utilities.local/"
    utilitydata_home: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2025-04-01-preview"
    row_limit: int = 1000
    query_timeout_s: int = 20
    require_auth: bool = False
    proxy_shared_secret: str | None = None
    max_tool_rounds: int = 10

    @field_validator("sparql_query_url")
    @classmethod
    def _loopback_query_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK:
            raise ValueError("SPARQL_QUERY_URL must use the loopback interface")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("SPARQL_QUERY_URL must not include credentials")
        return value.strip()

    @field_validator("graph_base_iri")
    @classmethod
    def _base_iri(cls, value: str) -> str:
        return require_base(value.strip())

    @field_validator("utilitydata_release")
    @classmethod
    def _release_name(cls, value: str) -> str:
        return validate_release_id(value)

    @field_validator("row_limit", "query_timeout_s", "max_tool_rounds")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Numeric settings must be at least 1")
        return value

    @property
    def data_home(self) -> Path:
        if self.utilitydata_home:
            home = Path(self.utilitydata_home).expanduser()
            if not home.is_absolute():
                raise ValueError("UTILITYDATA_HOME must be an absolute path")
            return home
        return repository_root() / "data"

    @property
    def release_dir(self) -> Path:
        return release_dir(self.data_home, self.utilitydata_release)

    def missing_llm(self) -> list[str]:
        """Return the names of model settings that are unset. Values are not included."""
        missing: list[str] = []
        if not (self.azure_openai_endpoint or "").strip():
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not (self.azure_openai_deployment or "").strip():
            missing.append("AZURE_OPENAI_DEPLOYMENT")
        if not (self.azure_openai_api_key or "").strip():
            missing.append("AZURE_OPENAI_API_KEY")
        return missing

    @property
    def llm_configured(self) -> bool:
        return not self.missing_llm()

    def __repr__(self) -> str:
        return (
            "Settings("
            f"release={self.utilitydata_release!r}, "
            f"row_limit={self.row_limit}, "
            f"llm_endpoint_set={bool((self.azure_openai_endpoint or '').strip())}, "
            f"llm_deployment_set={bool((self.azure_openai_deployment or '').strip())}, "
            f"llm_key_set={bool((self.azure_openai_api_key or '').strip())})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings. Tests clear the cache after changing the environment."""
    return Settings()
