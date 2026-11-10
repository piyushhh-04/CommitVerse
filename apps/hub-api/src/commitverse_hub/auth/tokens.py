"""Opaque high-entropy session-token primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

_SESSION_TOKEN_BYTES = 32
_SESSION_TOKEN_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{43}\Z")
_TOKEN_HASH_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


def generate_session_token() -> str:
    """Generate an opaque URL-safe token containing 256 bits of entropy."""
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def validate_session_token(token: object) -> bool:
    """Validate the canonical encoding and entropy-sized shape of a token."""
    if not isinstance(token, str) or not _SESSION_TOKEN_PATTERN.fullmatch(token):
        return False
    try:
        decoded = base64.urlsafe_b64decode(token + "=")
    except (ValueError, UnicodeEncodeError):
        return False
    return (
        len(decoded) == _SESSION_TOKEN_BYTES
        and base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") == token
    )


def hash_session_token(token: str) -> str:
    """Return the SHA-256 digest of a valid high-entropy session token."""
    if not validate_session_token(token):
        raise ValueError("Session token is malformed.")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def compare_token_hashes(left: str, right: str) -> bool:
    """Compare canonical token digests in constant time."""
    if (
        not isinstance(left, str)
        or not isinstance(right, str)
        or not _TOKEN_HASH_PATTERN.fullmatch(left)
        or not _TOKEN_HASH_PATTERN.fullmatch(right)
    ):
        return False
    return hmac.compare_digest(left, right)
