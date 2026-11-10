"""Authenticated personal repository metadata and lifecycle endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.api.v1.auth import (
    get_authenticated_user,
    require_authenticated_csrf,
)
from commitverse_hub.config.settings import Settings
from commitverse_hub.db.models import Repository, User
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.repositories.service import (
    RepositoryConflictError,
    RepositoryNotFoundError,
    RepositoryOperationError,
    create_personal_repository,
    delete_personal_repository,
    get_personal_repository,
    list_personal_repositories,
    normalize_repository_name,
    update_personal_repository,
    validate_description,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryCreateRequest(BaseModel):
    """Fields accepted when creating a personal repository."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    visibility: Literal["public", "private"] = "private"

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_repository_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return validate_description(value)


class RepositoryUpdateRequest(BaseModel):
    """Allow-listed repository metadata updates; protected fields are forbidden."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    visibility: Literal["public", "private"] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else normalize_repository_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return validate_description(value)

    @model_validator(mode="after")
    def validate_changes(self) -> RepositoryUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one repository metadata field is required.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Repository name cannot be null.")
        if "visibility" in self.model_fields_set and self.visibility is None:
            raise ValueError("Repository visibility cannot be null.")
        return self


class RepositoryResponse(BaseModel):
    """Safe repository metadata without internal storage details."""

    id: uuid.UUID
    name: str
    description: str | None
    visibility: Literal["public", "private"]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_repository(cls, repository: Repository) -> RepositoryResponse:
        return cls(
            id=repository.id,
            name=repository.slug,
            description=repository.description,
            visibility=repository.visibility,
            created_at=repository.created_at,
            updated_at=repository.updated_at,
        )


class RepositoryListResponse(BaseModel):
    items: list[RepositoryResponse]
    total: int
    limit: int
    offset: int


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(
            503,
            "database_unavailable",
            "The Hub database is not configured.",
        )
    return factory


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _repository_error(exc: Exception) -> HubApplicationError:
    if isinstance(exc, RepositoryConflictError):
        return HubApplicationError(409, "repository_conflict", "Repository name is already in use.")
    if isinstance(exc, RepositoryNotFoundError):
        return HubApplicationError(404, "repository_not_found", "Repository not found.")
    if isinstance(exc, RepositoryOperationError):
        return HubApplicationError(503, "repository_unavailable", str(exc))
    if isinstance(exc, ValueError):
        return HubApplicationError(422, "validation_error", "Repository metadata is invalid.")
    raise TypeError("Unsupported repository exception.")


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository(
    payload: RepositoryCreateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        repository = create_personal_repository(
            factory,
            _settings(request).repository_storage_root,
            user.id,
            name=payload.name,
            description=payload.description,
            visibility=payload.visibility,
            request_id=getattr(request.state, "request_id", None),
        )
    except (RepositoryConflictError, RepositoryOperationError, ValueError) as exc:
        raise _repository_error(exc) from exc
    return RepositoryResponse.from_repository(repository)


@router.get("", response_model=RepositoryListResponse)
def list_repositories(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: User = Depends(get_authenticated_user),
) -> RepositoryListResponse:
    try:
        items, total = list_personal_repositories(
            _session_factory(request),
            user.id,
            limit=limit,
            offset=offset,
        )
    except RepositoryOperationError as exc:
        raise _repository_error(exc) from exc
    return RepositoryListResponse(
        items=[RepositoryResponse.from_repository(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{repository_id}", response_model=RepositoryResponse)
def get_repository(
    repository_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryResponse:
    try:
        repository = get_personal_repository(
            _session_factory(request),
            repository_id,
            user.id,
        )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise _repository_error(exc) from exc
    return RepositoryResponse.from_repository(repository)


@router.patch("/{repository_id}", response_model=RepositoryResponse)
def patch_repository(
    repository_id: uuid.UUID,
    payload: RepositoryUpdateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryResponse:
    require_authenticated_csrf(request)
    try:
        repository = update_personal_repository(
            _session_factory(request),
            repository_id,
            user.id,
            name=payload.name,
            description=payload.description,
            description_provided="description" in payload.model_fields_set,
            visibility=payload.visibility,
            request_id=getattr(request.state, "request_id", None),
        )
    except (
        RepositoryConflictError,
        RepositoryNotFoundError,
        RepositoryOperationError,
        ValueError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryResponse.from_repository(repository)


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repository(
    repository_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> Response:
    require_authenticated_csrf(request)
    try:
        delete_personal_repository(
            _session_factory(request),
            _settings(request).repository_storage_root,
            repository_id,
            user.id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise _repository_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
