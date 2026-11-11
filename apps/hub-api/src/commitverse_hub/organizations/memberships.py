"""Transactional organization membership and ownership operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, sessionmaker

from commitverse_hub.auth.passwords import verify_password
from commitverse_hub.db.models import (
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
    OrganizationReauthenticationError,
    OrganizationValidationError,
    can_add_member,
    can_remove_member,
    validate_member_role,
)
from commitverse_hub.organizations.service import (
    _audit_event,
    _ensure_eligible_owner,
    _lock_memberships,
    _lock_organization,
    _require_active_organization,
)


def list_organization_members(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[OrganizationMembership], int]:
    """List the roster for any current organization member, including disabled orgs."""
    try:
        with factory() as db_session:
            _require_member(db_session, organization_id, actor_user_id)
            filters = OrganizationMembership.organization_id == organization_id
            total = db_session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(filters)
            )
            memberships = list(
                db_session.scalars(
                    select(OrganizationMembership)
                    .options(joinedload(OrganizationMembership.user))
                    .where(filters)
                    .order_by(
                        OrganizationMembership.joined_at,
                        OrganizationMembership.user_id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            return memberships, int(total or 0)
    except OrganizationNotFoundError:
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization members could not be listed.") from exc


def add_organization_member(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    role: str,
    request_id: str | None,
) -> OrganizationMembership:
    """Add an existing active user under the owner/admin add-member policy."""
    requested_role = validate_member_role(role)
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(
                db_session, organization_id, [actor_user_id, target_user_id]
            )
            actor_membership = _require_actor_membership(memberships, actor_user_id)
            if not can_add_member(actor_membership.role, requested_role):
                raise OrganizationPermissionError("Adding this member is not permitted.")
            if target_user_id in memberships:
                raise OrganizationConflictError("User is already an organization member.")
            target_user = db_session.get(User, target_user_id)
            if target_user is None or target_user.account_state != "active":
                raise OrganizationNotFoundError("Active user not found.")

            membership = OrganizationMembership(
                organization_id=organization_id,
                user_id=target_user_id,
                role=requested_role,
            )
            db_session.add(membership)
            db_session.flush()
            _ensure_eligible_owner(db_session, organization_id)
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "organization.member_added",
                    organization_id,
                    request_id,
                    {"user_id": str(target_user_id), "role": requested_role},
                )
            )
    except (
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
        OrganizationConflictError,
    ):
        raise
    except IntegrityError as exc:
        raise OrganizationConflictError("User is already an organization member.") from exc
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization member could not be added.") from exc
    return _load_membership(factory, organization_id, target_user_id)


def change_organization_member_role(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    role: str,
    request_id: str | None,
) -> OrganizationMembership:
    """Change a non-owner membership role; only owners may change roles."""
    new_role = validate_member_role(role)
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(
                db_session, organization_id, [actor_user_id, target_user_id]
            )
            actor_membership = _require_actor_membership(memberships, actor_user_id)
            if actor_membership.role != "owner":
                raise OrganizationPermissionError(
                    "Only an organization owner may change member roles."
                )
            target_membership = memberships.get(target_user_id)
            if target_membership is None:
                raise OrganizationNotFoundError("Organization member not found.")
            if target_membership.role == "owner":
                raise OrganizationConflictError(
                    "Ownership changes require the ownership transfer operation."
                )

            previous_role = target_membership.role
            target_membership.role = new_role
            db_session.flush()
            _ensure_eligible_owner(db_session, organization_id)
            if previous_role != new_role:
                db_session.add(
                    _audit_event(
                        actor_user_id,
                        "organization.member_role_changed",
                        organization_id,
                        request_id,
                        {
                            "user_id": str(target_user_id),
                            "old_role": previous_role,
                            "new_role": new_role,
                        },
                    )
                )
    except (
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
        OrganizationConflictError,
    ):
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization member role could not be changed.") from exc
    return _load_membership(factory, organization_id, target_user_id)


def remove_organization_member(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    request_id: str | None,
) -> None:
    """Remove a non-owner member or admin subject to the actor-role policy."""
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(
                db_session, organization_id, [actor_user_id, target_user_id]
            )
            actor_membership = _require_actor_membership(memberships, actor_user_id)
            target_membership = memberships.get(target_user_id)
            if target_membership is None:
                raise OrganizationNotFoundError("Organization member not found.")
            if not can_remove_member(actor_membership.role, target_membership.role):
                raise OrganizationPermissionError("Removing this member is not permitted.")

            previous_role = target_membership.role
            db_session.delete(target_membership)
            db_session.flush()
            _ensure_eligible_owner(db_session, organization_id)
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "organization.member_removed",
                    organization_id,
                    request_id,
                    {"user_id": str(target_user_id), "role": previous_role},
                )
            )
    except (
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
        OrganizationConflictError,
    ):
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization member could not be removed.") from exc


def leave_organization(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    request_id: str | None,
) -> None:
    """Remove the caller's membership unless that would leave no eligible owner."""
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(db_session, organization_id, [actor_user_id])
            actor_membership = _require_actor_membership(memberships, actor_user_id)
            previous_role = actor_membership.role
            db_session.delete(actor_membership)
            db_session.flush()
            _ensure_eligible_owner(db_session, organization_id)
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "organization.member_left",
                    organization_id,
                    request_id,
                    {"role": previous_role},
                )
            )
    except (
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationConflictError,
    ):
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization membership could not be left.") from exc


def transfer_organization_ownership(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    current_password: str,
    request_id: str | None,
) -> None:
    """Transfer ownership to an active member after current-password verification."""
    if actor_user_id == target_user_id:
        raise OrganizationValidationError("Ownership target must be another member.")
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(
                db_session, organization_id, [actor_user_id, target_user_id]
            )
            actor_membership = _require_actor_membership(memberships, actor_user_id)
            if actor_membership.role != "owner":
                raise OrganizationPermissionError(
                    "Only an organization owner may transfer ownership."
                )
            target_membership = memberships.get(target_user_id)
            if target_membership is None or target_membership.role == "owner":
                raise OrganizationNotFoundError("Eligible organization member not found.")
            actor_user = db_session.get(User, actor_user_id)
            target_user = db_session.get(User, target_user_id)
            if (
                actor_user is None
                or actor_user.account_state != "active"
                or not verify_password(actor_user.password_hash, current_password)
            ):
                raise OrganizationReauthenticationError(
                    "Current password could not be verified."
                )
            if target_user is None or target_user.account_state != "active":
                raise OrganizationNotFoundError("Eligible organization member not found.")

            target_membership.role = "owner"
            actor_membership.role = "admin"
            db_session.flush()
            _ensure_eligible_owner(db_session, organization_id)
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "organization.ownership_transferred",
                    organization_id,
                    request_id,
                    {
                        "previous_owner_user_id": str(actor_user_id),
                        "new_owner_user_id": str(target_user_id),
                    },
                )
            )
    except (
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
        OrganizationConflictError,
        OrganizationValidationError,
    ):
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization ownership could not be transferred.") from exc
    return None


def _require_member(
    db_session: Session,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership:
    organization = db_session.get(Organization, organization_id)
    if organization is None:
        raise OrganizationNotFoundError("Organization not found.")
    membership = db_session.get(
        OrganizationMembership,
        {"organization_id": organization_id, "user_id": user_id},
    )
    if membership is None:
        raise OrganizationNotFoundError("Organization not found.")
    return membership


def _require_actor_membership(
    memberships: dict[uuid.UUID, OrganizationMembership],
    actor_user_id: uuid.UUID,
) -> OrganizationMembership:
    membership = memberships.get(actor_user_id)
    if membership is None:
        raise OrganizationNotFoundError("Organization not found.")
    return membership


def _load_membership(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership:
    try:
        with factory() as db_session:
            membership = db_session.scalar(
                select(OrganizationMembership)
                .options(joinedload(OrganizationMembership.user))
                .where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == user_id,
                )
            )
            if membership is None:
                raise OrganizationOperationError("Organization membership is missing.")
            return membership
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization membership could not be loaded.") from exc
