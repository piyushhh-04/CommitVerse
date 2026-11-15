"""Authorized, bounded repository browsing endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from commitverse_hub.api.v1.auth import get_optional_authenticated_user
from commitverse_hub.config.settings import Settings
from commitverse_hub.db.models import User
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.repositories.browse import (
    BrowseError,
    BrowseLimitError,
    BrowseNotFoundError,
    browse_commit,
    browse_diff,
    browse_blob,
    browse_history,
    browse_refs,
    browse_tree,
)
from commitverse_hub.repositories.service import (
    RepositoryNotFoundError,
    RepositoryOperationError,
    get_repository_for_access,
    get_public_repository_for_access,
)

router = APIRouter(prefix="/repositories", tags=["repository-browse"])


class TreeEntryResponse(BaseModel):
    name: str
    type: str
    mode: str
    object_id: str

    model_config = ConfigDict(from_attributes=True)


class TreeResponse(BaseModel):
    repository_id: uuid.UUID
    commit_id: str | None
    path: str
    entries: list[TreeEntryResponse]


class BlobResponse(BaseModel):
    repository_id: uuid.UUID
    commit_id: str
    path: str
    object_id: str
    size: int
    is_binary: bool
    content: str | None


class CommitResponse(BaseModel):
    object_id: str
    parent_ids: list[str]
    author_name: str
    author_email: str
    author_timestamp: int
    message: str


class CommitListResponse(BaseModel):
    repository_id: uuid.UUID
    commits: list[CommitResponse]
    limit: int
    truncated: bool


class CommitDetailResponse(BaseModel):
    repository_id: uuid.UUID
    object_id: str
    tree_id: str
    parent_ids: list[str]
    author_name: str
    author_email: str
    author_timestamp: int
    author_timezone_offset: int
    committer_name: str
    committer_email: str
    committer_timestamp: int
    committer_timezone_offset: int
    message: str


class DiffFileResponse(BaseModel):
    path: str
    status: str
    old_object_id: str | None
    new_object_id: str | None
    is_binary: bool
    patch: str | None


class DiffResponse(BaseModel):
    repository_id: uuid.UUID
    base_commit_id: str | None
    head_commit_id: str
    files: list[DiffFileResponse]


class RefResponse(BaseModel):
    name: str
    ref: str
    object_id: str | None
    kind: str
    current: bool


class RefListResponse(BaseModel):
    repository_id: uuid.UUID
    refs: list[RefResponse]


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _repository_path(request: Request, storage_key: str):
    return _settings(request).repository_storage_root / f"{storage_key}.git"


def _browse_error(exc: Exception) -> HubApplicationError:
    if isinstance(exc, BrowseNotFoundError):
        return HubApplicationError(404, "repository_path_not_found", str(exc))
    if isinstance(exc, BrowseLimitError):
        return HubApplicationError(413, "repository_browse_limit", str(exc))
    if isinstance(exc, BrowseError):
        return HubApplicationError(503, "repository_browse_unavailable", str(exc))
    if isinstance(exc, RepositoryNotFoundError):
        return HubApplicationError(404, "repository_not_found", "Repository not found.")
    if isinstance(exc, RepositoryOperationError):
        return HubApplicationError(503, "repository_unavailable", str(exc))
    raise TypeError("Unsupported repository browse exception.")


def _authorized_repository(request: Request, repository_id: uuid.UUID, user: User | None):
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(
            503,
            "database_unavailable",
            "The Hub database is not configured.",
        )
    try:
        if user is None:
            return get_public_repository_for_access(factory, repository_id)
        return get_repository_for_access(factory, repository_id, user.id)
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise _browse_error(exc) from exc


@router.get("/{repository_id}/tree", response_model=TreeResponse)
def read_tree(
    repository_id: uuid.UUID,
    request: Request,
    path: Annotated[str, Query(max_length=4096)] = "",
    ref: Annotated[str, Query(max_length=4096)] = "HEAD",
    user: User | None = Depends(get_optional_authenticated_user),
) -> TreeResponse:
    repository = _authorized_repository(request, repository_id, user)
    try:
        result = browse_tree(_repository_path(request, repository.storage_key), path, ref)
    except (BrowseError, BrowseLimitError) as exc:
        raise _browse_error(exc) from exc
    return TreeResponse(
        repository_id=repository_id,
        commit_id=result.commit_id,
        path=result.path,
        entries=[
            TreeEntryResponse(
                name=entry.name,
                type=entry.entry_type,
                mode=entry.mode,
                object_id=entry.object_id,
            )
            for entry in result.entries
        ],
    )


@router.get("/{repository_id}/blob", response_model=BlobResponse)
def read_blob(
    repository_id: uuid.UUID,
    request: Request,
    path: Annotated[str, Query(min_length=1, max_length=4096)],
    ref: Annotated[str, Query(max_length=4096)] = "HEAD",
    user: User | None = Depends(get_optional_authenticated_user),
) -> BlobResponse:
    repository = _authorized_repository(request, repository_id, user)
    try:
        result = browse_blob(_repository_path(request, repository.storage_key), path, ref)
    except (BrowseError, BrowseLimitError) as exc:
        raise _browse_error(exc) from exc
    return BlobResponse(
        repository_id=repository_id,
        commit_id=result.commit_id,
        path=result.path,
        object_id=result.object_id,
        size=result.size,
        is_binary=result.is_binary,
        content=result.content,
    )


@router.get("/{repository_id}/commits", response_model=CommitListResponse)
def read_commits(
    repository_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ref: Annotated[str, Query(max_length=4096)] = "HEAD",
    user: User | None = Depends(get_optional_authenticated_user),
) -> CommitListResponse:
    repository = _authorized_repository(request, repository_id, user)
    try:
        commits = browse_history(_repository_path(request, repository.storage_key), limit, ref)
    except (BrowseError, BrowseLimitError) as exc:
        raise _browse_error(exc) from exc
    return CommitListResponse(
        repository_id=repository_id,
        commits=[
            CommitResponse(
                object_id=commit.object_id,
                parent_ids=list(commit.parent_ids),
                author_name=commit.author_name,
                author_email=commit.author_email,
                author_timestamp=commit.author_timestamp,
                message=commit.message,
            )
            for commit in commits
        ],
        limit=limit,
        truncated=len(commits) == limit,
    )


@router.get("/{repository_id}/commits/{commit_id}", response_model=CommitDetailResponse)
def read_commit_detail(
    repository_id: uuid.UUID,
    commit_id: str,
    request: Request,
    ref: Annotated[str, Query(max_length=4096)] = "HEAD",
    user: User | None = Depends(get_optional_authenticated_user),
) -> CommitDetailResponse:
    repository = _authorized_repository(request, repository_id, user)
    try:
        result = browse_commit(
            _repository_path(request, repository.storage_key), commit_id, ref
        )
    except (BrowseError, BrowseLimitError) as exc:
        raise _browse_error(exc) from exc
    return CommitDetailResponse(
        repository_id=repository_id,
        object_id=result.object_id,
        tree_id=result.tree_id,
        parent_ids=list(result.parent_ids),
        author_name=result.author_name,
        author_email=result.author_email,
        author_timestamp=result.author_timestamp,
        author_timezone_offset=result.author_timezone_offset,
        committer_name=result.committer_name,
        committer_email=result.committer_email,
        committer_timestamp=result.committer_timestamp,
        committer_timezone_offset=result.committer_timezone_offset,
        message=result.message,
    )


@router.get("/{repository_id}/commits/{commit_id}/diff", response_model=DiffResponse)
def read_commit_diff(
    repository_id: uuid.UUID,
    commit_id: str,
    request: Request,
    ref: Annotated[str, Query(max_length=4096)] = "HEAD",
    user: User | None = Depends(get_optional_authenticated_user),
) -> DiffResponse:
    repository = _authorized_repository(request, repository_id, user)
    try:
        result = browse_diff(
            _repository_path(request, repository.storage_key), commit_id, ref
        )
    except (BrowseError, BrowseLimitError) as exc:
        raise _browse_error(exc) from exc
    return DiffResponse(
        repository_id=repository_id,
        base_commit_id=result.base_commit_id,
        head_commit_id=result.head_commit_id,
        files=[DiffFileResponse.model_validate(item, from_attributes=True) for item in result.files],
    )


@router.get("/{repository_id}/refs", response_model=RefListResponse)
def read_refs(
    repository_id: uuid.UUID,
    request: Request,
    user: User | None = Depends(get_optional_authenticated_user),
) -> RefListResponse:
    repository = _authorized_repository(request, repository_id, user)
    try:
        refs = browse_refs(_repository_path(request, repository.storage_key))
    except (BrowseError, BrowseLimitError) as exc:
        raise _browse_error(exc) from exc
    return RefListResponse(
        repository_id=repository_id,
        refs=[RefResponse.model_validate(item, from_attributes=True) for item in refs],
    )
