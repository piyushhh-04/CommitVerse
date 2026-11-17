"""Repository-scoped invitations that publish existing direct permissions."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.auth.tokens import generate_session_token, hash_session_token, validate_session_token
from commitverse_hub.db.models import Invitation, Repository, RepositoryUserPermission, User
from commitverse_hub.db.session import transactional_session
from commitverse_hub.repositories.service import (
    RepositoryConflictError,
    RepositoryNotFoundError,
    RepositoryOperationError,
    RepositoryPermissionError,
    _audit_event,
    _lock_organization,
    _lock_repository,
    _lock_repository_for_permission_manager,
    _validate_repository_permission_role,
)

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")


@dataclass(frozen=True)
class IssuedRepositoryInvitation:
    invitation: Invitation
    token: str


def _email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invitation email is invalid.")
    normalized = value.strip().lower()
    if not normalized or " " in normalized or not _EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Invitation email is invalid.")
    return normalized


def create_repository_invitation(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    target_email: str,
    role: str,
    expires_in_days: int,
    request_id: str | None,
) -> IssuedRepositoryInvitation:
    target = _email(target_email)
    _validate_repository_permission_role(role)
    if not 1 <= expires_in_days <= 30:
        raise ValueError("Invitation expiry must be between 1 and 30 days.")
    token = generate_session_token()
    invitation_id = uuid.uuid4()
    try:
        with transactional_session(factory) as db_session:
            repository = _lock_repository_for_permission_manager(
                db_session, repository_id, actor_user_id
            )
            if repository.lifecycle_state != "ready":
                raise RepositoryNotFoundError("Repository not found.")
            owner_ids = [value for value in [repository.owner_user_id] if value is not None]
            owner_email = db_session.scalar(
                select(User.normalized_email).where(User.id.in_(owner_ids))
            ) if owner_ids else None
            existing_permission = db_session.scalar(
                select(RepositoryUserPermission)
                .join(User, User.id == RepositoryUserPermission.user_id)
                .where(
                    RepositoryUserPermission.repository_id == repository_id,
                    User.normalized_email == target,
                )
            )
            if target == owner_email or existing_permission is not None:
                raise RepositoryConflictError("The user already has repository access.")
            now = datetime.now(UTC)
            expired_invitation = db_session.scalar(
                select(Invitation)
                .where(
                    Invitation.repository_id == repository_id,
                    Invitation.target_email == target,
                    Invitation.status == "pending",
                    Invitation.expires_at <= now,
                )
                .with_for_update()
            )
            if expired_invitation is not None:
                expired_invitation.status = "expired"
                db_session.flush()
            invitation = Invitation(
                id=invitation_id,
                inviter_user_id=actor_user_id,
                target_email=target,
                repository_id=repository_id,
                role=role,
                token_hash=hash_session_token(token),
                expires_at=now + timedelta(days=expires_in_days),
            )
            db_session.add(invitation)
            db_session.flush()
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "repository.invitation_created",
                    repository_id,
                    request_id,
                    {"invitation_id": str(invitation_id), "role": role},
                )
            )
    except (RepositoryConflictError, RepositoryNotFoundError, RepositoryPermissionError, ValueError):
        raise
    except IntegrityError as exc:
        raise RepositoryConflictError("A pending invitation already exists for this email.") from exc
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository invitation could not be created.") from exc
    return IssuedRepositoryInvitation(invitation, token)


def list_repository_invitations(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Invitation], int]:
    from sqlalchemy import func

    try:
        with factory() as db_session:
            _lock_repository_for_permission_manager(db_session, repository_id, actor_user_id)
            now = datetime.now(UTC)
            filters = (
                Invitation.repository_id == repository_id,
                Invitation.status == "pending",
                Invitation.expires_at > now,
            )
            total = db_session.scalar(select(func.count()).select_from(Invitation).where(*filters))
            items = list(
                db_session.scalars(
                    select(Invitation)
                    .where(*filters)
                    .order_by(Invitation.created_at, Invitation.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            return items, int(total or 0)
    except (RepositoryNotFoundError, RepositoryPermissionError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository invitations could not be loaded.") from exc


def revoke_repository_invitation(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    invitation_id: uuid.UUID,
    *,
    request_id: str | None,
) -> None:
    try:
        with transactional_session(factory) as db_session:
            _lock_repository_for_permission_manager(db_session, repository_id, actor_user_id)
            invitation = db_session.scalar(
                select(Invitation)
                .where(
                    Invitation.id == invitation_id,
                    Invitation.repository_id == repository_id,
                    Invitation.status == "pending",
                )
                .with_for_update()
            )
            if invitation is None:
                raise RepositoryNotFoundError("Invitation not found.")
            invitation.status = "revoked"
            invitation.revoked_at = datetime.now(UTC)
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "repository.invitation_revoked",
                    repository_id,
                    request_id,
                    {"invitation_id": str(invitation_id)},
                )
            )
    except (RepositoryNotFoundError, RepositoryPermissionError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository invitation could not be revoked.") from exc


def accept_repository_invitation(
    factory: sessionmaker[Session],
    token: str,
    user_id: uuid.UUID,
    *,
    request_id: str | None,
) -> RepositoryUserPermission:
    if not validate_session_token(token):
        raise RepositoryNotFoundError("Invitation not found.")
    token_hash = hash_session_token(token)
    permission: RepositoryUserPermission | None = None
    expired = False
    try:
        with transactional_session(factory) as db_session:
            initial_invitation = db_session.scalar(
                select(Invitation).where(Invitation.token_hash == token_hash)
            )
            if (
                initial_invitation is None
                or initial_invitation.status != "pending"
                or initial_invitation.repository_id is None
            ):
                raise RepositoryNotFoundError("Invitation not found.")
            repository_snapshot = db_session.get(Repository, initial_invitation.repository_id)
            if repository_snapshot is None:
                raise RepositoryNotFoundError("Invitation not found.")
            organization_id = repository_snapshot.owner_organization_id
            if organization_id is not None:
                organization = _lock_organization(db_session, organization_id)
                if organization.state != "active":
                    raise RepositoryNotFoundError("Invitation not found.")
            user = db_session.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if user is None or user.account_state != "active":
                raise RepositoryPermissionError(
                    "Invitation email does not match the signed-in account."
                )
            db_session.expire(repository_snapshot)
            repository = _lock_repository(db_session, initial_invitation.repository_id)
            if (
                repository.lifecycle_state != "ready"
                or repository.owner_organization_id != organization_id
            ):
                raise RepositoryNotFoundError("Invitation not found.")
            invitation = db_session.scalar(
                select(Invitation)
                .where(
                    Invitation.id == initial_invitation.id,
                    Invitation.token_hash == token_hash,
                    Invitation.repository_id == repository.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if invitation is None or invitation.status != "pending":
                raise RepositoryNotFoundError("Invitation not found.")
            now = datetime.now(UTC)
            expiry = invitation.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= now:
                invitation.status = "expired"
                db_session.flush()
                expired = True
            else:
                if user.normalized_email != invitation.target_email:
                    raise RepositoryPermissionError("Invitation email does not match the signed-in account.")
                if repository.owner_user_id == user_id:
                    raise RepositoryConflictError("The user already owns this repository.")
                existing = db_session.get(RepositoryUserPermission, (repository.id, user_id))
                if existing is not None:
                    raise RepositoryConflictError("The user already has repository access.")
                permission = RepositoryUserPermission(
                    repository_id=repository.id,
                    user_id=user_id,
                    role=invitation.role,
                    granted_by=invitation.inviter_user_id,
                )
                db_session.add(permission)
                invitation.status = "accepted"
                invitation.accepted_at = datetime.now(UTC)
                db_session.flush()
                db_session.add(
                    _audit_event(
                        user_id,
                        "repository.invitation_accepted",
                        repository.id,
                        request_id,
                        {"invitation_id": str(invitation.id), "role": invitation.role},
                    )
                )
    except (RepositoryConflictError, RepositoryNotFoundError, RepositoryPermissionError):
        raise
    except IntegrityError as exc:
        raise RepositoryConflictError("The user already has repository access.") from exc
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository invitation could not be accepted.") from exc
    if expired:
        raise RepositoryNotFoundError("Invitation not found.")
    assert permission is not None
    return permission
