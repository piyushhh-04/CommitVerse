"""Session-bound CSRF token generation and validation."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Collection
from urllib.parse import urlsplit

from commitverse_hub.auth.tokens import generate_session_token, validate_session_token

_CSRF_DOMAIN = b"CommitVerse Hub CSRF v1\x00"
_CSRF_SIGNATURE_LENGTH = hashlib.sha256().digest_size * 2
_CSRF_TOKEN_LENGTH = 43 + 1 + _CSRF_SIGNATURE_LENGTH
_CSRF_SIGNATURE_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


class CsrfValidationError(ValueError):
    """Raised when a request fails CSRF token or Origin validation."""


def generate_csrf_token(session_token: str) -> str:
    """Generate a random CSRF token cryptographically bound to one session."""
    if not validate_session_token(session_token):
        raise ValueError("Session token is malformed.")
    nonce = generate_session_token()
    signature = hmac.new(
        session_token.encode("ascii"),
        _CSRF_DOMAIN + nonce.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{signature}"


def validate_csrf_token(session_token: str, csrf_token: object) -> bool:
    """Validate token shape and its constant-time HMAC against a session."""
    if (
        not validate_session_token(session_token)
        or not isinstance(csrf_token, str)
        or len(csrf_token) != _CSRF_TOKEN_LENGTH
    ):
        return False
    nonce, separator, supplied_signature = csrf_token.partition(".")
    if (
        separator != "."
        or not validate_session_token(nonce)
        or not _CSRF_SIGNATURE_PATTERN.fullmatch(supplied_signature)
    ):
        return False
    expected_signature = hmac.new(
        session_token.encode("ascii"),
        _CSRF_DOMAIN + nonce.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, supplied_signature)


def validate_request_origin(
    origin: str | None,
    allowed_origins: Collection[str],
) -> bool:
    """Require an exact, explicitly allow-listed Origin; wildcards never match."""
    if (
        not isinstance(origin, str)
        or not _is_http_origin(origin)
        or not allowed_origins
        or "*" in allowed_origins
        or not all(_is_http_origin(allowed) for allowed in allowed_origins)
    ):
        return False
    return origin in allowed_origins


def _is_http_origin(value: str) -> bool:
    if not isinstance(value, str) or value == "null":
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


def require_csrf_protection(
    session_token: str,
    csrf_token: object,
    origin: str | None,
    allowed_origins: Collection[str],
) -> None:
    """Reject missing, invalid, or non-allow-listed request CSRF credentials."""
    if not validate_request_origin(origin, allowed_origins) or not validate_csrf_token(
        session_token, csrf_token
    ):
        raise CsrfValidationError("CSRF validation failed.")
