"""Bounded local reachability traversal and fetch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from commitverse_core.commits import CommitError, parse_commit
from commitverse_core.objects import (
    ObjectResourceLimitError,
    read_object_bounded,
    write_object,
)
from commitverse_core.refs import (
    ReferenceError,
    ReferenceNotFoundError,
    compare_and_swap_ref,
    read_ref,
    validate_ref_name,
)
from commitverse_core.repository import Repository
from commitverse_core.transport import (
    LocalFilesystemTransport,
    RemoteAdvertisement,
    RemoteReference,
    TransportError,
)
from commitverse_core.trees import TreeError, parse_tree


@dataclass(frozen=True)
class TransferLimits:
    """Resource limits applied while reading and transferring a closure."""

    max_decompressed_object_size: int = 64 * 1024 * 1024
    max_compressed_object_size: int = 64 * 1024 * 1024
    max_total_decompressed_transfer: int = 1024 * 1024 * 1024
    max_objects_per_transfer: int = 1_000_000
    max_commit_traversal: int = 1_000_000


class FetchError(ValueError):
    """Raised when a fetch cannot validate or transfer its selected closure."""


@dataclass(frozen=True)
class FetchReferenceResult:
    """Publication result for one selected remote reference."""

    source_ref: str
    destination_ref: str
    object_id: str
    status: str
    error: str | None = None
    published: bool = False


@dataclass(frozen=True)
class FetchResult:
    """Fetch result with deterministic per-reference publication results."""

    references: tuple[FetchReferenceResult, ...]
    objects_transferred: int


@dataclass(frozen=True)
class _ReachableObject:
    object_id: str
    object_type: str
    payload: bytes
    compressed_size: int


def fetch_from_local(
    destination: Repository,
    remote_path: Path | str,
    *,
    base: Path | str | None = None,
    branches: Sequence[str] | None = None,
    all_branches: bool = False,
    remote_name: str = "origin",
    ref_mapping: Mapping[str, str] | None = None,
    limits: TransferLimits | None = None,
) -> FetchResult:
    """Fetch selected local branch closures into remote-tracking refs."""
    selected_limits = limits or TransferLimits()
    _validate_limits(selected_limits)
    try:
        advertisement = LocalFilesystemTransport.open(remote_path, base=base).advertise()
        selected = _select_references(
            advertisement,
            branches=branches,
            all_branches=all_branches,
            remote_name=remote_name,
            ref_mapping=ref_mapping,
        )
        closure = _reachable_objects(advertisement.repository, selected, selected_limits)
        missing: list[_ReachableObject] = []
        for item in closure:
            if _destination_object_exists(destination, item.object_id, selected_limits):
                continue
            object_path = destination.objects_dir / item.object_id[:2] / item.object_id[2:]
            if object_path.exists():
                raise FetchError(
                    f"existing local object is malformed: {item.object_id}"
                )
            missing.append(item)
        total = sum(_canonical_size(item.object_type, item.payload) for item in missing)
        if total > selected_limits.max_total_decompressed_transfer:
            raise FetchError(
                f"transfer exceeds {selected_limits.max_total_decompressed_transfer} "
                "decompressed bytes"
            )
        for item in missing:
            write_object(destination.objects_dir, item.object_type, item.payload)
        publication = _publish_refs(destination, selected)
        if any(result.status == "failed" for result in publication):
            return FetchResult(publication, len(missing))
        return FetchResult(
            tuple(
                FetchReferenceResult(
                    source_ref=source_ref,
                    destination_ref=destination_ref,
                    object_id=object_id,
                    status="updated",
                    published=True,
                )
                for source_ref, destination_ref, object_id in selected
            ),
            len(missing),
        )
    except FetchError:
        raise
    except TransportError as error:
        raise FetchError(f"fetch failed: {error}") from error
    except (OSError, ValueError, ReferenceError) as error:
        raise FetchError(f"fetch failed: {error}") from error


def _select_references(
    advertisement: RemoteAdvertisement,
    *,
    branches: Sequence[str] | None,
    all_branches: bool,
    remote_name: str,
    ref_mapping: Mapping[str, str] | None,
) -> tuple[tuple[str, str, str], ...]:
    if not remote_name or "/" in remote_name or remote_name in {".", ".."}:
        raise FetchError(f"invalid remote name: {remote_name!r}")
    advertised = {reference.name: reference for reference in advertisement.branches}
    if all_branches and branches:
        raise FetchError("choose either selected branches or all branches")
    if all_branches:
        source_names = sorted(advertised)
    elif branches is None:
        source_names = []
    else:
        source_names = [
            name if name.startswith("refs/") else f"refs/heads/{name}"
            for name in branches
        ]
    mapping = dict(ref_mapping or {})
    if mapping:
        source_names = sorted(mapping)
    selected: list[tuple[str, str, str]] = []
    for source_name in source_names:
        reference = advertised.get(source_name)
        if reference is None:
            raise FetchError(f"remote branch is not advertised: {source_name}")
        destination_name = mapping.get(
            source_name,
            f"refs/remotes/{remote_name}/{source_name.removeprefix('refs/heads/')}",
        )
        validate_ref_name(destination_name)
        selected.append((source_name, destination_name, reference.object_id))
    return tuple(selected)


def _reachable_objects(
    remote: Repository,
    selected: Sequence[tuple[str, str, str]],
    limits: TransferLimits,
) -> tuple[_ReachableObject, ...]:
    state: dict[str, int] = {}
    objects: dict[str, _ReachableObject] = {}
    commits = 0
    stack = [(object_id, False, None) for _, _, object_id in reversed(selected)]
    while stack:
        object_id, exiting, expected_type = stack.pop()
        if exiting:
            state[object_id] = 2
            continue
        if state.get(object_id) == 1:
            raise FetchError(f"cycle detected in reachable object graph at {object_id}")
        if state.get(object_id) == 2:
            if expected_type is not None and objects[object_id].object_type != expected_type:
                raise FetchError(
                    f"object {object_id} is {objects[object_id].object_type}, "
                    f"expected {expected_type}"
                )
            continue
        state[object_id] = 1
        try:
            object_type, payload, compressed_size = read_object_bounded(
                remote.objects_dir,
                object_id,
                max_compressed_size=limits.max_compressed_object_size,
                max_decompressed_size=limits.max_decompressed_object_size,
            )
        except (OSError, ValueError, ObjectResourceLimitError) as error:
            raise FetchError(f"cannot read remote object {object_id}: {error}") from error
        if expected_type is not None and object_type != expected_type:
            raise FetchError(
                f"object {object_id} is {object_type}, expected {expected_type}"
            )
        item = _ReachableObject(object_id, object_type, payload, compressed_size)
        objects[object_id] = item
        if len(objects) > limits.max_objects_per_transfer:
            raise FetchError("object transfer count limit exceeded")
        stack.append((object_id, True, None))
        children: list[tuple[str, str | None]] = []
        if object_type == "commit":
            commits += 1
            if commits > limits.max_commit_traversal:
                raise FetchError("commit traversal limit exceeded")
            try:
                commit = parse_commit(payload)
            except (CommitError, ValueError) as error:
                raise FetchError(f"malformed commit {object_id}: {error}") from error
            children.append((commit.tree_id, "tree"))
            children.extend((parent_id, "commit") for parent_id in commit.parent_ids)
        elif object_type == "tree":
            try:
                entries = parse_tree(payload)
            except (TreeError, ValueError) as error:
                raise FetchError(f"malformed tree {object_id}: {error}") from error
            for entry in entries:
                children.append((entry.object_id, "tree" if entry.mode == "40000" else "blob"))
        elif object_type != "blob":
            raise FetchError(f"unsupported reachable object type: {object_type}")
        for child_id, child_type in reversed(children):
            if state.get(child_id) == 1:
                raise FetchError(f"cycle detected in reachable object graph at {child_id}")
            stack.append((child_id, False, child_type))
    return tuple(objects[object_id] for object_id in sorted(objects))


def _publish_refs(
    destination: Repository,
    selected: Sequence[tuple[str, str, str]],
) -> tuple[FetchReferenceResult, ...]:
    results: list[FetchReferenceResult] = []
    for source_ref, destination_ref, object_id in selected:
        try:
            try:
                expected = read_ref(destination, destination_ref)
            except ReferenceNotFoundError:
                expected = None
            compare_and_swap_ref(destination, destination_ref, expected, object_id)
        except ReferenceError as error:
            results.append(
                FetchReferenceResult(
                    source_ref,
                    destination_ref,
                    object_id,
                    "failed",
                    str(error),
                    getattr(error, "published", False),
                )
            )
            break
        results.append(
            FetchReferenceResult(source_ref, destination_ref, object_id, "updated", published=True)
        )
    return tuple(results)


def _destination_object_exists(
    repository: Repository, object_id: str, limits: TransferLimits
) -> bool:
    try:
        read_object_bounded(
            repository.objects_dir,
            object_id,
            max_compressed_size=limits.max_compressed_object_size,
            max_decompressed_size=limits.max_decompressed_object_size,
        )
    except (OSError, ValueError, ObjectResourceLimitError):
        return False
    return True


def _canonical_size(object_type: str, payload: bytes) -> int:
    return len(object_type.encode("ascii")) + 1 + len(str(len(payload))) + len(payload) + 1


def _validate_limits(limits: TransferLimits) -> None:
    if any(value < 0 for value in (
        limits.max_decompressed_object_size,
        limits.max_compressed_object_size,
        limits.max_total_decompressed_transfer,
        limits.max_objects_per_transfer,
        limits.max_commit_traversal,
    )):
        raise FetchError("transfer limits must be nonnegative")
