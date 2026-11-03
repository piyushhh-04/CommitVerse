"""Safe local repository cloning."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from commitverse_core.checkout import CheckoutError, checkout_commit
from commitverse_core.config import ConfigurationError, update_repository_configuration
from commitverse_core.fetch import FetchError, fetch_from_local
from commitverse_core.index import IndexFormatError, read_index
from commitverse_core.refs import (
    Head,
    ReferenceError,
    compare_and_swap_ref,
    read_ref,
    set_head_symbolic,
)
from commitverse_core.repository import (
    Repository,
    RepositoryError,
    discover_repository,
    initialize_repository,
)
from commitverse_core.status import StatusError, get_status
from commitverse_core.transport import (
    LocalFilesystemTransport,
    RemoteAdvertisement,
    TransportError,
)


class CloneError(ValueError):
    """Raised when a local clone cannot be completed safely."""


@dataclass(frozen=True)
class CloneResult:
    """Published clone details."""

    source: Path
    destination: Path
    branch: str
    object_id: str


def clone_from_local(
    source_path: Path | str,
    destination_path: Path | str,
    *,
    branch: str | None = None,
    base: Path | str | None = None,
) -> CloneResult:
    """Clone one selected branch from a local bare or non-bare repository."""
    try:
        transport = LocalFilesystemTransport.open(source_path, base=base)
        advertisement = transport.advertise(allow_unresolved_head=branch is not None)
        selected_ref, selected_branch, object_id = _select_branch(advertisement, branch)
    except (TransportError, ReferenceError, ValueError) as error:
        raise CloneError(f"cannot open or select clone source: {error}") from error

    destination = Path(destination_path).expanduser()
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    destination = Path(os.path.abspath(destination))
    parent = destination.parent
    _validate_destination(parent, destination)

    temporary: Path | None = None
    clone_error: BaseException | None = None
    try:
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.commitverse-",
                dir=parent,
            )
        )
        repository = initialize_repository(temporary)
        fetch_from_local(
            repository,
            transport.repository.root,
            branches=[selected_ref],
            ref_mapping={selected_ref: "refs/remotes/origin/" + selected_branch},
            allow_unresolved_head=branch is not None,
        )
        set_head_symbolic(repository, f"refs/heads/{selected_branch}")
        checkout_commit(
            repository,
            object_id,
            head=repository_head(repository, selected_branch),
        )
        compare_and_swap_ref(repository, f"refs/heads/{selected_branch}", None, object_id)
        _configure_origin(repository, transport.repository.root)
        _validate_clone(repository, selected_branch, object_id)
        _publish(temporary, destination)
        temporary = None
        return CloneResult(
            source=transport.repository.root,
            destination=destination,
            branch=selected_branch,
            object_id=object_id,
        )
    except (CloneError, FetchError, CheckoutError, ConfigurationError, OSError, ValueError) as error:
        clone_error = error
        raise CloneError(f"clone failed: {error}") from error
    finally:
        if temporary is not None:
            try:
                shutil.rmtree(temporary)
            except OSError as cleanup_error:
                if clone_error is None:
                    raise CloneError(f"clone cleanup failed: {cleanup_error}") from cleanup_error
                raise CloneError(
                    f"clone failed: {clone_error}; cleanup failed: {cleanup_error}"
                ) from clone_error


def _select_branch(
    advertisement: RemoteAdvertisement, branch: str | None
) -> tuple[str, str, str]:
    branches = {reference.name: reference for reference in advertisement.branches}
    if branch is not None:
        selected = branch.removeprefix("refs/heads/")
        ref_name = f"refs/heads/{selected}"
        if ref_name not in branches:
            raise CloneError(f"source branch is not advertised: {ref_name}")
    else:
        if advertisement.head_symbolic_ref is None:
            raise CloneError("source HEAD is detached; specify an explicit branch")
        ref_name = advertisement.head_symbolic_ref
        if ref_name not in branches:
            raise CloneError(f"source HEAD branch is not advertised: {ref_name}")
        selected = ref_name.removeprefix("refs/heads/")
    return ref_name, selected, branches[ref_name].object_id


def _validate_destination(parent: Path, destination: Path) -> None:
    current = parent
    missing: list[Path] = []
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            current = current.parent
            continue
        except OSError as error:
            raise CloneError(f"invalid destination parent {parent}: {error}") from error
        if missing:
            raise CloneError(f"invalid destination parent {parent}: a component is missing")
        if current.is_symlink() or not current.is_dir():
            raise CloneError(f"destination parent is not a safe directory: {current}")
        if current == current.parent:
            break
        current = current.parent
    if destination.exists() or destination.is_symlink():
        raise CloneError(f"destination already exists: {destination}")


def _configure_origin(repository: Repository, source: Path) -> None:
    update_repository_configuration(
        repository,
        lambda config: config.set("remote", "url", str(source), subsection="origin"),
    )


def _validate_clone(repository: Repository, branch: str, object_id: str) -> None:
    try:
        discovered = discover_repository(repository.root)
        if discovered.bare:
            raise CloneError("clone result is bare")
        if read_ref(discovered, f"refs/heads/{branch}") != object_id:
            raise CloneError("clone branch does not name the selected commit")
        if discovered.head_path.read_text(encoding="ascii").strip() != (
            f"ref: refs/heads/{branch}"
        ):
            raise CloneError("clone HEAD is not symbolic to the selected branch")
        read_index(discovered.git_dir / "index")
        status = get_status(discovered)
        if status.staged or status.unstaged or status.untracked:
            raise CloneError("clone result has a dirty working tree")
    except (OSError, ReferenceError, IndexFormatError, StatusError, ValueError) as error:
        raise CloneError(f"clone result validation failed: {error}") from error


def _publish(temporary: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise CloneError(f"destination was created during clone: {destination}")
    try:
        os.rename(temporary, destination)
    except OSError as error:
        raise CloneError(f"cannot publish clone: {error}") from error


def repository_head(repository: Repository, branch: str) -> Head:
    return Head(symbolic_ref=f"refs/heads/{branch}")
