"""Compare committed, staged, and working-tree repository snapshots."""

import errno
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from commitverse_core.commits import read_commit
from commitverse_core.index import read_index
from commitverse_core.objects.format import hash_object
from commitverse_core.objects.store import read_object
from commitverse_core.refs import current_branch, resolve_head
from commitverse_core.repository import Repository
from commitverse_core.staging import _is_ignored, _parse_ignore_rules
from commitverse_core.trees import read_tree


class StatusError(ValueError):
    """Raised when repository state cannot be compared safely."""


@dataclass(frozen=True)
class FileState:
    """A tracked file's Git mode and blob object ID."""

    mode: str
    object_id: str


@dataclass(frozen=True)
class Change:
    """One path changed between two repository states."""

    path: bytes
    kind: str


@dataclass(frozen=True)
class StatusSnapshot:
    """Validated snapshots used by status and diff without writing repository data."""

    head: dict[bytes, FileState]
    index: dict[bytes, FileState]
    working_tree: dict[bytes, FileState]
    working_payloads: dict[bytes, bytes]
    untracked: tuple[bytes, ...]
    branch_name: str | None
    head_id: str | None

    @property
    def unborn(self) -> bool:
        return self.head_id is None and self.branch_name is not None


@dataclass(frozen=True)
class RepositoryStatus:
    """Staged, unstaged, and untracked path classifications."""

    branch_name: str | None
    head_id: str | None
    staged: tuple[Change, ...]
    unstaged: tuple[Change, ...]
    untracked: tuple[bytes, ...]

    @property
    def clean(self) -> bool:
        return not self.staged and not self.unstaged and not self.untracked

    @property
    def unborn(self) -> bool:
        return self.head_id is None and self.branch_name is not None


def _signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_mode,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _path_text(path: bytes) -> str:
    text = os.fsdecode(path)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        return repr(text)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8")
    return text


def _missing_path(error: OSError) -> bool:
    return isinstance(error, FileNotFoundError) or error.errno == errno.ENOENT


def _validate_worktree_path(path: bytes) -> None:
    if b".git" in path.split(b"/"):
        raise StatusError(
            "tracked path enters the repository's .git directory: "
            f"{_path_text(path)!r}"
        )


def _read_worktree_file(
    root: Path, relative_path: bytes
) -> tuple[FileState, bytes] | None:
    parts = relative_path.split(b"/")
    if not relative_path or any(part in (b"", b".", b"..") for part in parts):
        raise StatusError(f"invalid repository-relative path: {relative_path!r}")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory_flag or os.open not in os.supports_dir_fd:
        raise StatusError("safe descriptor-relative worktree reads are unsupported")

    try:
        directory_fd = os.open(
            os.fsencode(root),
            os.O_RDONLY | directory_flag | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as error:
        raise StatusError(f"cannot open repository worktree {root}: {error}") from error

    path_label = _path_text(relative_path)
    try:
        for component in parts[:-1]:
            try:
                child_fd = os.open(
                    component,
                    os.O_RDONLY | directory_flag | nofollow | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
            except OSError as error:
                if _missing_path(error):
                    return None
                raise StatusError(
                    f"cannot safely access tracked path {path_label!r}: {error}"
                ) from error
            os.close(directory_fd)
            directory_fd = child_fd

        leaf = parts[-1]
        try:
            initial = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as error:
            if _missing_path(error):
                return None
            raise StatusError(
                f"cannot inspect tracked path {path_label!r}: {error}"
            ) from error

        if stat.S_ISLNK(initial.st_mode):
            try:
                payload = os.readlink(leaf, dir_fd=directory_fd)
                final = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise StatusError(
                    f"cannot safely read symbolic link {path_label!r}: {error}"
                ) from error
            if _signature(initial) != _signature(final):
                raise StatusError(f"tracked path changed while being read: {path_label!r}")
            mode = "120000"
        elif stat.S_ISREG(initial.st_mode):
            try:
                file_fd = os.open(
                    leaf,
                    os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
            except OSError as error:
                raise StatusError(
                    f"cannot safely open tracked path {path_label!r}: {error}"
                ) from error
            try:
                before = os.fstat(file_fd)
                if _signature(initial) != _signature(before):
                    raise StatusError(
                        f"tracked path changed while being opened: {path_label!r}"
                    )
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(file_fd)
                try:
                    final = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
                except OSError as error:
                    raise StatusError(
                        f"tracked path changed while being read: {path_label!r}"
                    ) from error
                if (
                    _signature(before) != _signature(after)
                    or _signature(after) != _signature(final)
                ):
                    raise StatusError(
                        f"tracked path changed while being read: {path_label!r}"
                    )
                payload = b"".join(chunks)
            finally:
                os.close(file_fd)
            mode = "100755" if initial.st_mode & 0o111 else "100644"
        else:
            raise StatusError(
                f"tracked path is not a regular file or symbolic link: {path_label!r}"
            )
    finally:
        os.close(directory_fd)

    return FileState(mode, hash_object("blob", payload)), payload


def _head_snapshot(repository: Repository) -> tuple[dict[bytes, FileState], str | None]:
    object_id = resolve_head(repository)
    if object_id is None:
        return {}, None
    commit = read_commit(repository.objects_dir, object_id)
    files: dict[bytes, FileState] = {}
    active_trees: set[str] = set()

    def visit(tree_id: str, prefix: bytes) -> None:
        if tree_id in active_trees:
            raise StatusError(f"cyclic tree structure at object {tree_id}")
        active_trees.add(tree_id)
        try:
            entries = read_tree(repository.objects_dir, tree_id)
            for entry in entries:
                path = prefix + entry.name
                if entry.mode == "40000":
                    visit(entry.object_id, path + b"/")
                else:
                    _validate_worktree_path(path)
                    if path in files:
                        raise StatusError(f"duplicate tree path: {_path_text(path)!r}")
                    files[path] = FileState(entry.mode, entry.object_id)
        finally:
            active_trees.remove(tree_id)

    visit(commit.tree_id, b"")
    return files, object_id


def _index_snapshot(repository: Repository) -> dict[bytes, FileState]:
    index = read_index(repository.git_dir / "index")
    files: dict[bytes, FileState] = {}
    for entry in index.entries:
        _validate_worktree_path(entry.path)
        if entry.stage != 0:
            raise StatusError(
                f"unmerged index entries are unsupported: {_path_text(entry.path)!r}"
            )
        object_type, _ = read_object(repository.objects_dir, entry.object_id)
        if object_type != "blob":
            raise StatusError(
                f"index path {_path_text(entry.path)!r} references "
                f"{object_type}, not a blob"
            )
        files[entry.path] = FileState(entry.mode, entry.object_id)
    return files


def _has_nested_git_directory(directory_fd: int) -> bool:
    try:
        os.stat(b".git", dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise StatusError(f"cannot inspect nested repository metadata: {error}") from error
    return True


def _untracked_paths(
    repository: Repository,
    tracked_paths: set[bytes],
    ignore_rules: tuple[tuple[bytes, bool, bool, bool], ...],
) -> tuple[bytes, ...]:
    root = repository.root.resolve(strict=True)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not directory_flag or not nofollow or os.open not in os.supports_dir_fd:
        raise StatusError("safe descriptor-relative worktree traversal is unsupported")
    try:
        root_fd = os.open(
            os.fsencode(root),
            os.O_RDONLY | directory_flag | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as error:
        raise StatusError(f"cannot open repository worktree {root}: {error}") from error

    found: list[bytes] = []
    may_prune_ignored_directories = not any(rule[1] for rule in ignore_rules)

    def visit(directory_fd: int, prefix: bytes) -> None:
        try:
            iterator_fd = os.dup(directory_fd)
            with os.scandir(iterator_fd) as entries:
                for entry in entries:
                    name = os.fsencode(entry.name)
                    if name == b".git":
                        continue
                    path = name if not prefix else prefix + b"/" + name
                    try:
                        before = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        raise StatusError(
                            f"cannot inspect worktree path {_path_text(path)!r}: {error}"
                        ) from error

                    if stat.S_ISDIR(before.st_mode):
                        try:
                            child_fd = os.open(
                                name,
                                os.O_RDONLY
                                | directory_flag
                                | nofollow
                                | getattr(os, "O_CLOEXEC", 0),
                                dir_fd=directory_fd,
                            )
                        except OSError as error:
                            raise StatusError(
                                f"cannot safely traverse worktree path "
                                f"{_path_text(path)!r}: {error}"
                            ) from error
                        try:
                            after = os.stat(
                                name, dir_fd=directory_fd, follow_symlinks=False
                            )
                            if _signature(before) != _signature(after):
                                raise StatusError(
                                    f"worktree path changed while being inspected: "
                                    f"{_path_text(path)!r}"
                                )
                            is_ignored_directory = (
                                may_prune_ignored_directories
                                and _is_ignored(path, True, ignore_rules)
                            )
                            if (
                                not _has_nested_git_directory(child_fd)
                                and not is_ignored_directory
                            ):
                                visit(child_fd, path)
                        finally:
                            os.close(child_fd)
                    elif stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
                        try:
                            after = os.stat(
                                name, dir_fd=directory_fd, follow_symlinks=False
                            )
                        except OSError as error:
                            raise StatusError(
                                f"worktree path changed while being inspected: "
                                f"{_path_text(path)!r}"
                            ) from error
                        if _signature(before) != _signature(after):
                            raise StatusError(
                                f"worktree path changed while being inspected: "
                                f"{_path_text(path)!r}"
                            )
                        is_directory = stat.S_ISDIR(before.st_mode)
                        if (
                            path not in tracked_paths
                            and not _is_ignored(path, is_directory, ignore_rules)
                        ):
                            found.append(path)
        except OSError as error:
            raise StatusError(f"cannot scan worktree: {error}") from error

    try:
        visit(root_fd, b"")
    finally:
        os.close(root_fd)
    return tuple(sorted(found))


def collect_snapshot(
    repository: Repository, *, include_untracked: bool = True
) -> StatusSnapshot:
    """Read HEAD, index, and tracked worktree states without writing objects."""
    repository.require_worktree()
    head, head_id = _head_snapshot(repository)
    index = _index_snapshot(repository)
    tracked_paths = set(head) | set(index)
    working_tree: dict[bytes, FileState] = {}
    working_payloads: dict[bytes, bytes] = {}
    root = repository.require_worktree().resolve(strict=True)

    for path in sorted(tracked_paths):
        result = _read_worktree_file(root, path)
        if result is not None:
            state, payload = result
            working_tree[path] = state
            working_payloads[path] = payload

    untracked: tuple[bytes, ...] = ()
    if include_untracked:
        if b".gitignore" in tracked_paths:
            ignore_state = working_tree.get(b".gitignore")
            ignore_payload = working_payloads.get(b".gitignore")
            if ignore_state is not None and ignore_state.mode == "120000":
                raise StatusError(
                    "the worktree-root .gitignore must be a regular file"
                )
        else:
            ignore_file = _read_worktree_file(root, b".gitignore")
            ignore_state = None if ignore_file is None else ignore_file[0]
            ignore_payload = None if ignore_file is None else ignore_file[1]

        if ignore_payload is None:
            rules = ()
        elif ignore_state is not None and ignore_state.mode == "120000":
            raise StatusError("the worktree-root .gitignore must be a regular file")
        else:
            rules = _parse_ignore_rules(ignore_payload)
        untracked = _untracked_paths(repository, tracked_paths, rules)

    return StatusSnapshot(
        head=head,
        index=index,
        working_tree=working_tree,
        working_payloads=working_payloads,
        untracked=untracked,
        branch_name=current_branch(repository),
        head_id=head_id,
    )


def _changes(
    before: dict[bytes, FileState], after: dict[bytes, FileState]
) -> tuple[Change, ...]:
    changes: list[Change] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if old is None:
            kind = "new file"
        elif new is None:
            kind = "deleted"
        else:
            kind = "modified"
        changes.append(Change(path, kind))
    return tuple(changes)


def get_status(repository: Repository) -> RepositoryStatus:
    """Return staged, unstaged, and untracked changes for a repository."""
    snapshot = collect_snapshot(repository)
    return RepositoryStatus(
        branch_name=snapshot.branch_name,
        head_id=snapshot.head_id,
        staged=_changes(snapshot.head, snapshot.index),
        unstaged=_changes(snapshot.index, snapshot.working_tree),
        untracked=snapshot.untracked,
    )


def display_path(path: bytes) -> str:
    """Format a filesystem-byte path safely for one-line CLI output."""
    text = os.fsdecode(path)
    if any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in text
    ):
        return json.dumps(text, ensure_ascii=True)
    return text
