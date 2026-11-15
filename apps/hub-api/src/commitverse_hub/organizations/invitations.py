"""Scoped organization invitations with hashed, single-use tokens."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.auth.tokens import generate_session_token, hash_session_token, validate_session_token
from commitverse_hub.db.models import Invitation, OrganizationMembership, User
from commitverse_hub.db.session import transactional_session
from commitverse_hub.organizations.policy import (
    OrganizationConflictError,
    OrganizationDisabledError,
    OrganizationNotFoundError,
    OrganizationOperationError,
    OrganizationPermissionError,
    OrganizationValidationError,
)
from commitverse_hub.organizations.service import (
    _audit_event,
    _ensure_eligible_owner,
    _lock_memberships,
    _lock_organization,
    _lock_users,
    _require_active_actor,
    _require_active_organization,
)

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")
_MAX_EXPIRY_DAYS = 30


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: Invitation
    token: str


def _normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise OrganizationValidationError("Invitation email is invalid.")
    email = value.strip().lower()
    if not email or " " in email or not _EMAIL_PATTERN.fullmatch(email):
        raise OrganizationValidationError("Invitation email is invalid.")
    return email


def _validate_role(role: str) -> str:
    if role not in {"admin", "member"}:
        raise OrganizationValidationError("Invitation role is invalid.")
    return role


def create_organization_invitation(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    target_email: str,
    role: str,
    expires_in_days: int,
    request_id: str | None,
) -> IssuedInvitation:
    """Issue an organization invitation to an email address."""
    email = _normalize_email(target_email)
    requested_role = _validate_role(role)
    if not 1 <= expires_in_days <= _MAX_EXPIRY_DAYS:
        raise OrganizationValidationError("Invitation expiry must be between 1 and 30 days.")
    token = generate_session_token()
    now = datetime.now(UTC)
    invitation_id = uuid.uuid4()
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            memberships = _lock_memberships(db_session, organization_id, [actor_user_id])
            actor = _require_active_actor(db_session, actor_user_id)
            actor_membership = memberships.get(actor.id)
            if actor_membership is None or actor_membership.role not in {"owner", "admin"}:
                raise OrganizationPermissionError("Organization invitation is not permitted.")
            if actor_membership.role == "admin" and requested_role != "member":
                raise OrganizationPermissionError("Administrators may invite members only.")
            existing_member = db_session.scalar(
                select(User.id)
                .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                .where(
                    OrganizationMembership.organization_id == organization_id,
                    User.normalized_email == email,
                )
            )
            if existing_member is not None:
                raise OrganizationConflictError("The user is already an organization member.")
            invitation = Invitation(
                id=invitation_id,
                inviter_user_id=actor_user_id,
                target_email=email,
                organization_id=organization_id,
                role=requested_role,
                token_hash=hash_session_token(token),
                expires_at=now + timedelta(days=expires_in_days),
            )
            db_session.add(invitation)
            db_session.flush()
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "organization.invitation_created",
                    organization_id,
                    request_id,
                    {"invitation_id": str(invitation_id), "role": requested_role},
                )
            )
    except (
        OrganizationConflictError,
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
        OrganizationValidationError,
    ):
        raise
    except IntegrityError as exc:
        raise OrganizationConflictError("A pending invitation already exists for this email.") from exc
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization invitation could not be created.") from exc
    return IssuedInvitation(invitation, token)


def list_organization_invitations(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Invitation], int]:
    """List pending organization invitations for current managers without tokens."""
    try:
        with factory() as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            membership = db_session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == actor_user_id,
                )
            )
            if membership is None or membership.role not in {"owner", "admin"}:
                raise OrganizationNotFoundError("Organization not found.")
            filters = (
                Invitation.organization_id == organization_id,
                Invitation.status == "pending",
            )
            from sqlalchemy import func

            total = db_session.scalar(select(func.count()).select_from(Invitation).where(*filters))
            invitations = list(
                db_session.scalars(
                    select(Invitation)
                    .where(*filters)
                    .order_by(Invitation.created_at, Invitation.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            return invitations, int(total or 0)
    except OrganizationNotFoundError:
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization invitations could not be loaded.") from exc


def revoke_organization_invitation(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    invitation_id: uuid.UUID,
    *,
    request_id: str | None,
) -> None:
    """Revoke one pending organization invitation for an owner or administrator."""
    try:
        with transactional_session(factory) as db_session:
            organization = _lock_organization(db_session, organization_id)
            _require_active_organization(organization)
            membership = db_session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == actor_user_id,
                ).with_for_update()
            )
            if membership is None or membership.role not in {"owner", "admin"}:
                raise OrganizationNotFoundError("Organization not found.")
            invitation = db_session.scalar(
                select(Invitation).where(
                    Invitation.id == invitation_id,
                    Invitation.organization_id == organization_id,
                    Invitation.status == "pending",
                ).with_for_update()
            )
            if invitation is None:
                raise OrganizationNotFoundError("Invitation not found.")
            invitation.status = "revoked"
            invitation.revoked_at = datetime.now(UTC)
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "organization.invitation_revoked",
                    organization_id,
                    request_id,
                    {"invitation_id": str(invitation_id)},
                )
            )
    except (OrganizationDisabledError, OrganizationNotFoundError):
        raise
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization invitation could not be revoked.") from exc


def accept_organization_invitation(
    factory: sessionmaker[Session],
    token: str,
    user_id: uuid.UUID,
    *,
    request_id: str | None,
) -> OrganizationMembership:
    """Accept one invitation when the authenticated account email matches."""
    if not validate_session_token(token):
        raise OrganizationNotFoundError("Invitation not found.")
    token_hash = hash_session_token(token)
    now = datetime.now(UTC)
    expired = False
    try:
        with transactional_session(factory) as db_session:
            invitation = db_session.scalar(
                select(Invitation).where(Invitation.token_hash == token_hash).with_for_update()
            )
            if invitation is None or invitation.status != "pending":
                raise OrganizationNotFoundError("Invitation not found.")
            expires_at = invitation.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                invitation.status = "expired"
                db_session.flush()
                expired = True
            else:
                if invitation.organization_id is None:
                    raise OrganizationNotFoundError("Invitation not found.")
                organization = _lock_organization(db_session, invitation.organization_id)
                _require_active_organization(organization)
                actor = _lock_users(db_session, [user_id]).get(user_id)
                if actor is None or actor.account_state != "active":
                    raise OrganizationNotFoundError("Invitation not found.")
                if actor.normalized_email != invitation.target_email:
                    raise OrganizationPermissionError("Invitation email does not match the signed-in account.")
                existing = db_session.get(
                    OrganizationMembership,
                    {"organization_id": invitation.organization_id, "user_id": user_id},
                )
                if existing is not None:
                    raise OrganizationConflictError("The user is already an organization member.")
                membership = OrganizationMembership(
                    organization_id=invitation.organization_id,
                    user_id=user_id,
                    role=invitation.role,
                )
                db_session.add(membership)
                invitation.status = "accepted"
                invitation.accepted_at = now
                db_session.flush()
                _ensure_eligible_owner(db_session, invitation.organization_id)
                db_session.add(
                    _audit_event(
                        user_id,
                        "organization.invitation_accepted",
                        invitation.organization_id,
                        request_id,
                        {"invitation_id": str(invitation.id), "role": invitation.role},
                    )
                )
    except (
        OrganizationConflictError,
        OrganizationDisabledError,
        OrganizationNotFoundError,
        OrganizationPermissionError,
    ):
        raise
    except IntegrityError as exc:
        raise OrganizationConflictError("The user is already an organization member.") from exc
    except SQLAlchemyError as exc:
        raise OrganizationOperationError("Organization invitation could not be accepted.") from exc
    if expired:
        raise OrganizationNotFoundError("Invitation not found.")
    return membership
