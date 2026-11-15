"""Bounded read-only browsing of Core-backed bare repositories."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import os
from pathlib import Path
import stat

from commitverse_core.commits import Commit, parse_commit
from commitverse_core.objects.store import read_object_bounded
from commitverse_core.refs import (
    ReferenceError,
    ReferenceNotFoundError,
    branch_ref_name,
    current_branch,
    list_branches,
    read_ref,
    resolve_head,
    validate_ref_name,
)
from commitverse_core.repository import Repository as CoreRepository
from commitverse_core.repository import RepositoryError as CoreRepositoryError
from commitverse_core.repository import discover_repository
from commitverse_core.trees import TreeEntry, parse_tree

MAX_TREE_OBJECT_BYTES = 4 * 1024 * 1024
MAX_COMMIT_OBJECT_BYTES = 4 * 1024 * 1024
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_TREE_ENTRIES = 1000
MAX_HISTORY_COMMITS = 100
MAX_DIFF_FILES = 200
MAX_DIFF_BYTES = 8 * 1024 * 1024
MAX_PATCH_BYTES = 512 * 1024


class BrowseError(Exception):
    """Raised when a Core repository cannot be browsed safely."""


class BrowseNotFoundError(BrowseError):
    """Raised when a requested path or commit does not exist."""


class BrowseLimitError(BrowseError):
    """Raised when a repository object exceeds a browsing limit."""


@dataclass(frozen=True)
class BrowseTreeEntry:
    name: str
    entry_type: str
    mode: str
    object_id: str


@dataclass(frozen=True)
class BrowseTree:
    commit_id: str | None
    path: str
    entries: tuple[BrowseTreeEntry, ...]


@dataclass(frozen=True)
class BrowseBlob:
    commit_id: str
    path: str
    object_id: str
    size: int
    is_binary: bool
    content: str | None


@dataclass(frozen=True)
class BrowseCommit:
    object_id: str
    parent_ids: tuple[str, ...]
    author_name: str
    author_email: str
    author_timestamp: int
    message: str


@dataclass(frozen=True)
class BrowseCommitDetail:
    object_id: str
    tree_id: str
    parent_ids: tuple[str, ...]
    author_name: str
    author_email: str
    author_timestamp: int
    author_timezone_offset: int
    committer_name: str
    committer_email: str
    committer_timestamp: int
    committer_timezone_offset: int
    message: str


@dataclass(frozen=True)
class BrowseDiffFile:
    path: str
    status: str
    old_object_id: str | None
    new_object_id: str | None
    is_binary: bool
    patch: str | None


@dataclass(frozen=True)
class BrowseDiff:
    base_commit_id: str | None
    head_commit_id: str
    files: tuple[BrowseDiffFile, ...]


@dataclass(frozen=True)
class BrowseRef:
    name: str
    ref: str
    object_id: str | None
    kind: str
    current: bool


def browse_refs(repository_path: Path) -> tuple[BrowseRef, ...]:
    """List safe local branches and direct-commit tags for a bare repository."""
    repository = _repository(repository_path)
    try:
        head = current_branch(repository)
        branches = tuple(
            BrowseRef(branch.name, f"refs/heads/{branch.name}", branch.object_id, "branch", branch.name == head)
            for branch in list_branches(repository)
        )
        tags = tuple(
            BrowseRef(name, f"refs/tags/{name}", object_id, "tag", False)
            for name, object_id in _list_tags(repository)
        )
    except (OSError, ReferenceError, RuntimeError, ValueError) as exc:
        raise BrowseError("The repository references could not be read.") from exc
    return tuple(sorted((*branches, *tags), key=lambda item: (item.kind, item.name.encode("utf-8"))))


def browse_tree(repository_path: Path, path: str = "", ref: str = "HEAD") -> BrowseTree:
    """List one committed tree directory from a selected local ref."""
    repository, commit_id, commit = _ref_commit(repository_path, ref)
    normalized_path, components = _normalize_path(path)
    if commit is None or commit_id is None:
        if components:
            raise BrowseNotFoundError("Repository has no committed files.")
        return BrowseTree(None, normalized_path, ())
    tree_id = _tree_for_components(repository, commit.tree_id, components)
    entries = _read_tree(repository, tree_id)
    return BrowseTree(
        commit_id,
        normalized_path,
        tuple(
            BrowseTreeEntry(
                name=_display_name(entry.name),
                entry_type="tree" if entry.mode == "40000" else "blob",
                mode=entry.mode,
                object_id=entry.object_id,
            )
            for entry in entries
        ),
    )


def browse_blob(repository_path: Path, path: str, ref: str = "HEAD") -> BrowseBlob:
    """Read one bounded committed blob from a selected local ref."""
    repository, commit_id, commit = _ref_commit(repository_path, ref)
    normalized_path, components = _normalize_path(path)
    if commit is None or commit_id is None or not components:
        raise BrowseNotFoundError("File not found.")
    tree_id, entry = _resolve_entry(repository, commit.tree_id, components)
    del tree_id
    if entry.mode == "40000":
        raise BrowseNotFoundError("Requested path is a directory.")
    try:
        object_type, payload, _ = read_object_bounded(
            repository.objects_dir,
            entry.object_id,
            max_compressed_size=MAX_BLOB_BYTES,
            max_decompressed_size=MAX_BLOB_BYTES,
        )
    except ValueError as exc:
        raise BrowseError("The stored file object is malformed.") from exc
    if object_type != "blob":
        raise BrowseError("The requested tree entry is not a blob.")
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError:
        content = None
    return BrowseBlob(
        commit_id,
        normalized_path,
        entry.object_id,
        len(payload),
        content is None,
        content,
    )


def browse_history(repository_path: Path, limit: int = 50, ref: str = "HEAD") -> tuple[BrowseCommit, ...]:
    """Return a bounded history from a selected local ref."""
    if limit < 1 or limit > MAX_HISTORY_COMMITS:
        raise BrowseLimitError("History limit is outside the supported range.")
    repository, commit_id, _ = _ref_commit(repository_path, ref)
    if commit_id is None:
        return ()
    commits: list[BrowseCommit] = []
    pending = [commit_id]
    visited: set[str] = set()
    while pending and len(commits) < limit:
        object_id = pending.pop(0)
        if object_id in visited:
            continue
        visited.add(object_id)
        commit = _read_commit(repository, object_id)
        commits.append(
            BrowseCommit(
                object_id=object_id,
                parent_ids=commit.parent_ids,
                author_name=commit.author.name,
                author_email=commit.author.email,
                author_timestamp=commit.author.timestamp,
                message=_message_summary(commit.message),
            )
        )
        pending.extend(commit.parent_ids)
    return tuple(commits)


def browse_commit(
    repository_path: Path, object_id: str, ref: str = "HEAD"
) -> BrowseCommitDetail:
    """Return a bounded commit detail only when reachable from the selected ref."""
    repository, commit_id, _ = _ref_commit(repository_path, ref)
    if commit_id is None:
        raise BrowseNotFoundError("The selected repository ref has no commit.")
    commit = _reachable_commit(repository, commit_id, object_id)
    if commit is not None:
        return BrowseCommitDetail(
                object_id=object_id,
                tree_id=commit.tree_id,
                parent_ids=commit.parent_ids,
                author_name=commit.author.name,
                author_email=commit.author.email,
                author_timestamp=commit.author.timestamp,
                author_timezone_offset=commit.author.timezone_offset,
                committer_name=commit.committer.name,
                committer_email=commit.committer.email,
                committer_timestamp=commit.committer.timestamp,
                committer_timezone_offset=commit.committer.timezone_offset,
                message=commit.message.decode("utf-8", errors="replace"),
        )
    raise BrowseNotFoundError("Commit is not reachable from the selected ref.")


def browse_diff(
    repository_path: Path, object_id: str, ref: str = "HEAD"
) -> BrowseDiff:
    """Compare a reachable commit with its first parent using bounded objects."""
    repository, ref_commit_id, _ = _ref_commit(repository_path, ref)
    if ref_commit_id is None:
        raise BrowseNotFoundError("The selected repository ref has no commit.")
    head = _reachable_commit(repository, ref_commit_id, object_id)
    if head is None:
        raise BrowseNotFoundError("Commit is not reachable from the selected ref.")
    base_id = head.parent_ids[0] if head.parent_ids else None
    base = _read_commit(repository, base_id) if base_id else None
    old_files = _snapshot_tree(repository, base.tree_id) if base else {}
    new_files = _snapshot_tree(repository, head.tree_id)
    paths = sorted(set(old_files) | set(new_files), key=lambda value: value.encode("utf-8"))
    if len(paths) > MAX_DIFF_FILES:
        raise BrowseLimitError("The commit changes too many files to browse.")
    files: list[BrowseDiffFile] = []
    for path in paths:
        old = old_files.get(path)
        new = new_files.get(path)
        if old is not None and new is not None and old[0] == new[0] and old[1] == new[1]:
            continue
        old_payload = old[2] if old else None
        new_payload = new[2] if new else None
        is_binary = _is_binary(old_payload) or _is_binary(new_payload)
        patch = None if is_binary else _unified_patch(path, old_payload or b"", new_payload or b"")
        if patch is not None and len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
            raise BrowseLimitError("The rendered commit diff is too large.")
        files.append(
            BrowseDiffFile(
                path=path,
                status="added" if old is None else "deleted" if new is None else "modified",
                old_object_id=old[0] if old else None,
                new_object_id=new[0] if new else None,
                is_binary=is_binary,
                patch=patch,
            )
        )
    return BrowseDiff(base_id, object_id, tuple(files))


def _head_commit(
    repository_path: Path,
) -> tuple[CoreRepository, str | None, Commit | None]:
    try:
        repository = _repository(repository_path)
        if not repository.bare or repository.git_dir != repository_path.resolve():
            raise BrowseError("Stored repository is not the requested bare repository.")
        commit_id = resolve_head(repository)
    except BrowseError:
        raise
    except (CoreRepositoryError, OSError, RuntimeError, ValueError) as exc:
        raise BrowseError("The repository history could not be read.") from exc
    if commit_id is None:
        return repository, None, None
    return repository, commit_id, _read_commit(repository, commit_id)


def _repository(repository_path: Path) -> CoreRepository:
    repository = discover_repository(repository_path)
    if not repository.bare or repository.git_dir != repository_path.resolve():
        raise BrowseError("Stored repository is not the requested bare repository.")
    return repository


def _ref_commit(
    repository_path: Path, ref: str
) -> tuple[CoreRepository, str | None, Commit | None]:
    try:
        repository = _repository(repository_path)
        if ref == "HEAD":
            commit_id = resolve_head(repository)
        else:
            ref_name = _safe_browse_ref(ref)
            commit_id = read_ref(repository, ref_name)
            _read_commit(repository, commit_id)
    except BrowseError:
        raise
    except ReferenceNotFoundError as exc:
        raise BrowseNotFoundError("The selected repository ref was not found.") from exc
    except (CoreRepositoryError, OSError, ReferenceError, RuntimeError, ValueError) as exc:
        raise BrowseError("The selected repository ref could not be read.") from exc
    if commit_id is None:
        return repository, None, None
    return repository, commit_id, _read_commit(repository, commit_id)


def _safe_browse_ref(ref: str) -> str:
    if not isinstance(ref, str) or ref == "HEAD":
        raise BrowseNotFoundError("The selected repository ref is invalid.")
    if ref.startswith("refs/heads/"):
        ref_name = ref
    elif ref.startswith("refs/tags/"):
        ref_name = ref
    elif "/" not in ref:
        ref_name = branch_ref_name(ref)
    else:
        raise BrowseNotFoundError("Only local branches and tags can be browsed.")
    try:
        return validate_ref_name(ref_name)
    except ReferenceError as exc:
        raise BrowseNotFoundError("The selected repository ref is invalid.") from exc


def _list_tags(repository: CoreRepository) -> tuple[tuple[str, str], ...]:
    root = repository.git_dir / "refs" / "tags"
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ReferenceError("unsafe tag directory")
    found: list[tuple[str, str]] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in tuple(directory_names):
            child = current / name
            if child.is_symlink():
                raise ReferenceError(f"unsafe tag directory: {child}")
        for name in file_names:
            if name.endswith(".lock"):
                continue
            path = current / name
            ref_name = path.relative_to(repository.git_dir).as_posix()
            validate_ref_name(ref_name)
            object_id = read_ref(repository, ref_name)
            _read_commit(repository, object_id)
            found.append((ref_name.removeprefix("refs/tags/"), object_id))
    return tuple(sorted(found, key=lambda item: item[0].encode("utf-8")))


def _read_commit(repository: CoreRepository, object_id: str) -> Commit:
    try:
        object_type, payload, _ = read_object_bounded(
            repository.objects_dir,
            object_id,
            max_compressed_size=MAX_COMMIT_OBJECT_BYTES,
            max_decompressed_size=MAX_COMMIT_OBJECT_BYTES,
        )
        if object_type != "commit":
            raise BrowseError("The history references a non-commit object.")
        return parse_commit(payload)
    except BrowseError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BrowseError("The repository history contains a malformed commit.") from exc


def _reachable_commit(
    repository: CoreRepository, start_id: str, target_id: str
) -> Commit | None:
    pending = [start_id]
    visited: set[str] = set()
    while pending and len(visited) < MAX_HISTORY_COMMITS:
        candidate = pending.pop(0)
        if candidate in visited:
            continue
        visited.add(candidate)
        commit = _read_commit(repository, candidate)
        if candidate == target_id:
            return commit
        pending.extend(commit.parent_ids)
    return None


def _snapshot_tree(
    repository: CoreRepository, tree_id: str
) -> dict[str, tuple[str, str, bytes]]:
    files: dict[str, tuple[str, str, bytes]] = {}
    total_bytes = 0

    def visit(current_tree_id: str, prefix: str) -> None:
        nonlocal total_bytes
        for entry in _read_tree(repository, current_tree_id):
            name = _display_name(entry.name)
            path = f"{prefix}/{name}" if prefix else name
            if entry.mode == "40000":
                visit(entry.object_id, path)
                continue
            try:
                object_type, payload, _ = read_object_bounded(
                    repository.objects_dir,
                    entry.object_id,
                    max_compressed_size=MAX_BLOB_BYTES,
                    max_decompressed_size=MAX_BLOB_BYTES,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise BrowseError("The commit diff references malformed file data.") from exc
            if object_type != "blob":
                raise BrowseError("The commit diff references a non-blob file object.")
            total_bytes += len(payload)
            if total_bytes > MAX_DIFF_BYTES:
                raise BrowseLimitError("The commit trees are too large to diff.")
            files[path] = (entry.object_id, entry.mode, payload)
            if len(files) > MAX_DIFF_FILES:
                raise BrowseLimitError("The commit changes too many files to browse.")

    visit(tree_id, "")
    return files


def _is_binary(payload: bytes | None) -> bool:
    if payload is None:
        return False
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return b"\0" in payload


def _unified_patch(path: str, old_payload: bytes, new_payload: bytes) -> str:
    old_text = old_payload.decode("utf-8", errors="replace").splitlines(keepends=True)
    new_text = new_payload.decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_text,
            new_text,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _read_tree(repository: CoreRepository, tree_id: str) -> tuple[TreeEntry, ...]:
    try:
        object_type, payload, _ = read_object_bounded(
            repository.objects_dir,
            tree_id,
            max_compressed_size=MAX_TREE_OBJECT_BYTES,
            max_decompressed_size=MAX_TREE_OBJECT_BYTES,
        )
        if object_type != "tree":
            raise BrowseError("The repository references a non-tree object.")
        entries = parse_tree(payload)
    except BrowseError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BrowseError("The repository tree contains malformed data.") from exc
    if len(entries) > MAX_TREE_ENTRIES:
        raise BrowseLimitError("The requested directory contains too many entries.")
    return entries


def _tree_for_components(
    repository: CoreRepository,
    tree_id: str,
    components: tuple[bytes, ...],
) -> str:
    current_tree = tree_id
    for component in components:
        entries = _read_tree(repository, current_tree)
        entry = next((item for item in entries if item.name == component), None)
        if entry is None or entry.mode != "40000":
            raise BrowseNotFoundError("Directory not found.")
        current_tree = entry.object_id
    return current_tree


def _resolve_entry(
    repository: CoreRepository,
    tree_id: str,
    components: tuple[bytes, ...],
) -> tuple[str, TreeEntry]:
    if not components:
        raise BrowseNotFoundError("File not found.")
    current_tree = tree_id
    for component in components[:-1]:
        entries = _read_tree(repository, current_tree)
        entry = next((item for item in entries if item.name == component), None)
        if entry is None or entry.mode != "40000":
            raise BrowseNotFoundError("File not found.")
        current_tree = entry.object_id
    entries = _read_tree(repository, current_tree)
    entry = next((item for item in entries if item.name == components[-1]), None)
    if entry is None:
        raise BrowseNotFoundError("File not found.")
    return current_tree, entry


def _normalize_path(path: str) -> tuple[str, tuple[bytes, ...]]:
    if not isinstance(path, str) or "\\" in path or path.startswith("/"):
        raise BrowseNotFoundError("Repository paths must be relative POSIX paths.")
    if len(path.encode("utf-8")) > MAX_PATH_BYTES:
        raise BrowseLimitError("Repository path is too long.")
    if path in {"", "."}:
        return "", ()
    raw_components = path.split("/")
    if any(component in {"", ".", ".."} for component in raw_components):
        raise BrowseNotFoundError("Repository path is invalid.")
    components = tuple(component.encode("utf-8") for component in raw_components)
    return "/".join(raw_components), components


def _display_name(name: bytes) -> str:
    return name.decode("utf-8", errors="replace")


def _message_summary(message: bytes) -> str:
    return message.decode("utf-8", errors="replace").splitlines()[0][:500] if message else ""
