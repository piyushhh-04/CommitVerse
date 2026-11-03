"""Basic safe three-way merges."""

import difflib
import os
from datetime import datetime
from dataclasses import dataclass

from commitverse_core.checkout import _tree_files, checkout_commit
from commitverse_core.commit_service import resolve_identities
from commitverse_core.commits import Commit, read_commit, write_commit
from commitverse_core.merge_base import MergeBaseError, find_merge_base, is_ancestor
from commitverse_core.objects.store import read_object, write_object
from commitverse_core.refs import read_head, resolve_branch, resolve_head
from commitverse_core.repository import Repository
from commitverse_core.status import StatusError, collect_snapshot
from commitverse_core.index import write_index


class MergeError(ValueError):
    """Raised when a merge cannot be completed safely."""


@dataclass(frozen=True)
class Conflict:
    path: bytes
    kind: str


def _files(repository: Repository, commit_id: str) -> dict[bytes, tuple[str, str, bytes]]:
    result: dict[bytes, tuple[str, str, bytes]] = {}
    for path, (mode, object_id) in _tree_files(repository, read_commit(repository.objects_dir, commit_id).tree_id).items():
        object_type, payload = read_object(repository.objects_dir, object_id)
        if object_type != "blob":
            raise MergeError(f"tree path {path!r} does not reference a blob")
        result[path] = (mode, object_id, payload)
    return result


def _combine_text(base: bytes, left: bytes, right: bytes) -> bytes | None:
    if left == right:
        return left
    if left == base:
        return right
    if right == base:
        return left
    if b"\0" in base + left + right:
        return None
    base_lines = base.splitlines(keepends=True)
    left_lines = left.splitlines(keepends=True)
    right_lines = right.splitlines(keepends=True)
    left_changes = difflib.SequenceMatcher(None, base_lines, left_lines).get_opcodes()
    right_changes = difflib.SequenceMatcher(None, base_lines, right_lines).get_opcodes()
    edits: list[tuple[int, int, list[bytes]]] = []
    for tag, start, end, replacement_start, replacement_end in left_changes:
        if tag != "equal":
            edits.append((start, end, left_lines[replacement_start:replacement_end]))
    for tag, start, end, replacement_start, replacement_end in right_changes:
        if tag != "equal":
            candidate = (start, end, right_lines[replacement_start:replacement_end])
            for existing in edits:
                overlaps = not (
                    candidate[1] <= existing[0] or existing[1] <= candidate[0]
                )
                if overlaps and candidate[2] != existing[2]:
                    return None
            if candidate not in edits:
                edits.append(candidate)
    edits.sort(key=lambda value: value[0])
    output = list(base_lines)
    for start, end, replacement in reversed(edits):
        output[start:end] = replacement
    return b"".join(output)


def merge_branch(repository: Repository, branch_name: str) -> tuple[str, str]:
    current = resolve_head(repository)
    if current is None:
        raise MergeError("cannot merge into an unborn branch")
    other = resolve_branch(repository, branch_name)
    try:
        snapshot = collect_snapshot(repository)
    except (OSError, StatusError, ValueError) as error:
        raise MergeError(f"cannot inspect worktree: {error}") from error
    if snapshot.head != snapshot.index or snapshot.index != snapshot.working_tree or snapshot.untracked:
        raise MergeError("local changes or untracked files prevent merge")
    if is_ancestor(repository, other, current):
        return "already-up-to-date", current
    if is_ancestor(repository, current, other):
        checkout_commit(
            repository, other, head=read_head(repository), advance_symbolic=True
        )
        return "fast-forward", other
    base = find_merge_base(repository, current, other)
    if base is None:
        raise MergeError("branches have unrelated histories")
    base_files = _files(repository, base)
    left_files = _files(repository, current)
    right_files = _files(repository, other)
    merged: dict[bytes, tuple[str, str]] = {}
    conflicts: list[Conflict] = []
    for path in sorted(set(base_files) | set(left_files) | set(right_files)):
        base_value = base_files.get(path)
        left_value = left_files.get(path)
        right_value = right_files.get(path)
        if left_value == right_value:
            chosen = left_value
        elif left_value == base_value:
            chosen = right_value
        elif right_value == base_value:
            chosen = left_value
        elif left_value is None or right_value is None:
            conflicts.append(Conflict(path, "modify/delete"))
            continue
        elif base_value is None:
            conflicts.append(Conflict(path, "add/add"))
            continue
        elif left_value[0] != right_value[0]:
            conflicts.append(Conflict(path, "mode"))
            continue
        else:
            payload = _combine_text(base_value[2] if base_value else b"", left_value[2], right_value[2])
            if payload is None:
                conflicts.append(Conflict(path, "content"))
                continue
            chosen = (left_value[0], write_object(repository.objects_dir, "blob", payload), payload)
        if chosen is not None:
            merged[path] = (chosen[0], chosen[1])
    if conflicts:
        details = ", ".join(
            f"{conflict.path!r} ({conflict.kind})" for conflict in conflicts
        )
        raise MergeError(f"merge conflicts: {details}")

    tree_id = _tree_from_files(repository, merged)
    current_commit = read_commit(repository.objects_dir, current)
    other_commit = read_commit(repository.objects_dir, other)
    author, committer = resolve_identities(
        repository, environment=dict(os.environ), now=datetime.now().astimezone()
    )
    commit = Commit(
        tree_id,
        (current, other),
        author,
        committer,
        f"Merge branch '{branch_name}'\n".encode(),
    )
    merge_id = write_commit(repository.objects_dir, commit)
    checkout_commit(
        repository, merge_id, head=read_head(repository), advance_symbolic=True
    )
    return "merged", merge_id


def _tree_from_files(repository: Repository, files: dict[bytes, tuple[str, str]]) -> str:
    from commitverse_core.index import IndexEntry, IndexStat
    from commitverse_core.trees import write_tree

    return write_tree(
        repository.objects_dir,
        [
            IndexEntry(path, object_id, IndexStat(mode=int(mode, 8)))
            for path, (mode, object_id) in files.items()
        ],
    )
