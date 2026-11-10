"""Validated authentication-cookie configuration and response helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import Response

from commitverse_hub.auth.tokens import validate_session_token

_COOKIE_NAME_PATTERN = re.compile(r"\A[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_COOKIE_DOMAIN_PATTERN = re.compile(
    r"\A(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?))*\Z"
)
_SAME_SITE_VALUES = frozenset({"lax", "strict", "none"})
_MAX_COOKIE_AGE_SECONDS = 60 * 60 * 24 * 365


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


@dataclass(frozen=True, slots=True)
class AuthCookieSettings:
    """Cookie attributes used for the opaque browser session."""

    name: str = "commitverse_session"
    secure: bool = True
    httponly: bool = True
    samesite: str = "lax"
    path: str = "/"
    domain: str | None = None
    max_age_seconds: int = 60 * 60 * 24 * 30

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _COOKIE_NAME_PATTERN.fullmatch(self.name):
            raise ValueError("Session cookie name is invalid.")
        if not isinstance(self.secure, bool):
            raise ValueError("Session cookie secure flag must be boolean.")
        if self.httponly is not True:
            raise ValueError("Session cookies must be HttpOnly.")
        if not isinstance(self.samesite, str) or self.samesite.lower() not in _SAME_SITE_VALUES:
            raise ValueError("Session cookie SameSite must be Lax, Strict, or None.")
        if self.samesite.lower() == "none" and not self.secure:
            raise ValueError("SameSite=None requires a Secure session cookie.")
        if (
            not isinstance(self.path, str)
            or not self.path.startswith("/")
            or any(character in self.path for character in ";\r\n")
        ):
            raise ValueError("Session cookie path must be an absolute cookie path.")
        if self.domain is not None and (
            not isinstance(self.domain, str)
            or "*" in self.domain
            or not _COOKIE_DOMAIN_PATTERN.fullmatch(self.domain)
        ):
            raise ValueError("Session cookie domain must be an explicit host name.")
        if (
            not isinstance(self.max_age_seconds, int)
            or isinstance(self.max_age_seconds, bool)
            or not 1 <= self.max_age_seconds <= _MAX_COOKIE_AGE_SECONDS
        ):
            raise ValueError("Session cookie max age must be between 1 second and 1 year.")
        object.__setattr__(self, "samesite", self.samesite.lower())

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str],
    ) -> AuthCookieSettings:
        """Create validated cookie settings from Hub environment values."""
        secure_value = values.get("HUB_SESSION_COOKIE_SECURE", "true")
        httponly_value = values.get("HUB_SESSION_COOKIE_HTTPONLY", "true")
        domain = values.get("HUB_SESSION_COOKIE_DOMAIN") or None
        max_age_value = values.get("HUB_SESSION_COOKIE_MAX_AGE", "2592000")
        try:
            max_age = int(max_age_value)
        except ValueError:
            raise ValueError("HUB_SESSION_COOKIE_MAX_AGE must be an integer.") from None
        return cls(
            name=values.get("HUB_SESSION_COOKIE_NAME", "commitverse_session"),
            secure=_parse_bool("HUB_SESSION_COOKIE_SECURE", secure_value),
            httponly=_parse_bool("HUB_SESSION_COOKIE_HTTPONLY", httponly_value),
            samesite=values.get("HUB_SESSION_COOKIE_SAMESITE", "lax"),
            path=values.get("HUB_SESSION_COOKIE_PATH", "/"),
            domain=domain,
            max_age_seconds=max_age,
        )


def set_session_cookie(
    response: Response,
    token: str,
    settings: AuthCookieSettings,
) -> None:
    """Set a validated opaque session token using the configured attributes."""
    if not validate_session_token(token):
        raise ValueError("Session token is malformed.")
    response.set_cookie(
        key=settings.name,
        value=token,
        max_age=settings.max_age_seconds,
        path=settings.path,
        domain=settings.domain,
        secure=settings.secure,
        httponly=True,
        samesite=settings.samesite,
    )


def clear_session_cookie(response: Response, settings: AuthCookieSettings) -> None:
    """Expire the session cookie using the same scope and security attributes."""
    response.delete_cookie(
        key=settings.name,
        path=settings.path,
        domain=settings.domain,
        secure=settings.secure,
        httponly=True,
        samesite=settings.samesite,
    )
