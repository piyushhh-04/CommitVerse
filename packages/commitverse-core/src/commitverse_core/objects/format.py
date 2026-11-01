"""Serialize and hash canonical Git-compatible object bytes."""

from hashlib import sha1

_SUPPORTED_OBJECT_TYPES = ("blob", "tree", "commit")


def serialize_object(object_type: str, payload: bytes) -> bytes:
    """Return canonical object bytes for a supported type and byte payload."""
    if object_type not in _SUPPORTED_OBJECT_TYPES:
        raise ValueError(f"unsupported object type: {object_type!r}")
    if not isinstance(payload, bytes):
        raise TypeError("object payload must be bytes")

    header = f"{object_type} {len(payload)}".encode("ascii") + b"\0"
    return header + payload


def hash_object(object_type: str, payload: bytes) -> str:
    """Return the SHA-1 hex digest of an object's canonical bytes."""
    return sha1(serialize_object(object_type, payload)).hexdigest()
