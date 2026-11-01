"""Initialize and discover non-bare CommitVerse repositories."""

import configparser
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


class RepositoryError(Exception):
    """Raised when a repository cannot be initialized or discovered."""


class RepositoryNotFoundError(RepositoryError):
    """Raised when no valid repository exists at or above a starting path."""


@dataclass(frozen=True)
class Repository:
    """A discovered non-bare repository and its object database paths."""

    root: Path
    git_dir: Path
    objects_dir: Path
    created: bool = False


def initialize_repository(path: Path | str) -> Repository:
    """Create a Git-compatible SHA-1 repository, preserving an existing one."""
    try:
        root = Path(path).expanduser().resolve()
        if root.exists() and not root.is_dir():
            raise RepositoryError(f"repository path is not a directory: {root}")
        root.mkdir(parents=True, exist_ok=True)
    except RepositoryError:
        raise
    except (OSError, RuntimeError) as error:
        raise RepositoryError(f"cannot create repository path {path!s}: {error}") from error

    if not root.is_dir():
        raise RepositoryError(f"repository path is not a directory: {root}")

    git_dir = root / ".git"
    if git_dir.exists() or git_dir.is_symlink():
        if _is_valid_git_directory(git_dir):
            return _repository_at(root, created=False)
        raise RepositoryError(
            f"cannot initialize repository at {root}: existing .git is not "
            "a valid supported repository"
        )

    try:
        with tempfile.TemporaryDirectory(
            prefix=".commitverse-init-", dir=root
        ) as temporary_directory:
            temporary_git_dir = Path(temporary_directory)
            for directory in (
                "objects/info",
                "objects/pack",
                "refs/heads",
                "refs/tags",
            ):
                (temporary_git_dir / directory).mkdir(parents=True, exist_ok=True)

            (temporary_git_dir / "HEAD").write_text(
                "ref: refs/heads/main\n", encoding="ascii"
            )
            (temporary_git_dir / "config").write_text(
                "[core]\n"
                "\trepositoryformatversion = 0\n"
                "\tfilemode = true\n"
                "\tbare = false\n"
                "\tlogallrefupdates = true\n",
                encoding="ascii",
            )
            temporary_git_dir.rename(git_dir)
    except OSError as error:
        if git_dir.exists() and _is_valid_git_directory(git_dir):
            return _repository_at(root, created=False)
        raise RepositoryError(
            f"cannot initialize repository at {root}: {error}"
        ) from error

    return _repository_at(root, created=True)


def discover_repository(start_path: Path | str | None = None) -> Repository:
    """Find a valid repository from a directory or file path and its parents."""
    requested_path = Path.cwd() if start_path is None else Path(start_path).expanduser()
    try:
        start = requested_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RepositoryError(
            f"cannot access repository search path {requested_path}: {error}"
        ) from error

    if start.is_file():
        start = start.parent
    elif not start.is_dir():
        raise RepositoryError(f"repository search path is not a file or directory: {start}")

    for directory in (start, *start.parents):
        git_dir = directory / ".git"
        if git_dir.exists() or git_dir.is_symlink():
            if _is_valid_git_directory(git_dir):
                return _repository_at(directory, created=False)
            raise RepositoryError(
                f"invalid or unsupported repository metadata at {git_dir}"
            )

    raise RepositoryNotFoundError(
        f"no valid CommitVerse repository found from {start}"
    )


def _repository_at(root: Path, *, created: bool) -> Repository:
    git_dir = root / ".git"
    return Repository(
        root=root,
        git_dir=git_dir,
        objects_dir=git_dir / "objects",
        created=created,
    )


def _is_valid_git_directory(git_dir: Path) -> bool:
    if git_dir.is_symlink() or not git_dir.is_dir():
        return False

    if not all(
        (git_dir / relative_path).is_dir()
        for relative_path in ("objects", "refs", "refs/heads")
    ):
        return False

    head_path = git_dir / "HEAD"
    config_path = git_dir / "config"
    if not head_path.is_file() or not config_path.is_file():
        return False

    try:
        head = head_path.read_text(encoding="ascii").strip()
        config_text = config_path.read_text(encoding="utf-8")
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read_string(config_text)
        format_version = config.getint("core", "repositoryformatversion")
        is_bare = config.getboolean("core", "bare")
    except (OSError, UnicodeError, configparser.Error, ValueError):
        return False

    return format_version == 0 and not is_bare and _is_valid_head(head)


def _is_valid_head(head: str) -> bool:
    if _OBJECT_ID_PATTERN.fullmatch(head) is not None:
        return True
    if not head.startswith("ref: refs/"):
        return False

    reference = head.removeprefix("ref: refs/")
    components = reference.split("/")
    return bool(reference) and all(
        component not in ("", ".", "..")
        and not any(character.isspace() for character in component)
        and "\\" not in component
        for component in components
    )
