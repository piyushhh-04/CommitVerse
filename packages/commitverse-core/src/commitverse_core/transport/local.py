"""Read-only local filesystem transport and remote advertisement."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from commitverse_core.objects import read_object
from commitverse_core.refs import (
    ReferenceError,
    ReferenceNotFoundError,
    read_head,
    read_ref,
    resolve_head,
    validate_ref_name,
)
from commitverse_core.repository import Repository, RepositoryError, discover_repository


class TransportError(ValueError):
    """Raised when a local remote cannot be opened or advertised."""


@dataclass(frozen=True)
class RemoteReference:
    """A validated advertised reference."""

    name: str
    object_id: str


@dataclass(frozen=True)
class RemoteAdvertisement:
    """Validated, read-only view of a remote repository's refs and HEAD."""

    repository: Repository
    branches: tuple[RemoteReference, ...]
    tags: tuple[RemoteReference, ...]
    head_symbolic_ref: str | None
    head_target: str | None

    @property
    def references(self) -> tuple[RemoteReference, ...]:
        """Return branch and tag references in deterministic order."""
        return self.branches + self.tags


class LocalFilesystemTransport:
    """Open and inspect a repository without modifying it."""

    def __init__(self, repository: Repository):
        self.repository = repository

    @classmethod
    def open(cls, path: Path | str, *, base: Path | str | None = None) -> "LocalFilesystemTransport":
        requested = Path(path).expanduser()
        if not requested.is_absolute():
            if base is None:
                raise TransportError(
                    "relative local remote paths require an explicit base directory"
                )
            requested = Path(base).expanduser() / requested
        try:
            requested = requested.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise TransportError(
                f"invalid local remote {path!s}: cannot access path: {error}"
            ) from error
        try:
            repository = discover_repository(requested)
        except (RepositoryError, ValueError) as error:
            raise TransportError(
                f"invalid local remote repository {requested}; repository metadata "
                f"including HEAD is invalid or missing: {error}"
            ) from error
        if repository.root != requested:
            raise TransportError(
                f"local remote path is not a repository root: {requested}"
            )
        return cls(repository)

    def advertise(self, *, allow_unresolved_head: bool = False) -> RemoteAdvertisement:
        """Validate and return the remote's loose refs and HEAD without writes."""
        packed_refs = self.repository.git_dir / "packed-refs"
        if packed_refs.exists():
            raise TransportError(
                "packed references are unsupported by local advertisement"
            )
        branches = self._advertise_namespace("heads", require_commit=True)
        tags = self._advertise_namespace("tags", require_commit=False)
        try:
            head = read_head(self.repository)
            head_target = resolve_head(self.repository)
        except ReferenceNotFoundError:
            if not allow_unresolved_head:
                raise
            head = read_head(self.repository)
            head_target = None
        except (ReferenceError, OSError, ValueError) as error:
            raise TransportError(f"invalid remote HEAD: {error}") from error
        return RemoteAdvertisement(
            repository=self.repository,
            branches=branches,
            tags=tags,
            head_symbolic_ref=head.symbolic_ref,
            head_target=head_target,
        )

    def _advertise_namespace(
        self, namespace: str, *, require_commit: bool
    ) -> tuple[RemoteReference, ...]:
        root = self.repository.refs_dir / namespace
        if not root.exists():
            return ()
        if root.is_symlink() or not root.is_dir():
            raise TransportError(f"invalid remote refs/{namespace} directory")
        references: list[RemoteReference] = []
        for path in _walk_ref_files(root):
            relative = path.relative_to(self.repository.git_dir).as_posix()
            if relative.endswith(".lock"):
                continue
            try:
                ref_name = validate_ref_name(relative)
                object_id = read_ref(self.repository, ref_name)
                object_type, _ = read_object(self.repository.objects_dir, object_id)
                if require_commit and object_type != "commit":
                    raise TransportError(
                        f"branch reference {ref_name} does not target a commit"
                    )
            except (ReferenceError, OSError, ValueError) as error:
                if isinstance(error, TransportError):
                    raise
                raise TransportError(f"invalid remote reference {relative}: {error}") from error
            references.append(RemoteReference(ref_name, object_id))
        return tuple(sorted(references, key=lambda reference: reference.name))


def _walk_ref_files(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            raise TransportError(f"cannot read remote refs directory {directory}: {error}") from error
        for entry in entries:
            try:
                metadata = entry.lstat()
            except OSError as error:
                raise TransportError(f"cannot inspect remote ref path {entry}: {error}") from error
            if stat.S_ISLNK(metadata.st_mode):
                raise TransportError(f"unsafe symbolic link in remote refs: {entry}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(entry)
            elif stat.S_ISREG(metadata.st_mode):
                result.append(entry)
            else:
                raise TransportError(f"unsupported remote ref entry: {entry}")
    return tuple(result)
