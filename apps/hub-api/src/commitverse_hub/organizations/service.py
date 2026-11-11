"""Transactional organization metadata operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.db.models import (
    AuditEvent,
    Organization,
    OrganizationMembership,
    User,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.organizations.policy import (
    OrganizationConflictError,
    OrganizationDisabledError,
    OrganizationNotFoundError,
    OrganizationOperationError,
    OrganizationPermissionError,
    OrganizationValidationError,
    normalize_organization_name,
    normalize_organization_slug,
)


def create_organization(
    factory: sessionmaker[Session],
    creator_user_id: uuid.UUID,
    *,
    slug: str,
    name: str,
    request_id: str | None,
) -> Organization:
    """Create organization metadata and the creator's owner membership atomically."""
    normalized_slug = normalize_organization_slug(slug)
    normalized_name = normalize_organization_name(name)
    organization_id = uuid.uuid4()
    try:
        with transactional_session(factory) as db_session:
            creator = db_session.get(User, creator_user_id)
            if creator is None or creator.account_state != "active":
                raise OrganizationNotFoundError("Active user not found.")
            if db_session.scalar(
                select(Organization.id).where(
                    func.lower(Organization.slug) == normalized_slug
                )
            ) is not None:
                raise OrganizationConflictError("Organization slug is already in use.")

            organization = Organization(
                id=organization_id,
                slug=normalized_slug,
                name=normalized_name,
                created_by=creator_user_id,
                state="active",
            )
            db_session.add(organization)
            db_session.add(
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=creator_user_id,
                    role="owner",
                )
            )
            db_session.flush()
            _ensure_eligible_owner(db_session, organization_id)
            db_session.add(
                _audit_event(
                    creator_user_id,
                    "organization.created",
                    organization_id,
                    request_id,
                    {"slug": normalized_slug},
                )
            )
    except (OrganizationConflictError, OrganizationNotFoundError):
        raise
    except IntegrityError as exc:
        raise OrganizationConflictError("Organization slug is already in use.") from exc
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization could not be created.") from exc
    return _load_organization(factory, organization_id)


def list_user_organizations(
    factory: sessionmaker[Session],
    user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Organization, str]], int]:
    """List organizations for which the user has a membership, including disabled."""
    try:
        with factory() as db_session:
            filters = OrganizationMembership.user_id == user_id
            total = db_session.scalar(
                select(func.count())
                .select_from(Organization)
                .join(OrganizationMembership)
                .where(filters)
            )
            rows = db_session.execute(
                select(Organization, OrganizationMembership.role)
                .join(OrganizationMembership)
                .where(filters)
                .order_by(Organization.created_at.desc(), Organization.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [(organization, role) for organization, role in rows], int(total or 0)
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organizations could not be listed.") from exc


def get_organization_for_member(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[Organization, str]:
    """Return organization metadata and caller role, scoped to existing membership."""
    try:
        with factory() as db_session:
            row = db_session.execute(
                select(Organization, OrganizationMembership.role)
                .join(OrganizationMembership)
                .where(
                    Organization.id == organization_id,
                    OrganizationMembership.user_id == user_id,
                )
            ).one_or_none()
            if row is None:
                raise OrganizationNotFoundError("Organization not found.")
            return row[0], row[1]
    except OrganizationNotFoundError:
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization could not be loaded.") from exc


def update_organization(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    slug: str | None,
    name: str | None,
    request_id: str | None,
) -> Organization:
    """Update organization metadata for an owner or admin and audit atomically."""
    normalized_slug = normalize_organization_slug(slug) if slug is not None else None
    normalized_name = normalize_organization_name(name) if name is not None else None
    if normalized_slug is None and normalized_name is None:
        raise OrganizationValidationError("At least one organization field is required.")

    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(db_session, organization_id, [actor_user_id])
            actor_membership = memberships.get(actor_user_id)
            if actor_membership is None:
                raise OrganizationNotFoundError("Organization not found.")
            if actor_membership.role not in {"owner", "admin"}:
                raise OrganizationPermissionError(
                    "Organization metadata update is not permitted."
                )

            changed_fields: list[str] = []
            if normalized_slug is not None and organization.slug != normalized_slug:
                organization.slug = normalized_slug
                changed_fields.append("slug")
            if normalized_name is not None and organization.name != normalized_name:
                organization.name = normalized_name
                changed_fields.append("name")
            if changed_fields:
                db_session.flush()
                db_session.add(
                    _audit_event(
                        actor_user_id,
                        "organization.updated",
                        organization_id,
                        request_id,
                        {"changed_fields": changed_fields},
                    )
                )
    except (
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
    ):
        raise
    except IntegrityError as exc:
        raise OrganizationConflictError("Organization slug is already in use.") from exc
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization could not be updated.") from exc
    return _load_organization(factory, organization_id)


def _lock_organization(
    db_session: Session,
    organization_id: uuid.UUID,
) -> Organization:
    organization = db_session.scalar(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    )
    if organization is None:
        raise OrganizationNotFoundError("Organization not found.")
    return organization


def _lock_memberships(
    db_session: Session,
    organization_id: uuid.UUID,
    user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, OrganizationMembership]:
    if not user_ids:
        return {}
    memberships = db_session.scalars(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id.in_(set(user_ids)),
        )
        .order_by(OrganizationMembership.user_id)
        .with_for_update()
    )
    return {membership.user_id: membership for membership in memberships}


def _require_active_organization(organization: Organization) -> None:
    if organization.state != "active":
        raise OrganizationDisabledError("Organization is disabled.")


def _ensure_eligible_owner(db_session: Session, organization_id: uuid.UUID) -> None:
    eligible_owners = db_session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.role == "owner",
            User.account_state == "active",
        )
    )
    if not eligible_owners:
        raise OrganizationConflictError(
            "An organization must retain at least one active owner."
        )


def _audit_event(
    actor_user_id: uuid.UUID,
    action: str,
    organization_id: uuid.UUID,
    request_id: str | None,
    event_metadata: dict[str, object],
) -> AuditEvent:
    return AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        target_type="organization",
        target_id=str(organization_id),
        request_id=request_id,
        event_metadata=event_metadata,
    )


def _load_organization(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
) -> Organization:
    try:
        with factory() as db_session:
            organization = db_session.get(Organization, organization_id)
            if organization is None:
                raise OrganizationOperationError("Organization metadata is missing.")
            return organization
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization could not be loaded.") from exc
