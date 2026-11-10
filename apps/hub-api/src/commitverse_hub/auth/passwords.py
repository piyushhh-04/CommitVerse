"""Argon2id password hashing primitives."""

from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_MAX_PASSWORD_BYTES = 1024
_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def _validated_password(password: object) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string.")
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds the maximum supported length.")
    return password


def hash_password(password: object) -> str:
    """Return a salted Argon2id hash for a non-empty password."""
    return _PASSWORD_HASHER.hash(_validated_password(password))


def verify_password(encoded_hash: str, password: object) -> bool:
    """Verify a password, returning false for malformed hashes or bad input."""
    if not isinstance(encoded_hash, str) or not encoded_hash:
        return False
    try:
        return _PASSWORD_HASHER.verify(encoded_hash, _validated_password(password))
    except (InvalidHashError, VerificationError, VerifyMismatchError, ValueError):
        return False


def password_needs_rehash(encoded_hash: str) -> bool:
    """Report whether a valid hash uses outdated parameters or is malformed."""
    if not isinstance(encoded_hash, str) or not encoded_hash:
        return True
    try:
        return _PASSWORD_HASHER.check_needs_rehash(encoded_hash)
    except (InvalidHashError, VerificationError, ValueError):
        return True
