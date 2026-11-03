"""Read and update loose Git references and HEAD."""

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from commitverse_core.commits import read_commit
from commitverse_core.repository import Repository

_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_INVALID_REF_CHARS = frozenset(" ~^:?*[\\")


class ReferenceError(ValueError):
    """Raised when a reference or HEAD value is invalid or unsafe."""


class ReferenceNotFoundError(ReferenceError):
    """Raised when a loose reference does not exist."""


@dataclass(frozen=True)
class Head:
    """A symbolic HEAD target or a detached commit object ID."""

    symbolic_ref: str | None = None
    object_id: str | None = None


@dataclass(frozen=True)
class Branch:
    """A local branch name and its resolved commit ID."""

    name: str
    object_id: str


def validate_ref_name(ref_name: str) -> str:
    """Validate a full ref name using Git's core check-ref-format rules."""
    if not isinstance(ref_name, str) or not ref_name.startswith("refs/"):
        raise ReferenceError("reference names must begin with 'refs/'")
    if (
        ref_name.endswith("/")
        or "//" in ref_name
        or ".." in ref_name
        or "@{" in ref_name
        or ref_name == "@"
        or any(
            character in _INVALID_REF_CHARS
            or ord(character) < 0x20
            or ord(character) == 0x7F
            for character in ref_name
        )
    ):
        raise ReferenceError(f"invalid reference name: {ref_name!r}")
    parts = ref_name.split("/")
    if len(parts) < 3 or any(
        not part or part.startswith(".") or part.endswith(".") or part.endswith(".lock")
        for part in parts
    ):
        raise ReferenceError(f"invalid reference name: {ref_name!r}")
    return ref_name


def branch_ref_name(branch_name: str) -> str:
    """Validate a short local branch name and return its full ref path."""
    if not isinstance(branch_name, str) or branch_name.startswith("-"):
        raise ReferenceError(f"invalid branch name: {branch_name!r}")
    return validate_ref_name(f"refs/heads/{branch_name}")


def _validate_object_id(object_id: str) -> None:
    if (
        not isinstance(object_id, str)
        or _OBJECT_ID_PATTERN.fullmatch(object_id) is None
    ):
        raise ReferenceError("reference target must be a 40-character lowercase SHA-1 ID")


def _safe_ref_path(repository: Repository, ref_name: str, *, create: bool) -> Path:
    validate_ref_name(ref_name)
    current = repository.git_dir
    for component in ref_name.split("/"):
        current = current / component
        if current == repository.git_dir / ref_name:
            break
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if not create:
                raise
            current.mkdir()
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ReferenceError(f"unsafe reference directory: {current}")
    return current


def _atomic_write(path: Path, contents: bytes, *, create_only: bool) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".cv-ref-", suffix=".lock", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if create_only:
            try:
                os.link(temporary_path, path)
            except FileExistsError as error:
                raise ReferenceError(f"reference already exists: {path.name}") from error
        else:
            os.replace(temporary_path, path)
    except OSError:
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _read_ref_text(path: Path, ref_name: str) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ReferenceNotFoundError(f"reference does not exist: {ref_name}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ReferenceError(f"reference is not a regular file: {ref_name}")
    try:
        contents = path.read_bytes()
        text = contents.decode("ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise ReferenceError(f"cannot read reference {ref_name}: {error}") from error
    if text.endswith("\n"):
        text = text[:-1]
    if not _OBJECT_ID_PATTERN.fullmatch(text):
        raise ReferenceError(f"malformed reference contents: {ref_name}")
    return text


def read_ref(repository: Repository, ref_name: str) -> str:
    """Read a loose ref's SHA-1 ID without resolving its target object."""
    try:
        path = _safe_ref_path(repository, ref_name, create=False)
    except FileNotFoundError as error:
        raise ReferenceNotFoundError(f"reference does not exist: {ref_name}") from error
    return _read_ref_text(path, ref_name)


def write_ref(
    repository: Repository,
    ref_name: str,
    object_id: str,
    *,
    create_only: bool = False,
) -> None:
    """Atomically write a loose ref to an existing commit object."""
    validate_ref_name(ref_name)
    _validate_object_id(object_id)
    try:
        read_commit(repository.objects_dir, object_id)
    except (OSError, ValueError) as error:
        raise ReferenceError(
            f"reference target is not a valid commit object: {object_id}"
        ) from error
    path = _safe_ref_path(repository, ref_name, create=True)
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ReferenceError(f"reference is not a regular file: {ref_name}")
    try:
        _atomic_write(path, f"{object_id}\n".encode("ascii"), create_only=create_only)
    except ReferenceError as error:
        raise ReferenceError(f"reference already exists: {ref_name}") from error


def create_branch(repository: Repository, branch_name: str, object_id: str) -> None:
    """Create a local branch without replacing an existing branch."""
    ref_name = branch_ref_name(branch_name)
    write_ref(repository, ref_name, object_id, create_only=True)


def delete_branch(repository: Repository, branch_name: str) -> None:
    """Delete an existing local branch ref without touching its objects."""
    ref_name = branch_ref_name(branch_name)
    if current_branch(repository) == branch_name:
        raise ReferenceError("cannot delete the currently checked-out branch")
    target = resolve_branch(repository, branch_name)
    current = resolve_head(repository)
    if current is None:
        raise ReferenceError("cannot delete a branch before the first commit")
    from commitverse_core.merge_base import is_ancestor

    if not is_ancestor(repository, target, current):
        raise ReferenceError(
            f"branch {branch_name!r} is not fully merged into the current branch"
        )
    path = _safe_ref_path(repository, ref_name, create=False)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ReferenceNotFoundError(f"reference does not exist: {ref_name}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ReferenceError(f"reference is not a regular file: {ref_name}")
    path.unlink()
    parent = path.parent
    while parent != repository.git_dir / "refs" / "heads":
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def read_head(repository: Repository) -> Head:
    """Read and validate symbolic or detached HEAD."""
    head_path = repository.git_dir / "HEAD"
    try:
        metadata = head_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ReferenceError("HEAD must be a regular file")
        contents = head_path.read_bytes().decode("ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise ReferenceError(f"cannot read HEAD: {error}") from error
    if contents.endswith("\n"):
        contents = contents[:-1]
    if contents.startswith("ref: "):
        ref_name = validate_ref_name(contents[5:])
        return Head(symbolic_ref=ref_name)
    _validate_object_id(contents)
    return Head(object_id=contents)


def resolve_head(repository: Repository) -> str | None:
    """Resolve HEAD; return None only for an unborn local branch."""
    head = read_head(repository)
    if head.object_id is not None:
        try:
            read_commit(repository.objects_dir, head.object_id)
        except (OSError, ValueError) as error:
            raise ReferenceError(f"detached HEAD is not a valid commit: {error}") from error
        return head.object_id

    if head.symbolic_ref is None:
        raise ReferenceError("HEAD has no symbolic or detached target")
    try:
        object_id = read_ref(repository, head.symbolic_ref)
    except ReferenceNotFoundError:
        if head.symbolic_ref.startswith("refs/heads/"):
            return None
        raise
    try:
        read_commit(repository.objects_dir, object_id)
    except (OSError, ValueError) as error:
        raise ReferenceError(
            f"HEAD reference {head.symbolic_ref} does not name a valid commit: {error}"
        ) from error
    return object_id


def update_head(repository: Repository, object_id: str) -> None:
    """Advance the symbolic HEAD's ref or the detached HEAD itself."""
    _validate_object_id(object_id)
    try:
        read_commit(repository.objects_dir, object_id)
    except (OSError, ValueError) as error:
        raise ReferenceError(f"HEAD target is not a valid commit: {object_id}") from error
    head = read_head(repository)
    if head.symbolic_ref is not None:
        write_ref(repository, head.symbolic_ref, object_id)
        return
    _atomic_write(
        repository.git_dir / "HEAD",
        f"{object_id}\n".encode("ascii"),
        create_only=False,
    )


def set_head_symbolic(repository: Repository, ref_name: str) -> None:
    """Make HEAD symbolically point at a validated local or other ref."""
    validate_ref_name(ref_name)
    _atomic_write(
        repository.git_dir / "HEAD",
        f"ref: {ref_name}\n".encode("ascii"),
        create_only=False,
    )


def set_head_detached(repository: Repository, object_id: str) -> None:
    """Make HEAD directly point at a validated commit."""
    _validate_object_id(object_id)
    try:
        read_commit(repository.objects_dir, object_id)
    except (OSError, ValueError) as error:
        raise ReferenceError(f"HEAD target is not a valid commit: {object_id}") from error
    _atomic_write(
        repository.git_dir / "HEAD",
        f"{object_id}\n".encode("ascii"),
        create_only=False,
    )


def current_branch(repository: Repository) -> str | None:
    """Return the short symbolic branch name, or None for detached HEAD."""
    head = read_head(repository)
    if head.symbolic_ref is None or not head.symbolic_ref.startswith("refs/heads/"):
        return None
    return head.symbolic_ref.removeprefix("refs/heads/")


def resolve_branch(repository: Repository, branch_name: str) -> str:
    """Resolve a local branch and verify that it names a valid commit."""
    ref_name = branch_ref_name(branch_name)
    object_id = read_ref(repository, ref_name)
    try:
        read_commit(repository.objects_dir, object_id)
    except (OSError, ValueError) as error:
        raise ReferenceError(
            f"branch {branch_name!r} does not name a valid commit: {error}"
        ) from error
    return object_id


def list_branches(repository: Repository) -> tuple[Branch, ...]:
    """List and validate loose local branches in deterministic name order."""
    root = repository.git_dir / "refs" / "heads"
    try:
        metadata = root.lstat()
    except OSError as error:
        raise ReferenceError(f"cannot access local branch directory: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ReferenceError(f"unsafe local branch directory: {root}")

    def raise_walk_error(error: OSError) -> None:
        raise error

    branches: list[Branch] = []
    for directory, directory_names, file_names in os.walk(
        root, followlinks=False, onerror=raise_walk_error
    ):
        current = Path(directory)
        for name in tuple(directory_names):
            child = current / name
            if child.is_symlink():
                raise ReferenceError(f"unsafe reference directory: {child}")
        for name in file_names:
            if name.endswith(".lock"):
                continue
            path = current / name
            ref_name = path.relative_to(repository.git_dir).as_posix()
            validate_ref_name(ref_name)
            object_id = _read_ref_text(path, ref_name)
            try:
                read_commit(repository.objects_dir, object_id)
            except (OSError, ValueError) as error:
                raise ReferenceError(
                    f"branch {ref_name.removeprefix('refs/heads/')!r} "
                    f"does not name a valid commit: {error}"
                ) from error
            branches.append(
                Branch(ref_name.removeprefix("refs/heads/"), object_id)
            )
    return tuple(sorted(branches, key=lambda branch: branch.name.encode("utf-8")))
