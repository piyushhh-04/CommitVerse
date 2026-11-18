"""Authenticated personal repository metadata and lifecycle endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import select, or_, func
from sqlalchemy.exc import SQLAlchemyError

from commitverse_hub.api.v1.auth import (
    get_authenticated_user,
    require_authenticated_csrf,
)
from commitverse_hub.config.settings import Settings
from commitverse_hub.db.models import (
    AuditEvent,
    Invitation,
    OrganizationMembership,
    Repository,
    RepositoryUserPermission,
    User,
)
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.repositories.service import (
    RepositoryConflictError,
    RepositoryNotFoundError,
    RepositoryPermissionError,
    RepositoryOperationError,
    create_organization_repository,
    create_personal_repository,
    delete_organization_repository,
    delete_personal_repository,
    get_organization_repository,
    get_personal_repository,
    grant_repository_permission,
    list_organization_repositories,
    list_personal_repositories,
    list_repository_permissions,
    normalize_repository_name,
    revoke_repository_permission,
    update_repository_permission,
    update_organization_repository,
    update_personal_repository,
    validate_description,
)
from commitverse_hub.repositories.invitations import (
    accept_repository_invitation,
    create_repository_invitation,
    list_repository_invitations,
    revoke_repository_invitation,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])
organization_router = APIRouter(prefix="/organizations", tags=["organization-repositories"])


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


class RepositoryPermissionRequest(BaseModel):
    """Fields accepted when granting or changing a direct repository role."""

    user_id: uuid.UUID
    role: Literal["reader", "writer", "admin"]

    model_config = ConfigDict(extra="forbid")


class RepositoryPermissionUpdateRequest(BaseModel):
    """Fields accepted when changing a direct repository role."""

    role: Literal["reader", "writer", "admin"]

    model_config = ConfigDict(extra="forbid")


class RepositoryPermissionResponse(BaseModel):
    """Safe direct permission metadata without private user profile fields."""

    user_id: uuid.UUID
    role: Literal["reader", "writer", "admin"]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_permission(
        cls, permission: RepositoryUserPermission
    ) -> RepositoryPermissionResponse:
        return cls(
            user_id=permission.user_id,
            role=permission.role,
            created_at=permission.created_at,
            updated_at=permission.updated_at,
        )


class RepositoryInvitationCreateRequest(BaseModel):
    target_email: str = Field(..., min_length=3, max_length=320)
    role: Literal["reader", "writer", "admin"]
    expires_in_days: int = Field(default=7, ge=1, le=30)

    model_config = ConfigDict(extra="forbid")


class RepositoryInvitationResponse(BaseModel):
    id: uuid.UUID
    target_email: str
    role: Literal["reader", "writer", "admin"]
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("expires_at", "created_at")
    @classmethod
    def normalize_timestamps_to_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class RepositoryInvitationCreateResponse(RepositoryInvitationResponse):
    token: str


class RepositoryInvitationListResponse(BaseModel):
    items: list[RepositoryInvitationResponse]
    total: int
    limit: int
    offset: int


class RepositoryInvitationAcceptResponse(BaseModel):
    repository_id: uuid.UUID
    role: Literal["reader", "writer", "admin"]


class RepositorySearchResponse(BaseModel):
    items: list[RepositoryResponse]
    total: int


class ActivityResponse(BaseModel):
    id: uuid.UUID
    action: str
    target_type: str
    target_id: str
    occurred_at: datetime
    metadata: dict


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
    if isinstance(exc, RepositoryPermissionError):
        return HubApplicationError(403, "repository_permission_denied", str(exc))
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


@router.get("/search", response_model=RepositorySearchResponse)
def search_repositories(
    request: Request,
    query: Annotated[str, Query(min_length=1, max_length=100)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: User = Depends(get_authenticated_user),
) -> RepositorySearchResponse:
    factory = _session_factory(request)
    normalized = f"%{query.strip().lower()}%"
    try:
        with factory() as db:
            owned = select(Repository.id).where(
                Repository.owner_user_id == user.id,
                Repository.lifecycle_state != "deleted",
            )
            direct = select(RepositoryUserPermission.repository_id).where(
                RepositoryUserPermission.user_id == user.id,
            )
            org = select(Repository.owner_organization_id).join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Repository.owner_organization_id,
            ).where(
                OrganizationMembership.user_id == user.id,
                Repository.lifecycle_state != "deleted",
            )
            filters = (
                or_(
                    Repository.id.in_(owned),
                    Repository.id.in_(direct),
                    Repository.owner_organization_id.in_(org),
                    Repository.visibility == "public",
                ),
                or_(
                    func.lower(Repository.slug).contains(query.strip().lower()),
                    func.lower(func.coalesce(Repository.description, "")).contains(query.strip().lower()),
                ),
            )
            total = db.scalar(select(func.count()).select_from(Repository).where(*filters))
            items = list(db.scalars(
                select(Repository).where(*filters).order_by(Repository.updated_at.desc()).limit(limit).offset(offset)
            ))
            return RepositorySearchResponse(
                items=[RepositoryResponse.from_repository(item) for item in items],
                total=int(total or 0),
            )
    except SQLAlchemyError as exc:
        raise HubApplicationError(503, "repository_unavailable", "Repository search is unavailable.") from exc


@router.get("/activity", response_model=list[ActivityResponse])
def get_repository_activity(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_authenticated_user),
) -> list[ActivityResponse]:
    factory = _session_factory(request)
    try:
        with factory() as db:
            events = db.scalars(
                select(AuditEvent)
                .where(AuditEvent.actor_user_id == user.id)
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
                .limit(limit)
            )
            return [
                ActivityResponse(
                    id=event.id,
                    action=event.action,
                    target_type=event.target_type,
                    target_id=event.target_id,
                    occurred_at=event.occurred_at,
                    metadata=event.event_metadata,
                )
                for event in events
            ]
    except SQLAlchemyError as exc:
        raise HubApplicationError(503, "repository_unavailable", "Repository activity is unavailable.") from exc


@router.get(
    "/{repository_id}/permissions",
    response_model=list[RepositoryPermissionResponse],
)
def list_repository_permissions_route(
    repository_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> list[RepositoryPermissionResponse]:
    try:
        permissions = list_repository_permissions(
            _session_factory(request), repository_id, user.id
        )
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ) as exc:
        raise _repository_error(exc) from exc
    return [RepositoryPermissionResponse.from_permission(item) for item in permissions]


@router.post(
    "/{repository_id}/invitations",
    response_model=RepositoryInvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository_invitation_route(
    repository_id: uuid.UUID,
    payload: RepositoryInvitationCreateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryInvitationCreateResponse:
    require_authenticated_csrf(request)
    try:
        issued = create_repository_invitation(
            _session_factory(request),
            repository_id,
            user.id,
            target_email=payload.target_email,
            role=payload.role,
            expires_in_days=payload.expires_in_days,
            request_id=getattr(request.state, "request_id", None),
        )
    except RepositoryConflictError as exc:
        raise HubApplicationError(
            409,
            "repository_conflict",
            "Invitation conflicts with existing repository access or invitation.",
        ) from exc
    except ValueError as exc:
        raise HubApplicationError(
            422,
            "validation_error",
            "Repository invitation details are invalid.",
        ) from exc
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ) as exc:
        raise _repository_error(exc) from exc
    response = RepositoryInvitationResponse.model_validate(issued.invitation, from_attributes=True)
    return RepositoryInvitationCreateResponse(**response.model_dump(), token=issued.token)


@router.get("/{repository_id}/invitations", response_model=RepositoryInvitationListResponse)
def list_repository_invitations_route(
    repository_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: User = Depends(get_authenticated_user),
) -> RepositoryInvitationListResponse:
    try:
        items, total = list_repository_invitations(
            _session_factory(request), repository_id, user.id, limit=limit, offset=offset
        )
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError) as exc:
        raise _repository_error(exc) from exc
    return RepositoryInvitationListResponse(
        items=[RepositoryInvitationResponse.model_validate(item, from_attributes=True) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/{repository_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_repository_invitation_route(
    repository_id: uuid.UUID,
    invitation_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> Response:
    require_authenticated_csrf(request)
    try:
        revoke_repository_invitation(
            _session_factory(request), repository_id, user.id, invitation_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError) as exc:
        raise _repository_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invitations/{token}/accept",
    response_model=RepositoryInvitationAcceptResponse,
)
def accept_repository_invitation_route(
    token: str,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryInvitationAcceptResponse:
    require_authenticated_csrf(request)
    try:
        permission = accept_repository_invitation(
            _session_factory(request), token, user.id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (RepositoryConflictError, RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError) as exc:
        raise _repository_error(exc) from exc
    return RepositoryInvitationAcceptResponse(
        repository_id=permission.repository_id,
        role=permission.role,
    )


@router.post(
    "/{repository_id}/permissions",
    response_model=RepositoryPermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def grant_repository_permission_route(
    repository_id: uuid.UUID,
    payload: RepositoryPermissionRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryPermissionResponse:
    require_authenticated_csrf(request)
    try:
        permission = grant_repository_permission(
            _session_factory(request),
            repository_id,
            user.id,
            payload.user_id,
            role=payload.role,
            request_id=getattr(request.state, "request_id", None),
        )
    except (
        RepositoryConflictError,
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
        ValueError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryPermissionResponse.from_permission(permission)


@router.patch(
    "/{repository_id}/permissions/{target_user_id}",
    response_model=RepositoryPermissionResponse,
)
def update_repository_permission_route(
    repository_id: uuid.UUID,
    target_user_id: uuid.UUID,
    payload: RepositoryPermissionUpdateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryPermissionResponse:
    require_authenticated_csrf(request)
    try:
        permission = update_repository_permission(
            _session_factory(request),
            repository_id,
            user.id,
            target_user_id,
            role=payload.role,
            request_id=getattr(request.state, "request_id", None),
        )
    except (
        RepositoryConflictError,
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
        ValueError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryPermissionResponse.from_permission(permission)


@router.delete(
    "/{repository_id}/permissions/{target_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_repository_permission_route(
    repository_id: uuid.UUID,
    target_user_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> Response:
    require_authenticated_csrf(request)
    try:
        revoke_repository_permission(
            _session_factory(request),
            repository_id,
            user.id,
            target_user_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (
        RepositoryConflictError,
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ) as exc:
        raise _repository_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@organization_router.post(
    "/{organization_id}/repositories",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization_repository_route(
    organization_id: uuid.UUID,
    payload: RepositoryCreateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryResponse:
    require_authenticated_csrf(request)
    try:
        repository = create_organization_repository(
            _session_factory(request),
            _settings(request).repository_storage_root,
            organization_id,
            user.id,
            name=payload.name,
            description=payload.description,
            visibility=payload.visibility,
            request_id=getattr(request.state, "request_id", None),
        )
    except (
        RepositoryConflictError,
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
        ValueError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryResponse.from_repository(repository)


@organization_router.get(
    "/{organization_id}/repositories",
    response_model=RepositoryListResponse,
)
def list_organization_repositories_route(
    organization_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: User = Depends(get_authenticated_user),
) -> RepositoryListResponse:
    try:
        items, total = list_organization_repositories(
            _session_factory(request),
            organization_id,
            user.id,
            limit=limit,
            offset=offset,
        )
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryListResponse(
        items=[RepositoryResponse.from_repository(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@organization_router.get(
    "/{organization_id}/repositories/{repository_id}",
    response_model=RepositoryResponse,
)
def get_organization_repository_route(
    organization_id: uuid.UUID,
    repository_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryResponse:
    try:
        repository = get_organization_repository(
            _session_factory(request), repository_id, organization_id, user.id
        )
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryResponse.from_repository(repository)


@organization_router.patch(
    "/{organization_id}/repositories/{repository_id}",
    response_model=RepositoryResponse,
)
def patch_organization_repository_route(
    organization_id: uuid.UUID,
    repository_id: uuid.UUID,
    payload: RepositoryUpdateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> RepositoryResponse:
    require_authenticated_csrf(request)
    try:
        repository = update_organization_repository(
            _session_factory(request),
            repository_id,
            organization_id,
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
        RepositoryPermissionError,
        RepositoryOperationError,
        ValueError,
    ) as exc:
        raise _repository_error(exc) from exc
    return RepositoryResponse.from_repository(repository)


@organization_router.delete(
    "/{organization_id}/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_organization_repository_route(
    organization_id: uuid.UUID,
    repository_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> Response:
    require_authenticated_csrf(request)
    try:
        delete_organization_repository(
            _session_factory(request),
            _settings(request).repository_storage_root,
            repository_id,
            organization_id,
            user.id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ) as exc:
        raise _repository_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
