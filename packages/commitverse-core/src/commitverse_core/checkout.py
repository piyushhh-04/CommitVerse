"""Safe worktree, index, and HEAD transitions."""

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from commitverse_core.commits import read_commit
from commitverse_core.index import Index, IndexEntry, IndexStat, read_index, write_index
from commitverse_core.objects.store import read_object
from commitverse_core.refs import (
    Head,
    ReferenceError,
    read_head,
    resolve_head,
    set_head_detached,
    set_head_symbolic,
    update_head,
    write_ref,
)
from commitverse_core.repository import Repository
from commitverse_core.status import StatusError, collect_snapshot
from commitverse_core.trees import read_tree


class CheckoutError(ValueError):
    """Raised when a checkout would be unsafe or cannot be completed."""


@dataclass(frozen=True)
class _BackupEntry:
    path: bytes
    kind: str
    backup_path: Path | None
    mode: int
    link_target: str | None = None


def _ancestors(path: bytes) -> tuple[bytes, ...]:
    parts = path.split(b"/")
    return tuple(b"/".join(parts[:index]) for index in range(1, len(parts)))


def _transaction_paths(paths: set[bytes]) -> set[bytes]:
    result = set(paths)
    for path in paths:
        result.update(_ancestors(path))
    return {path for path in result if path}


def _ancestors_for_paths(paths: set[bytes]) -> set[bytes]:
    result: set[bytes] = set()
    for path in paths:
        result.update(_ancestors(path))
    return result


def _tree_files(repository: Repository, tree_id: str) -> dict[bytes, tuple[str, str]]:
    files: dict[bytes, tuple[str, str]] = {}
    active: set[str] = set()

    def visit(object_id: str, prefix: bytes) -> None:
        if object_id in active:
            raise CheckoutError(f"cyclic tree structure at object {object_id}")
        active.add(object_id)
        try:
            for entry in read_tree(repository.objects_dir, object_id):
                path = prefix + entry.name
                if entry.mode == "40000":
                    visit(entry.object_id, path + b"/")
                else:
                    if path in files:
                        raise CheckoutError(f"duplicate tree path: {path!r}")
                    files[path] = (entry.mode, entry.object_id)
        finally:
            active.remove(object_id)

    visit(tree_id, b"")
    return files


def _target_index(repository: Repository, files: dict[bytes, tuple[str, str]]) -> Index:
    entries: list[IndexEntry] = []
    for path, (mode, object_id) in sorted(files.items()):
        entries.append(
            IndexEntry(path, object_id, IndexStat(mode=int(mode, 8)))
        )
    return Index(tuple(entries))


def _safe_parent(root: Path, path: bytes) -> Path:
    current = root
    for component in path.split(b"/")[:-1]:
        current /= os.fsdecode(component)
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            current.mkdir()
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise CheckoutError(f"cannot create path through unsafe directory: {path!r}")
    return current


def _remove_path(root: Path, path: bytes) -> None:
    target = root / os.fsdecode(path)
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or stat.S_ISREG(metadata.st_mode):
        target.unlink()
    elif stat.S_ISDIR(metadata.st_mode):
        raise CheckoutError(f"cannot replace directory with tracked file: {path!r}")
    else:
        raise CheckoutError(f"unsupported worktree entry: {path!r}")


def _write_target(root: Path, path: bytes, mode: str, payload: bytes) -> None:
    parent = _safe_parent(root, path)
    target = parent / os.fsdecode(path.split(b"/")[-1])
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and stat.S_ISDIR(metadata.st_mode):
        raise CheckoutError(f"cannot replace directory with tracked file: {path!r}")
    if metadata is not None and stat.S_ISLNK(metadata.st_mode):
        target.unlink()
    if mode == "120000":
        try:
            os.symlink(os.fsdecode(payload), target)
        except OSError as error:
            raise CheckoutError(f"cannot create symbolic link {path!r}: {error}") from error
        return
    temporary = tempfile.NamedTemporaryFile(
        dir=parent, prefix=".cv-checkout-", delete=False
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, 0o755 if mode == "100755" else 0o644)
        os.replace(temporary_path, target)
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        raise CheckoutError(f"cannot write worktree path {path!r}: {error}") from error


def _backup_path(
    root: Path, path: bytes, backup_root: Path, sequence: int
) -> _BackupEntry | None:
    source = root / os.fsdecode(path)
    try:
        metadata = source.lstat()
    except FileNotFoundError:
        return None
    except NotADirectoryError:
        return None
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode):
        return _BackupEntry(path, "symlink", None, mode, os.readlink(source))
    destination = backup_root / f"entry-{sequence}"
    if stat.S_ISREG(metadata.st_mode):
        shutil.copy2(source, destination, follow_symlinks=False)
        return _BackupEntry(path, "file", destination, mode)
    elif stat.S_ISDIR(metadata.st_mode):
        return _BackupEntry(path, "directory", None, mode)
    else:
        raise CheckoutError(f"unsupported worktree entry: {path!r}")


def _remove_transaction_paths(root: Path, paths: set[bytes]) -> None:
    for path in sorted(paths, key=lambda value: (value.count(b"/"), value), reverse=True):
        target = root / os.fsdecode(path)
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir() and not target.is_symlink():
            try:
                target.rmdir()
            except OSError as error:
                raise CheckoutError(
                    f"cannot remove transaction directory during rollback: {path!r}"
                ) from error


def _restore_backup(
    root: Path, entries: tuple[_BackupEntry, ...], paths: set[bytes]
) -> None:
    _remove_transaction_paths(root, paths)
    for entry in sorted(entries, key=lambda value: (value.path.count(b"/"), value.path)):
        target = root / os.fsdecode(entry.path)
        parent = _safe_parent(root, entry.path)
        if entry.kind == "directory":
            target.mkdir()
            os.chmod(target, entry.mode)
        elif entry.kind == "symlink":
            os.symlink(os.fsdecode(entry.link_target or b""), target)
        else:
            if entry.backup_path is None:
                raise CheckoutError(f"missing backup for {entry.path!r}")
            shutil.copy2(entry.backup_path, target, follow_symlinks=False)
            os.chmod(target, entry.mode)


def checkout_commit(
    repository: Repository,
    object_id: str,
    *,
    head: Head | None,
    advance_symbolic: bool = False,
) -> None:
    """Safely make the worktree and index match a commit, then update HEAD."""
    repository.require_worktree()
    try:
        commit = read_commit(repository.objects_dir, object_id)
        target_files = _tree_files(repository, commit.tree_id)
        snapshot = collect_snapshot(repository)
    except (OSError, ValueError, StatusError) as error:
        raise CheckoutError(f"cannot prepare checkout: {error}") from error

    current_files = set(snapshot.head) | set(snapshot.index)
    tracked_dirty = snapshot.head != snapshot.index or snapshot.index != snapshot.working_tree
    if tracked_dirty:
        raise CheckoutError("local changes would be overwritten by checkout")

    target_paths = set(target_files)
    for untracked in snapshot.untracked:
        if any(
            untracked == path
            or untracked.startswith(path + b"/")
            or path.startswith(untracked + b"/")
            for path in target_paths
        ):
            raise CheckoutError(f"untracked path would be overwritten: {untracked!r}")

    affected = _transaction_paths(current_files | target_paths)
    backup_directory = Path(tempfile.mkdtemp(prefix=".cv-checkout-backup-", dir=repository.root))
    old_index = (repository.git_dir / "index").read_bytes() if (repository.git_dir / "index").exists() else None
    old_head = (repository.git_dir / "HEAD").read_bytes()
    old_ref = None
    if head is not None and head.symbolic_ref is not None:
        try:
            from commitverse_core.refs import read_ref

            old_ref = read_ref(repository, head.symbolic_ref)
        except ReferenceError:
            old_ref = None
    worktree_changed = False
    try:
        backups: list[_BackupEntry] = []
        for sequence, path in enumerate(sorted(affected)):
            entry = _backup_path(repository.root, path, backup_directory, sequence)
            if entry is not None:
                backups.append(entry)
        obsolete = {
            path
            for path in current_files
            if path not in target_paths
            or any(
                path.startswith(target + b"/") or target.startswith(path + b"/")
                for target in target_paths
            )
        }
        for path in sorted(obsolete, key=lambda value: value.count(b"/"), reverse=True):
            worktree_changed = True
            _remove_path(repository.root, path)
        for path in sorted(
            _ancestors_for_paths(obsolete), key=lambda value: value.count(b"/"), reverse=True
        ):
            target = repository.root / os.fsdecode(path)
            if target.is_dir() and not target.is_symlink():
                try:
                    target.rmdir()
                except OSError:
                    pass
        for path, (mode, target_object_id) in sorted(target_files.items()):
            worktree_changed = True
            object_type, payload = read_object(repository.objects_dir, target_object_id)
            if object_type != "blob":
                raise CheckoutError(f"tree file {path!r} does not reference a blob")
            _write_target(repository.root, path, mode, payload)
        write_index(repository.git_dir / "index", _target_index(repository, target_files))
        if head is None:
            set_head_detached(repository, object_id)
        elif head.symbolic_ref is not None:
            if advance_symbolic:
                update_head(repository, object_id)
            set_head_symbolic(repository, head.symbolic_ref)
        else:
            set_head_detached(repository, object_id)
    except (OSError, ValueError) as error:
        try:
            if worktree_changed:
                _restore_backup(repository.root, tuple(backups), affected)
            if old_index is None:
                (repository.git_dir / "index").unlink(missing_ok=True)
            else:
                (repository.git_dir / "index").write_bytes(old_index)
            (repository.git_dir / "HEAD").write_bytes(old_head)
            if (
                head is not None
                and head.symbolic_ref is not None
                and advance_symbolic
                and old_ref is not None
            ):
                write_ref(repository, head.symbolic_ref, old_ref)
        except OSError as rollback_error:
            raise CheckoutError(f"checkout failed and rollback failed: {rollback_error}") from error
        raise CheckoutError(f"checkout failed: {error}") from error
    finally:
        shutil.rmtree(backup_directory, ignore_errors=True)


def switch_branch(repository: Repository, branch_name: str, object_id: str) -> None:
    from commitverse_core.refs import branch_ref_name

    checkout_commit(repository, object_id, head=Head(symbolic_ref=branch_ref_name(branch_name)))


def checkout_revision(repository: Repository, object_id: str) -> None:
    checkout_commit(repository, object_id, head=Head(object_id=object_id))
