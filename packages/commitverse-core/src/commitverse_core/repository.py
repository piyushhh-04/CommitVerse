"""Initialize and discover bare and non-bare CommitVerse repositories."""

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
    """A repository's Git directory and optional working-tree capability."""

    root: Path
    git_dir: Path
    objects_dir: Path
    refs_dir: Path
    head_path: Path
    config_path: Path
    work_tree: Path | None
    bare: bool
    created: bool = False


    def require_worktree(self) -> Path:
        """Return the working tree or raise for a bare repository."""
        if self.work_tree is None:
            raise RepositoryError(
                "this operation requires a working tree; bare repositories "
                "support object and reference operations only"
            )
        return self.work_tree


def initialize_repository(
    path: Path | str, *, bare: bool = False
) -> Repository:
    """Create a Git-compatible SHA-1 repository, preserving valid metadata."""
    try:
        root = Path(path).expanduser().resolve()
        existed = root.exists()
        if root.exists() and not root.is_dir():
            raise RepositoryError(f"repository path is not a directory: {root}")
        if bare and not existed:
            root.parent.mkdir(parents=True, exist_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)
    except RepositoryError:
        raise
    except (OSError, RuntimeError) as error:
        raise RepositoryError(f"cannot create repository path {path!s}: {error}") from error

    if not bare and not root.is_dir():
        raise RepositoryError(f"repository path is not a directory: {root}")

    git_dir = root if bare else root / ".git"
    if bare and git_dir.exists() and not git_dir.is_dir():
        raise RepositoryError(f"repository path is not a directory: {root}")
    if git_dir.exists() or git_dir.is_symlink():
        if _is_valid_git_directory(git_dir, bare=bare):
            return _repository_at(root, git_dir, created=False)
        if bare and not any(git_dir.iterdir()):
            _initialize_git_directory(git_dir, bare=True)
            return _repository_at(root, git_dir, created=True)
        metadata_label = "existing .git" if not bare else "existing repository metadata"
        raise RepositoryError(
            f"cannot initialize repository at {root}: {metadata_label} "
            "is not a valid supported repository"
        )

    try:
        if bare:
            with tempfile.TemporaryDirectory(
                prefix=".commitverse-init-", dir=root.parent
            ) as temporary_directory:
                temporary_git_dir = Path(temporary_directory)
                _initialize_git_directory(temporary_git_dir, bare=True)
                temporary_git_dir.rename(git_dir)
        else:
            with tempfile.TemporaryDirectory(
                prefix=".commitverse-init-", dir=root
            ) as temporary_directory:
                temporary_git_dir = Path(temporary_directory)
                _initialize_git_directory(temporary_git_dir, bare=False)
                temporary_git_dir.rename(git_dir)
    except OSError as error:
        if git_dir.exists() and _is_valid_git_directory(git_dir, bare=bare):
            return _repository_at(root, git_dir, created=False)
        raise RepositoryError(
            f"cannot initialize repository at {root}: {error}"
        ) from error

    return _repository_at(root, git_dir, created=True)


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
        if _is_valid_git_directory(directory, bare=True):
            return _repository_at(directory, directory, created=False)
        git_dir = directory / ".git"
        if git_dir.exists() or git_dir.is_symlink():
            if _is_valid_git_directory(git_dir, bare=False):
                return _repository_at(directory, git_dir, created=False)
            raise RepositoryError(
                f"invalid or unsupported repository metadata at {git_dir}"
            )

    raise RepositoryNotFoundError(
        f"no valid CommitVerse repository found from {start}"
    )


def _repository_at(root: Path, git_dir: Path, *, created: bool) -> Repository:
    bare = _read_bare_config(git_dir / "config")
    return Repository(
        root=root,
        git_dir=git_dir,
        objects_dir=git_dir / "objects",
        refs_dir=git_dir / "refs",
        head_path=git_dir / "HEAD",
        config_path=git_dir / "config",
        work_tree=None if bare else root,
        bare=bare,
        created=created,
    )


def _read_bare_config(config_path: Path) -> bool:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read_string(config_path.read_text(encoding="utf-8"))
    if config.getint("core", "repositoryformatversion") != 0:
        raise ValueError("unsupported repository format version")
    return config.getboolean("core", "bare")


def _initialize_git_directory(git_dir: Path, *, bare: bool) -> None:
    for directory in (
        "objects/info",
        "objects/pack",
        "refs/heads",
        "refs/tags",
    ):
        (git_dir / directory).mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (git_dir / "config").write_text(
        "[core]\n"
        "\trepositoryformatversion = 0\n"
        "\tfilemode = true\n"
        f"\tbare = {'true' if bare else 'false'}\n"
        "\tlogallrefupdates = true\n",
        encoding="ascii",
    )


def _is_valid_git_directory(git_dir: Path, *, bare: bool) -> bool:
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

    return format_version == 0 and is_bare == bare and _is_valid_head(head)


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
