"""Safe local storage operations delegated to CommitVerse Core."""

from __future__ import annotations

import re
import shutil
import stat
from pathlib import Path

from commitverse_hub.repositories.core_adapter import (
    CoreAdapterError,
    initialize_bare_repository,
    verify_bare_repository,
)

_STORAGE_KEY_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_SOURCE_ROOT = Path(__file__).resolve().parents[5]


class RepositoryStorageError(Exception):
    """Raised when a controlled repository storage operation cannot complete."""


def create_bare_repository(
    storage_root: Path,
    storage_key: str,
    *,
    allow_existing: bool = False,
) -> bool:
    """Initialize and publish one bare Core repository; return whether published."""
    root = _prepare_storage_root(storage_root, create=True)
    final_path = _repository_path(root, storage_key)
    temporary_path = root / f".provisioning-{storage_key}.tmp"

    if _path_exists(final_path):
        if not allow_existing:
            raise RepositoryStorageError("Repository storage destination already exists.")
        _verify_bare_repository(final_path)
        return False

    if _path_exists(temporary_path):
        _remove_temporary_directory(root, temporary_path, storage_key)

    try:
        temporary_path.mkdir(mode=0o700)
        initialize_bare_repository(temporary_path)
        if _path_exists(final_path):
            raise RepositoryStorageError("Repository storage destination already exists.")
        temporary_path.rename(final_path)
        _verify_bare_repository(final_path)
        return True
    except RepositoryStorageError:
        _remove_temporary_directory(root, temporary_path, storage_key)
        raise
    except (CoreAdapterError, OSError, RuntimeError, ValueError) as exc:
        try:
            _remove_temporary_directory(root, temporary_path, storage_key)
        except RepositoryStorageError:
            raise
        raise RepositoryStorageError("Core repository initialization failed.") from exc


def delete_bare_repository(storage_root: Path, storage_key: str) -> bool:
    """Remove only a verified bare repository at its generated root child path."""
    root = _prepare_storage_root(storage_root, create=False)
    if root is None:
        return False
    repository_path = _repository_path(root, storage_key)
    if not _path_exists(repository_path):
        return False
    _verify_bare_repository(repository_path)
    try:
        shutil.rmtree(repository_path)
    except OSError as exc:
        raise RepositoryStorageError("Core repository deletion failed.") from exc
    return True


def _prepare_storage_root(storage_root: Path, *, create: bool) -> Path | None:
    root = Path(storage_root)
    if not root.is_absolute() or ".." in root.parts:
        raise RepositoryStorageError("Repository storage root is invalid.")
    if root == _SOURCE_ROOT or root.is_relative_to(_SOURCE_ROOT):
        raise RepositoryStorageError("Repository storage root must be outside the source tree.")

    current = Path(root.anchor)
    for component in root.parts[1:]:
        current = current / component
        try:
            entry = current.lstat()
        except FileNotFoundError:
            if not create:
                return None
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise RepositoryStorageError("Repository storage root is unavailable.") from exc
            try:
                entry = current.lstat()
            except OSError as exc:
                raise RepositoryStorageError("Repository storage root is unavailable.") from exc
        except OSError as exc:
            raise RepositoryStorageError("Repository storage root is unavailable.") from exc

        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise RepositoryStorageError("Repository storage root contains an unsafe path component.")

    if current != root:
        raise RepositoryStorageError("Repository storage root is invalid.")
    try:
        root_mode = stat.S_IMODE(current.stat().st_mode)
    except OSError as exc:
        raise RepositoryStorageError("Repository storage root is unavailable.") from exc
    if root_mode & 0o077:
        raise RepositoryStorageError("Repository storage root permissions must be private.")
    return current


def _repository_path(root: Path, storage_key: str) -> Path:
    if not _STORAGE_KEY_PATTERN.fullmatch(storage_key):
        raise RepositoryStorageError("Repository storage key is invalid.")
    return root / f"{storage_key}.git"


def _verify_bare_repository(path: Path) -> None:
    try:
        entry = path.lstat()
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise RepositoryStorageError("Repository storage path is not a directory.")
        verify_bare_repository(path)
    except RepositoryStorageError:
        raise
    except (CoreAdapterError, OSError, RuntimeError, ValueError) as exc:
        raise RepositoryStorageError("Stored Core repository could not be verified.") from exc


def _remove_temporary_directory(root: Path, path: Path, storage_key: str) -> None:
    expected_path = root / f".provisioning-{storage_key}.tmp"
    if path != expected_path or path.parent != root:
        raise RepositoryStorageError("Temporary repository path is outside the storage root.")
    if not _path_exists(path):
        return
    try:
        entry = path.lstat()
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise RepositoryStorageError("Temporary repository path is unsafe.")
        shutil.rmtree(path)
    except RepositoryStorageError:
        raise
    except OSError as exc:
        raise RepositoryStorageError("Temporary repository cleanup failed.") from exc


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RepositoryStorageError("Repository storage path cannot be inspected.") from exc
    return True
