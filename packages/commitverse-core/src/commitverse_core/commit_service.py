"""Coordinate index, commit objects, identity configuration, and HEAD updates."""

import configparser
import os
import re
from dataclasses import dataclass
from datetime import datetime

from commitverse_core.commits import (
    Commit,
    CommitIdentity,
    read_commit,
    write_commit,
)
from commitverse_core.index import read_index
from commitverse_core.refs import current_branch, resolve_head, update_head
from commitverse_core.repository import Repository
from commitverse_core.trees import write_tree

_DATE_PATTERN = re.compile(r"@?(-?(?:0|[1-9][0-9]*)) ([+-])([0-9]{2})([0-9]{2})\Z")


class CommitServiceError(ValueError):
    """Raised when a commit cannot be created from the current repository state."""


@dataclass(frozen=True)
class CommitResult:
    """Summary of a successful commit and the ref it advanced."""

    object_id: str
    tree_id: str
    parent_id: str | None
    branch_name: str | None
    path_count: int


def _configured_identity(repository: Repository) -> tuple[str, str]:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        config.read_string(
            (repository.git_dir / "config").read_text(encoding="utf-8")
        )
        name = config.get("user", "name", fallback="")
        email = config.get("user", "email", fallback="")
    except (OSError, UnicodeError, configparser.Error) as error:
        raise CommitServiceError(f"cannot read repository identity configuration: {error}") from error
    return name, email


def _identity_date(value: str, variable: str) -> tuple[int, int]:
    match = _DATE_PATTERN.fullmatch(value)
    if match is None:
        raise CommitServiceError(
            f"{variable} must use '@<unix-seconds> ±HHMM' format"
        )
    timestamp = int(match.group(1))
    hours, minutes = int(match.group(3)), int(match.group(4))
    if hours > 23 or minutes > 59:
        raise CommitServiceError(f"{variable} has an invalid timezone offset")
    offset = hours * 60 + minutes
    if match.group(2) == "-":
        offset = -offset
    return timestamp, offset


def _resolve_identity(
    role: str,
    configured: tuple[str, str],
    environment: dict[str, str],
    now: datetime,
) -> CommitIdentity:
    prefix = "GIT_AUTHOR" if role == "author" else "GIT_COMMITTER"
    name = environment.get(f"{prefix}_NAME") or configured[0]
    email = environment.get(f"{prefix}_EMAIL") or configured[1]
    if not name or not email:
        raise CommitServiceError(
            "commit identity is required; set user.name and user.email in "
            ".git/config or the corresponding GIT_AUTHOR/GIT_COMMITTER variables"
        )
    date_value = environment.get(f"{prefix}_DATE")
    if date_value:
        timestamp, offset = _identity_date(date_value, f"{prefix}_DATE")
    else:
        timestamp = int(now.timestamp())
        local_offset = now.utcoffset()
        offset = 0 if local_offset is None else int(local_offset.total_seconds() // 60)
    return CommitIdentity(name, email, timestamp, offset)


def create_commit(
    repository: Repository,
    message: str,
    *,
    environment: dict[str, str] | None = None,
    now: datetime | None = None,
) -> CommitResult:
    """Write a commit for the index and atomically advance current HEAD."""
    if not isinstance(message, str) or not message.strip():
        raise CommitServiceError("commit message must not be empty")
    message_bytes = message.encode("utf-8")
    if not message_bytes.endswith(b"\n"):
        message_bytes += b"\n"

    environment_values = dict(os.environ if environment is None else environment)
    configured = _configured_identity(repository)
    current_time = datetime.now().astimezone() if now is None else now
    author = _resolve_identity(
        "author", configured, environment_values, current_time
    )
    committer = _resolve_identity(
        "committer", configured, environment_values, current_time
    )

    index = read_index(repository.git_dir / "index")
    parent_id = resolve_head(repository)
    tree_id = write_tree(repository.objects_dir, index.entries)
    if parent_id is None and not index.entries:
        raise CommitServiceError(
            "nothing to commit; an empty initial commit is not supported"
        )
    if parent_id is not None:
        parent = read_commit(repository.objects_dir, parent_id)
        if parent.tree_id == tree_id:
            raise CommitServiceError("nothing to commit; the index matches HEAD")

    commit = Commit(
        tree_id=tree_id,
        parent_ids=() if parent_id is None else (parent_id,),
        author=author,
        committer=committer,
        message=message_bytes,
    )
    object_id = write_commit(repository.objects_dir, commit)
    update_head(repository, object_id)
    return CommitResult(
        object_id=object_id,
        tree_id=tree_id,
        parent_id=parent_id,
        branch_name=current_branch(repository),
        path_count=len(index.entries),
    )
