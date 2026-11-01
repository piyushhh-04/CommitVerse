"""Stage working-tree files in the repository's Git index."""

import fnmatch
import os
import stat
from pathlib import Path
from typing import Iterable, Sequence

from commitverse_core.index import (
    Index,
    IndexEntry,
    IndexStat,
    read_index,
    write_index,
)
from commitverse_core.objects.store import write_object
from commitverse_core.repository import Repository


class StagingError(ValueError):
    """Raised when a requested working-tree path cannot be staged safely."""


def _uint32(value: int) -> int:
    return value & 0xFFFFFFFF


def _stat_metadata(metadata: os.stat_result, mode: int) -> IndexStat:
    return IndexStat(
        ctime_seconds=_uint32(int(metadata.st_ctime)),
        ctime_nanoseconds=_uint32(metadata.st_ctime_ns % 1_000_000_000),
        mtime_seconds=_uint32(int(metadata.st_mtime)),
        mtime_nanoseconds=_uint32(metadata.st_mtime_ns % 1_000_000_000),
        device=_uint32(metadata.st_dev),
        inode=_uint32(metadata.st_ino),
        mode=mode,
        uid=_uint32(metadata.st_uid),
        gid=_uint32(metadata.st_gid),
        size=_uint32(metadata.st_size),
    )


def _mode_for(metadata: os.stat_result) -> int:
    if stat.S_ISLNK(metadata.st_mode):
        return 0o120000
    if stat.S_ISREG(metadata.st_mode):
        return 0o100755 if metadata.st_mode & 0o111 else 0o100644
    raise StagingError("only regular files and symbolic links can be staged")


def _load_ignore_rules(root: Path) -> tuple[tuple[bytes, bool, bool, bool], ...]:
    ignore_path = root / ".gitignore"
    try:
        metadata = ignore_path.lstat()
    except FileNotFoundError:
        return ()
    if not stat.S_ISREG(metadata.st_mode):
        raise StagingError("the worktree-root .gitignore must be a regular file")
    contents = ignore_path.read_bytes()

    rules: list[tuple[bytes, bool, bool, bool]] = []
    for raw_line in contents.splitlines():
        line = raw_line.rstrip(b" \t")
        if not line or line.startswith(b"#"):
            continue
        negated = line.startswith(b"!")
        if negated:
            line = line[1:]
        elif line.startswith(b"\\#") or line.startswith(b"\\!"):
            line = line[1:]
        if not line:
            continue
        directory_only = line.endswith(b"/")
        if directory_only:
            line = line[:-1]
        anchored = line.startswith(b"/")
        if anchored:
            line = line[1:]
        if not line:
            continue
        has_slash = b"/" in line
        rules.append((line, negated, directory_only, anchored or has_slash))
    return tuple(rules)


def _matches_ignore_rule(
    path: bytes,
    is_directory: bool,
    rule: tuple[bytes, bool, bool, bool],
) -> bool:
    pattern, _, directory_only, anchored = rule
    parts = path.split(b"/")
    for index in range(len(parts)):
        component_is_directory = index < len(parts) - 1 or is_directory
        if directory_only and not component_is_directory:
            continue
        candidate = b"/".join(parts[: index + 1])
        if anchored:
            if fnmatch.fnmatchcase(candidate, pattern):
                return True
        elif fnmatch.fnmatchcase(parts[index], pattern):
            return True
    return False


def _is_ignored(
    path: bytes,
    is_directory: bool,
    rules: tuple[tuple[bytes, bool, bool, bool], ...],
) -> bool:
    ignored = False
    for rule in rules:
        if _matches_ignore_rule(path, is_directory, rule):
            ignored = not rule[1]
    return ignored


def _relative_bytes(path: Path, root: Path) -> bytes:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise StagingError(f"path is outside the repository: {path}") from error
    encoded = os.fsencode(relative.as_posix())
    if not encoded or any(part in (b"", b".", b"..") for part in encoded.split(b"/")):
        raise StagingError(f"invalid repository-relative path: {path}")
    return encoded


def _resolve_requested_path(
    repository: Repository, value: str | Path, cwd: Path
) -> Path:
    root = repository.root.resolve(strict=True)
    requested = Path(value).expanduser()
    candidate = Path(
        os.path.abspath(requested if requested.is_absolute() else cwd / requested)
    )
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise StagingError(f"path is outside the repository: {value}") from error
    if any(part == ".git" for part in relative.parts):
        raise StagingError("the repository's .git directory cannot be staged")

    if candidate == root:
        return candidate
    parent = candidate.parent.resolve(strict=False)
    try:
        parent.relative_to(root)
    except ValueError as error:
        raise StagingError(f"path resolves outside the repository: {value}") from error
    return candidate


def _walk_directory(root: Path, start: Path) -> Iterable[Path]:
    def raise_walk_error(error: OSError) -> None:
        raise error

    if start != root and ((start / ".git").exists() or (start / ".git").is_symlink()):
        raise StagingError(f"nested repositories cannot be staged: {start}")

    for directory, directory_names, file_names in os.walk(
        start, topdown=True, followlinks=False, onerror=raise_walk_error
    ):
        current = Path(directory)
        for name in tuple(directory_names):
            child = current / name
            if name == ".git":
                directory_names.remove(name)
                continue
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                directory_names.remove(name)
                yield child
                continue
            if (child / ".git").exists() or (child / ".git").is_symlink():
                directory_names.remove(name)
                continue
        for name in file_names:
            if name == ".git":
                continue
            yield current / name


def _write_file_entry(repository: Repository, root: Path, path: Path) -> IndexEntry:
    metadata = path.lstat()
    mode = _mode_for(metadata)
    if mode == 0o120000:
        payload = os.readlink(os.fsencode(path))
    else:
        payload = path.read_bytes()
    object_id = write_object(repository.objects_dir, "blob", payload)
    return IndexEntry(
        path=_relative_bytes(path, root),
        object_id=object_id,
        stat=_stat_metadata(metadata, mode),
    )


def add_paths(
    repository: Repository,
    paths: Sequence[str | Path] = (),
    *,
    all: bool = False,
    cwd: Path | None = None,
) -> int:
    """Stage selected paths or the whole working tree; return changed entry count."""
    root = repository.root.resolve(strict=True)
    working_directory = (Path.cwd() if cwd is None else cwd).resolve(strict=True)
    try:
        working_directory.relative_to(root)
    except ValueError as error:
        raise StagingError("current directory is outside the repository") from error
    if all and paths:
        raise StagingError("cv add -A does not accept additional paths")
    if not all and not paths:
        raise StagingError("cv add requires one or more paths or -A")

    index_path = repository.git_dir / "index"
    current_index = read_index(index_path)
    old_entries_by_path: dict[bytes, list[IndexEntry]] = {}
    for entry in current_index.entries:
        old_entries_by_path.setdefault(entry.path, []).append(entry)

    rules = _load_ignore_rules(root)
    found: dict[bytes, Path] = {}
    scopes: list[tuple[bytes, bool]] = []

    if all:
        paths_to_scan: Iterable[Path] = _walk_directory(root, root)
        scopes.append((b"", True))
    else:
        selected: list[Path] = []
        for value in paths:
            candidate = _resolve_requested_path(repository, value, working_directory)
            try:
                metadata = candidate.lstat()
            except FileNotFoundError:
                relative = _relative_bytes(candidate, root)
                scopes.append((relative, True))
                if not any(
                    entry_path == relative or entry_path.startswith(relative + b"/")
                    for entry_path in old_entries_by_path
                ):
                    raise StagingError(f"path does not exist and is not staged: {value}")
                continue

            relative = _relative_bytes(candidate, root) if candidate != root else b""
            is_directory = stat.S_ISDIR(metadata.st_mode)
            scopes.append((relative, is_directory))
            if is_directory and relative == b"":
                selected.extend(_walk_directory(root, root))
            elif is_directory:
                selected.extend(_walk_directory(root, candidate))
            else:
                selected.append(candidate)
        paths_to_scan = selected

    for path in paths_to_scan:
        relative = _relative_bytes(path, root)
        metadata = path.lstat()
        if relative == b".git" or b"/.git/" in b"/" + relative + b"/":
            continue
        found[relative] = path

    new_entries = dict(old_entries_by_path)
    for relative, include_descendants in scopes:
        for existing_path in tuple(new_entries):
            if not relative:
                selected_scope = True
            else:
                selected_scope = existing_path == relative or (
                    include_descendants
                    and existing_path.startswith(relative + b"/")
                )
            if selected_scope and existing_path not in found:
                del new_entries[existing_path]

    for relative, path in found.items():
        existing_entries = new_entries.get(relative, [])
        if (
            _is_ignored(
                relative,
                not path.is_symlink() and path.is_dir(),
                rules,
            )
            and not existing_entries
        ):
            continue
        updated = _write_file_entry(repository, root, path)
        previous_stage_zero = next(
            (entry for entry in existing_entries if entry.stage == 0), None
        )
        if (
            previous_stage_zero is not None
            and previous_stage_zero.object_id == updated.object_id
            and previous_stage_zero.stat.mode == updated.stat.mode
        ):
            continue
        new_entries[relative] = [updated]

    flattened = tuple(
        sorted(
            (entry for entries in new_entries.values() for entry in entries),
            key=lambda entry: (entry.path, entry.stage),
        )
    )
    if flattened == current_index.entries:
        return 0
    write_index(index_path, Index(flattened))
    return len(
        {
            entry.path
            for entry in flattened
            if entry.path not in old_entries_by_path
            or entry not in old_entries_by_path[entry.path]
        }
    ) + len(set(old_entries_by_path) - {entry.path for entry in flattened})
