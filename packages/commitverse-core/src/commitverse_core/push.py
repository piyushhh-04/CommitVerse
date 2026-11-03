"""Fast-forward-only pushes to local bare repositories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from commitverse_core.fetch import (
    FetchError,
    TransferLimits,
    _canonical_size,
    _destination_object_exists,
    _reachable_objects,
    _validate_limits,
)
from commitverse_core.objects import read_object_bounded, write_object
from commitverse_core.refs import (
    ReferenceError,
    ReferenceExpectationError,
    ReferenceNotFoundError,
    branch_ref_name,
    compare_and_swap_ref,
    read_ref,
)
from commitverse_core.repository import Repository, RepositoryError
from commitverse_core.transport import LocalFilesystemTransport, TransportError


class PushError(ValueError):
    """Raised when a push cannot be safely prepared."""


class NonFastForwardError(PushError):
    """Raised when a push would discard destination history."""


@dataclass(frozen=True)
class PushResult:
    """Result of one branch publication."""

    source_ref: str
    destination_ref: str
    source_object_id: str
    status: str
    objects_transferred: int
    published: bool
    error: str | None = None


def push_to_local(
    source: Repository,
    destination_path: Path | str,
    *,
    source_branch: str,
    destination_branch: str | None = None,
    base: Path | str | None = None,
    limits: TransferLimits | None = None,
) -> PushResult:
    """Push one explicit source branch to a local bare destination."""
    selected_limits = limits or TransferLimits()
    try:
        _validate_limits(selected_limits)
    except ValueError as error:
        raise PushError(str(error)) from error
    if source.bare:
        raise PushError("push source must be a non-bare repository")

    source_ref = _branch_ref(source_branch)
    destination_ref = _branch_ref(
        source_branch if destination_branch is None else destination_branch
    )
    try:
        source_object_id = read_ref(source, source_ref)
    except (ReferenceError, OSError) as error:
        raise PushError(f"cannot read source branch {source_ref}: {error}") from error

    try:
        destination = LocalFilesystemTransport.open(
            destination_path, base=base
        ).repository
    except (TransportError, RepositoryError, ValueError) as error:
        raise PushError(f"cannot open push destination: {error}") from error
    if not destination.bare:
        raise PushError("push destination must be a bare repository")
    if (destination.git_dir / "packed-refs").exists():
        raise PushError("packed references are unsupported for push")

    try:
        current_object_id = read_ref(destination, destination_ref)
    except ReferenceNotFoundError:
        current_object_id = None
    except (ReferenceError, OSError) as error:
        raise PushError(
            f"cannot read destination branch {destination_ref}: {error}"
        ) from error

    source_closure = _read_closure(
        source,
        source_object_id,
        selected_limits,
        "source",
    )
    _require_commit_tip(source_closure, source_object_id, source_ref)
    if current_object_id is not None:
        destination_closure = _read_closure(
            destination,
            current_object_id,
            selected_limits,
            "destination",
        )
        _require_commit_tip(destination_closure, current_object_id, destination_ref)
        if current_object_id not in {item.object_id for item in source_closure}:
            raise NonFastForwardError(
                f"push rejected: {destination_ref} is not an ancestor of "
                f"{source_ref}"
            )

    missing = [
        item
        for item in source_closure
        if not _destination_object_exists(destination, item.object_id, selected_limits)
    ]
    for item in missing:
        object_path = destination.objects_dir / item.object_id[:2] / item.object_id[2:]
        if object_path.exists():
            raise PushError(f"existing destination object is malformed: {item.object_id}")
    total = sum(_canonical_size(item.object_type, item.payload) for item in missing)
    if total > selected_limits.max_total_decompressed_transfer:
        raise PushError(
            f"transfer exceeds {selected_limits.max_total_decompressed_transfer} "
            "decompressed bytes"
        )

    for item in missing:
        try:
            write_object(destination.objects_dir, item.object_type, item.payload)
        except (OSError, ValueError) as error:
            raise PushError(f"cannot transfer object {item.object_id}: {error}") from error

    for item in source_closure:
        try:
            read_object_bounded(
                destination.objects_dir,
                item.object_id,
                max_compressed_size=selected_limits.max_compressed_object_size,
                max_decompressed_size=selected_limits.max_decompressed_object_size,
            )
        except (OSError, ValueError) as error:
            raise PushError(
                f"destination object is not readable after transfer: {item.object_id}"
            ) from error

    try:
        compare_and_swap_ref(
            destination,
            destination_ref,
            current_object_id,
            source_object_id,
        )
    except ReferenceExpectationError as error:
        return PushResult(
            source_ref,
            destination_ref,
            source_object_id,
            "failed",
            len(missing),
            False,
            str(error),
        )
    except ReferenceError as error:
        published = getattr(error, "published", False)
        return PushResult(
            source_ref,
            destination_ref,
            source_object_id,
            "failed",
            len(missing),
            published,
            str(error),
        )

    return PushResult(
        source_ref,
        destination_ref,
        source_object_id,
        "updated",
        len(missing),
        True,
    )


def _branch_ref(branch: str) -> str:
    if not isinstance(branch, str):
        raise PushError(f"invalid branch name: {branch!r}")
    if branch.startswith("refs/") and not branch.startswith("refs/heads/"):
        raise PushError(f"invalid branch name: {branch!r}")
    try:
        return branch_ref_name(branch.removeprefix("refs/heads/"))
    except ReferenceError as error:
        raise PushError(f"invalid branch name: {branch!r}") from error


def _read_closure(
    repository: Repository,
    object_id: str,
    limits: TransferLimits,
    label: str,
):
    try:
        return _reachable_objects(
            repository,
            (("refs/heads/" + label, "refs/heads/" + label, object_id),),
            limits,
        )
    except (FetchError, OSError, ValueError) as error:
        raise PushError(f"cannot validate {label} closure: {error}") from error


def _require_commit_tip(closure, object_id: str, ref_name: str) -> None:
    for item in closure:
        if item.object_id == object_id:
            if item.object_type != "commit":
                raise PushError(
                    f"branch {ref_name} does not name a commit object"
                )
            return
    raise PushError(f"branch {ref_name} is missing its tip object")
