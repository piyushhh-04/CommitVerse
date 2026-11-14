"""Organization and membership API routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.api.v1.auth import get_authenticated_user, require_authenticated_csrf
from commitverse_hub.db.models import Organization, OrganizationMembership, User
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.organizations import (
    OrganizationConflictError,
    OrganizationDisabledError,
    OrganizationNotFoundError,
    OrganizationOperationError,
    OrganizationPermissionError,
    OrganizationReauthenticationError,
    OrganizationValidationError,
    add_organization_member,
    change_organization_member_role,
    create_organization,
    get_organization_for_member,
    leave_organization,
    list_organization_members,
    list_user_organizations,
    remove_organization_member,
    transfer_organization_ownership,
    update_organization,
)
from commitverse_hub.organizations.policy import (
    normalize_organization_name,
    normalize_organization_slug,
    validate_member_role,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


class OrganizationCreateRequest(BaseModel):
    """Fields accepted when creating an organization."""

    slug: str = Field(..., min_length=1, max_length=63)
    name: str = Field(..., min_length=1, max_length=120)

    model_config = ConfigDict(extra="forbid")

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return normalize_organization_slug(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_organization_name(value)


class OrganizationUpdateRequest(BaseModel):
    """Allow-listed organization metadata updates."""

    slug: str | None = Field(default=None, min_length=1, max_length=63)
    name: str | None = Field(default=None, min_length=1, max_length=120)

    model_config = ConfigDict(extra="forbid")

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_organization_slug(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_organization_name(value)

    @model_validator(mode="after")
    def validate_changes(self) -> OrganizationUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one organization field is required.")
        if "slug" in self.model_fields_set and self.slug is None:
            raise ValueError("Organization slug cannot be null.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Organization name cannot be null.")
        return self


class MembershipCreateRequest(BaseModel):
    """Fields accepted when adding a member to an organization."""

    user_id: uuid.UUID
    role: Literal["admin", "member"] = "member"

    model_config = ConfigDict(extra="forbid")

    @field_validator("role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        return validate_member_role(value)


class MembershipRoleUpdateRequest(BaseModel):
    """Fields accepted when changing an existing member role."""

    role: Literal["admin", "member"]

    model_config = ConfigDict(extra="forbid")

    @field_validator("role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        return validate_member_role(value)


class OwnershipTransferRequest(BaseModel):
    """Fields accepted when transferring organization ownership."""

    target_user_id: uuid.UUID
    current_password: str = Field(..., min_length=1, max_length=1024)

    model_config = ConfigDict(extra="forbid")


class OrganizationResponse(BaseModel):
    """Public organization metadata returned to members."""

    id: uuid.UUID
    slug: str
    name: str
    state: str
    role: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_organization(
        cls,
        organization: Organization,
        *,
        role: str | None = None,
    ) -> OrganizationResponse:
        return cls(
            id=organization.id,
            slug=organization.slug,
            name=organization.name,
            state=organization.state,
            role=role,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )


class OrganizationListResponse(BaseModel):
    """Paginated organization listing."""

    items: list[OrganizationResponse]
    total: int
    limit: int
    offset: int


class MembershipResponse(BaseModel):
    """Minimal public membership metadata."""

    user_id: uuid.UUID
    role: str
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_membership(cls, membership: OrganizationMembership) -> MembershipResponse:
        return cls(
            user_id=membership.user_id,
            role=membership.role,
            joined_at=membership.joined_at,
        )


class MembershipListResponse(BaseModel):
    """Paginated membership listing."""

    items: list[MembershipResponse]
    total: int
    limit: int
    offset: int


class StatusResponse(BaseModel):
    """Generic success payload for lifecycle operations."""

    status: str = "ok"


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(
            503,
            "database_unavailable",
            "The Hub database is not configured.",
        )
    return factory


def _organization_error(exc: Exception) -> HubApplicationError:
    if isinstance(exc, OrganizationDisabledError):
        return HubApplicationError(409, "organization_disabled", "Organization is disabled.")
    if isinstance(exc, OrganizationConflictError):
        return HubApplicationError(409, "organization_conflict", str(exc))
    if isinstance(exc, OrganizationNotFoundError):
        return HubApplicationError(404, "organization_not_found", "Organization not found.")
    if isinstance(exc, OrganizationReauthenticationError):
        return HubApplicationError(
            401,
            "reauthentication_failed",
            str(exc),
        )
    if isinstance(exc, OrganizationPermissionError):
        return HubApplicationError(
            403,
            "organization_permission_denied",
            str(exc),
        )
    if isinstance(exc, OrganizationValidationError):
        return HubApplicationError(422, "validation_error", str(exc))
    if isinstance(exc, OrganizationOperationError):
        return HubApplicationError(503, "organization_unavailable", str(exc))
    if isinstance(exc, ValueError):
        return HubApplicationError(422, "validation_error", str(exc))
    raise TypeError("Unsupported organization exception.")


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization_route(
    payload: OrganizationCreateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> OrganizationResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        organization = create_organization(
            factory,
            user.id,
            slug=payload.slug,
            name=payload.name,
            request_id=getattr(request.state, "request_id", None),
        )
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return OrganizationResponse.from_organization(organization, role="owner")


@router.get("", response_model=OrganizationListResponse)
def list_organizations_route(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: User = Depends(get_authenticated_user),
) -> OrganizationListResponse:
    factory = _session_factory(request)
    try:
        rows, total = list_user_organizations(
            factory,
            user.id,
            limit=limit,
            offset=offset,
        )
    except (OrganizationOperationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return OrganizationListResponse(
        items=[
            OrganizationResponse.from_organization(organization, role=role)
            for organization, role in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization_route(
    organization_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> OrganizationResponse:
    factory = _session_factory(request)
    try:
        organization, role = get_organization_for_member(factory, organization_id, user.id)
    except (OrganizationNotFoundError, OrganizationOperationError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return OrganizationResponse.from_organization(organization, role=role)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def patch_organization_route(
    organization_id: uuid.UUID,
    payload: OrganizationUpdateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> OrganizationResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        organization = update_organization(
            factory,
            organization_id,
            user.id,
            slug=payload.slug,
            name=payload.name,
            request_id=getattr(request.state, "request_id", None),
        )
        organization, role = get_organization_for_member(factory, organization_id, user.id)
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return OrganizationResponse.from_organization(organization, role=role)


@router.get("/{organization_id}/members", response_model=MembershipListResponse)
def list_members_route(
    organization_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user: User = Depends(get_authenticated_user),
) -> MembershipListResponse:
    factory = _session_factory(request)
    try:
        memberships, total = list_organization_members(
            factory,
            organization_id,
            user.id,
            limit=limit,
            offset=offset,
        )
    except (OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return MembershipListResponse(
        items=[MembershipResponse.from_membership(membership) for membership in memberships],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{organization_id}/members", response_model=MembershipResponse)
def add_member_route(
    organization_id: uuid.UUID,
    payload: MembershipCreateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> MembershipResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        membership = add_organization_member(
            factory,
            organization_id,
            user.id,
            payload.user_id,
            role=payload.role,
            request_id=getattr(request.state, "request_id", None),
        )
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return MembershipResponse.from_membership(membership)


@router.patch("/{organization_id}/members/{user_id}", response_model=MembershipResponse)
def change_member_role_route(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MembershipRoleUpdateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> MembershipResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        membership = change_organization_member_role(
            factory,
            organization_id,
            user.id,
            user_id,
            role=payload.role,
            request_id=getattr(request.state, "request_id", None),
        )
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return MembershipResponse.from_membership(membership)


@router.delete("/{organization_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member_route(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> Response:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        remove_organization_member(
            factory,
            organization_id,
            user.id,
            user_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{organization_id}/leave", response_model=StatusResponse)
def leave_organization_route(
    organization_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> StatusResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        leave_organization(
            factory,
            organization_id,
            user.id,
            request_id=getattr(request.state, "request_id", None),
        )
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return StatusResponse(status="ok")


@router.post("/{organization_id}/transfer-ownership", response_model=StatusResponse)
def transfer_ownership_route(
    organization_id: uuid.UUID,
    payload: OwnershipTransferRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> StatusResponse:
    require_authenticated_csrf(request)
    factory = _session_factory(request)
    try:
        transfer_organization_ownership(
            factory,
            organization_id,
            user.id,
            payload.target_user_id,
            current_password=payload.current_password,
            request_id=getattr(request.state, "request_id", None),
        )
    except (OrganizationConflictError, OrganizationDisabledError, OrganizationNotFoundError, OrganizationOperationError, OrganizationPermissionError, OrganizationReauthenticationError, OrganizationValidationError, ValueError) as exc:
        raise _organization_error(exc) from exc
    return StatusResponse(status="ok")
