"""Validated environment-based application settings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_ENVIRONMENTS = frozenset({"development", "testing", "production"})
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VERSION_PATTERN = re.compile(r"\A\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z")
_API_PREFIX_PATTERN = re.compile(r"\A/(?:[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)\Z")


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated configuration needed to construct the Hub API."""

    application_name: str = "CommitVerse Hub"
    api_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.application_name.strip() or len(self.application_name) > 120:
            raise ValueError("application_name must contain 1 to 120 characters.")
        if not _VERSION_PATTERN.fullmatch(self.api_version):
            raise ValueError("api_version must be a semantic version.")
        if self.environment not in _ENVIRONMENTS:
            choices = ", ".join(sorted(_ENVIRONMENTS))
            raise ValueError(f"environment must be one of: {choices}.")
        normalized_log_level = self.log_level.upper()
        if normalized_log_level not in _LOG_LEVELS:
            choices = ", ".join(sorted(_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {choices}.")
        if not _API_PREFIX_PATTERN.fullmatch(self.api_prefix):
            raise ValueError("api_prefix must be an absolute path without a trailing slash.")
        if self.environment == "production" and self.debug:
            raise ValueError("debug must be disabled in production.")
        if self.database_url is not None:
            if not isinstance(self.database_url, str) or not self.database_url.strip():
                raise ValueError("HUB_DATABASE_URL must be a non-empty PostgreSQL URL.")
            try:
                database_url = make_url(self.database_url)
            except ArgumentError:
                raise ValueError("HUB_DATABASE_URL must be a valid PostgreSQL URL.") from None
            if (
                database_url.drivername != "postgresql+psycopg"
                or not database_url.host
                or not database_url.database
            ):
                raise ValueError(
                    "HUB_DATABASE_URL must use postgresql+psycopg and include a host and database."
                )
        object.__setattr__(self, "application_name", self.application_name.strip())
        object.__setattr__(self, "log_level", normalized_log_level)

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> Settings:
        """Create settings from process environment or a supplied mapping."""
        values = os.environ if environ is None else environ
        debug_value = values.get("HUB_DEBUG", "false")
        return cls(
            application_name=values.get("HUB_APPLICATION_NAME", "CommitVerse Hub"),
            api_version=values.get("HUB_API_VERSION", "0.1.0"),
            environment=values.get("HUB_ENVIRONMENT", "development").strip().lower(),
            debug=_parse_bool("HUB_DEBUG", debug_value),
            log_level=values.get("HUB_LOG_LEVEL", "INFO"),
            api_prefix=values.get("HUB_API_PREFIX", "/api/v1"),
            database_url=values.get("HUB_DATABASE_URL"),
        )
