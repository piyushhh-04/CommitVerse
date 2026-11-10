"""Validated environment-based application settings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from commitverse_hub.auth.cookies import AuthCookieSettings
from commitverse_hub.auth.csrf import validate_request_origin

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
    auth_cookie: AuthCookieSettings = field(default_factory=AuthCookieSettings)
    csrf_allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://localhost:3000",
        "https://localhost:5173",
        "https://127.0.0.1:3000",
        "https://127.0.0.1:5173",
    )
    repository_storage_root: Path = field(
        default_factory=lambda: Path.home() / ".commitverse" / "repositories"
    )

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
        if self.environment == "production" and not self.auth_cookie.secure:
            raise ValueError("Session cookies must be Secure in production.")
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
        if not self.csrf_allowed_origins:
            raise ValueError("csrf_allowed_origins must contain at least one allow-listed origin.")
        for origin in self.csrf_allowed_origins:
            if not isinstance(origin, str) or not validate_request_origin(origin, set(self.csrf_allowed_origins)):
                raise ValueError(f"CSRF allow-list contains an invalid origin: {origin!r}.")
        storage_root = Path(self.repository_storage_root).expanduser()
        if (
            not storage_root.is_absolute()
            or ".." in storage_root.parts
            or len(storage_root.parts) < 3
        ):
            raise ValueError(
                "HUB_REPOSITORY_STORAGE_ROOT must be an absolute dedicated directory path."
            )
        object.__setattr__(self, "application_name", self.application_name.strip())
        object.__setattr__(self, "log_level", normalized_log_level)
        object.__setattr__(self, "repository_storage_root", storage_root)

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> Settings:
        """Create settings from process environment or a supplied mapping."""
        values = os.environ if environ is None else environ
        debug_value = values.get("HUB_DEBUG", "false")
        raw_allowed_origins = values.get("HUB_CSRF_ALLOWED_ORIGINS") or values.get(
            "HUB_ALLOWED_ORIGINS"
        )
        if raw_allowed_origins:
            parsed_origins = tuple(
                origin.strip() for origin in raw_allowed_origins.split(",") if origin.strip()
            )
        else:
            parsed_origins = (
                "http://localhost:3000",
                "http://localhost:5173",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:5173",
                "https://localhost:3000",
                "https://localhost:5173",
                "https://127.0.0.1:3000",
                "https://127.0.0.1:5173",
            )
        return cls(
            application_name=values.get("HUB_APPLICATION_NAME", "CommitVerse Hub"),
            api_version=values.get("HUB_API_VERSION", "0.1.0"),
            environment=values.get("HUB_ENVIRONMENT", "development").strip().lower(),
            debug=_parse_bool("HUB_DEBUG", debug_value),
            log_level=values.get("HUB_LOG_LEVEL", "INFO"),
            api_prefix=values.get("HUB_API_PREFIX", "/api/v1"),
            database_url=values.get("HUB_DATABASE_URL"),
            auth_cookie=AuthCookieSettings.from_environment(values),
            csrf_allowed_origins=parsed_origins,
            repository_storage_root=Path(
                values.get(
                    "HUB_REPOSITORY_STORAGE_ROOT",
                    str(Path.home() / ".commitverse" / "repositories"),
                )
            ).expanduser(),
        )
