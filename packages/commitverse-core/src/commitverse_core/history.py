"""Traverse and format the supported portion of commit history."""

from datetime import datetime, timedelta, timezone
from typing import Iterator

from commitverse_core.commits import Commit, read_commit
from commitverse_core.refs import resolve_head
from commitverse_core.repository import Repository


class HistoryError(ValueError):
    """Raised for malformed, missing, or cyclic commit history."""


def walk_history(repository: Repository) -> Iterator[tuple[str, Commit]]:
    """Yield reachable commits depth-first, preserving parent order."""
    start = resolve_head(repository)
    if start is None:
        return

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[tuple[str, bool]] = [(start, False)]
    while stack:
        object_id, leaving = stack.pop()
        if leaving:
            visiting.remove(object_id)
            visited.add(object_id)
            continue
        if object_id in visiting:
            raise HistoryError(f"cyclic commit history at {object_id}")
        if object_id in visited:
            continue

        visiting.add(object_id)
        try:
            commit = read_commit(repository.objects_dir, object_id)
        except (OSError, ValueError) as error:
            raise HistoryError(f"cannot read commit {object_id}: {error}") from error
        yield object_id, commit
        stack.append((object_id, True))
        stack.extend((parent_id, False) for parent_id in reversed(commit.parent_ids))


def format_commit_date(commit: Commit) -> str:
    """Format the author timestamp using the offset recorded in the commit."""
    try:
        zone = timezone(timedelta(minutes=commit.author.timezone_offset))
        value = datetime.fromtimestamp(commit.author.timestamp, zone)
    except (OverflowError, OSError, ValueError) as error:
        raise HistoryError(
            f"commit author timestamp is outside the supported date range: "
            f"{commit.author.timestamp}"
        ) from error
    return value.strftime("%Y-%m-%d %H:%M:%S %z")


def format_commit_message(message: bytes) -> str:
    """Decode a message for terminal display while preserving its line layout."""
    return message.decode("utf-8", errors="replace")
