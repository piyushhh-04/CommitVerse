"""Serialize, parse, and store Git-compatible commit objects."""

import re
from dataclasses import dataclass
from pathlib import Path

from commitverse_core.objects.store import read_object, write_object

_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_IDENTITY_PATTERN = re.compile(
    rb"(.+) <([^<>]+)> (-?(?:0|[1-9][0-9]*)) ([+-])([0-9]{2})([0-9]{2})\Z"
)


class CommitError(ValueError):
    """Raised when a commit value or payload is malformed."""


@dataclass(frozen=True)
class CommitIdentity:
    """An author or committer identity and its Git timestamp/timezone."""

    name: str
    email: str
    timestamp: int
    timezone_offset: int


@dataclass(frozen=True)
class Commit:
    """The supported fields of a Git commit payload."""

    tree_id: str
    parent_ids: tuple[str, ...]
    author: CommitIdentity
    committer: CommitIdentity
    message: bytes


def _validate_object_id(object_id: str, field: str) -> None:
    if (
        not isinstance(object_id, str)
        or _OBJECT_ID_PATTERN.fullmatch(object_id) is None
    ):
        raise CommitError(f"{field} must be 40 lowercase hexadecimal characters")


def _identity_bytes(identity: CommitIdentity, field: str) -> bytes:
    if not isinstance(identity, CommitIdentity):
        raise CommitError(f"{field} must be a CommitIdentity")
    if not isinstance(identity.name, str) or not identity.name:
        raise CommitError(f"{field} name must not be empty")
    if not isinstance(identity.email, str) or not identity.email:
        raise CommitError(f"{field} email must not be empty")
    if any(character in identity.name + identity.email for character in "\r\n\0"):
        raise CommitError(f"{field} must not contain line breaks or NUL bytes")
    if "<" in identity.email or ">" in identity.email:
        raise CommitError(f"{field} email must not contain angle brackets")
    if not isinstance(identity.timestamp, int):
        raise CommitError(f"{field} timestamp must be an integer")
    if (
        not isinstance(identity.timezone_offset, int)
        or abs(identity.timezone_offset) > 23 * 60 + 59
    ):
        raise CommitError(f"{field} timezone offset must be between -23:59 and +23:59")

    sign = "-" if identity.timezone_offset < 0 else "+"
    hours, minutes = divmod(abs(identity.timezone_offset), 60)
    return (
        f"{identity.name} <{identity.email}> {identity.timestamp} "
        f"{sign}{hours:02d}{minutes:02d}"
    ).encode("utf-8")


def serialize_commit(commit: Commit) -> bytes:
    """Encode the supported commit headers followed by the exact message bytes."""
    if not isinstance(commit, Commit):
        raise CommitError("commit must be a Commit value")
    _validate_object_id(commit.tree_id, "tree object ID")
    if not isinstance(commit.parent_ids, tuple):
        raise CommitError("parent object IDs must be a tuple")
    for parent_id in commit.parent_ids:
        _validate_object_id(parent_id, "parent object ID")
    if not isinstance(commit.message, bytes):
        raise CommitError("commit message must be bytes")

    headers = [
        f"tree {commit.tree_id}".encode("ascii"),
        *(f"parent {parent_id}".encode("ascii") for parent_id in commit.parent_ids),
        b"author " + _identity_bytes(commit.author, "author"),
        b"committer " + _identity_bytes(commit.committer, "committer"),
    ]
    return b"\n".join(headers) + b"\n\n" + commit.message


def _parse_identity(value: bytes, field: str) -> CommitIdentity:
    match = _IDENTITY_PATTERN.fullmatch(value)
    if match is None:
        raise CommitError(f"malformed {field} identity header")
    name_bytes, email_bytes, timestamp_bytes, sign, hour_bytes, minute_bytes = (
        match.groups()
    )
    try:
        name = name_bytes.decode("utf-8")
        email = email_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CommitError(f"{field} identity must be UTF-8") from error
    hours = int(hour_bytes)
    minutes = int(minute_bytes)
    if hours > 23 or minutes > 59:
        raise CommitError(f"malformed {field} timezone offset")
    offset = hours * 60 + minutes
    if sign == b"-":
        offset = -offset
    try:
        identity = CommitIdentity(
            name=name,
            email=email,
            timestamp=int(timestamp_bytes),
            timezone_offset=offset,
        )
    except ValueError as error:
        raise CommitError(f"malformed {field} timestamp") from error
    _identity_bytes(identity, field)
    return identity


def parse_commit(payload: bytes) -> Commit:
    """Parse a commit payload with tree, ordered parents, author, and committer."""
    if not isinstance(payload, bytes):
        raise TypeError("commit payload must be bytes")
    header_bytes, separator, message = payload.partition(b"\n\n")
    if not separator:
        raise CommitError("commit payload is missing the blank-line header separator")
    lines = header_bytes.split(b"\n")
    if not lines or not lines[0].startswith(b"tree "):
        raise CommitError("commit payload must begin with a tree header")
    try:
        tree_id = lines[0][5:].decode("ascii")
    except UnicodeDecodeError as error:
        raise CommitError("tree object ID must be ASCII") from error
    _validate_object_id(tree_id, "tree object ID")

    index = 1
    parents: list[str] = []
    while index < len(lines) and lines[index].startswith(b"parent "):
        try:
            parent_id = lines[index][7:].decode("ascii")
        except UnicodeDecodeError as error:
            raise CommitError("parent object ID must be ASCII") from error
        _validate_object_id(parent_id, "parent object ID")
        parents.append(parent_id)
        index += 1

    if index + 2 != len(lines) or not lines[index].startswith(b"author "):
        raise CommitError("commit payload must contain author and committer headers")
    author = _parse_identity(lines[index][7:], "author")
    committer_line = lines[index + 1]
    if not committer_line.startswith(b"committer "):
        raise CommitError("commit payload must contain a committer header after author")
    committer = _parse_identity(committer_line[10:], "committer")
    return Commit(tree_id, tuple(parents), author, committer, message)


def _validate_referenced_objects(objects_dir: Path, commit: Commit) -> None:
    tree_type, _ = read_object(objects_dir, commit.tree_id)
    if tree_type != "tree":
        raise CommitError(f"commit tree {commit.tree_id} is {tree_type}, not a tree")
    for parent_id in commit.parent_ids:
        parent_type, _ = read_object(objects_dir, parent_id)
        if parent_type != "commit":
            raise CommitError(
                f"commit parent {parent_id} is {parent_type}, not a commit"
            )


def write_commit(objects_dir: Path, commit: Commit) -> str:
    """Validate referenced object types, then store a serialized commit."""
    _validate_referenced_objects(objects_dir, commit)
    return write_object(objects_dir, "commit", serialize_commit(commit))


def read_commit(objects_dir: Path, object_id: str) -> Commit:
    """Read, parse, and validate a commit and its direct object references."""
    object_type, payload = read_object(objects_dir, object_id)
    if object_type != "commit":
        raise CommitError(f"object {object_id} is {object_type}, not a commit")
    commit = parse_commit(payload)
    _validate_referenced_objects(objects_dir, commit)
    return commit
