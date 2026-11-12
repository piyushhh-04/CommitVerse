"""Transactional repository workflows coordinated with local Core storage."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from commitverse_hub.db.models import (
    AuditEvent,
    Invitation,
    Organization,
    OrganizationMembership,
    Repository,
    RepositoryUserPermission,
    User,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.repositories.storage import (
    RepositoryStorageError,
    create_bare_repository,
    delete_bare_repository,
)

_REPOSITORY_NAME_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")


class RepositoryConflictError(Exception):
    """Raised when a repository name or lifecycle transition conflicts."""


class RepositoryNotFoundError(Exception):
    """Raised when the caller cannot access a repository."""


class RepositoryPermissionError(Exception):
    """Raised when the caller lacks the current organization role."""


class RepositoryOperationError(Exception):
    """Raised when repository metadata or Core storage operations fail."""


def normalize_repository_name(value: str) -> str:
    name = value.strip()
    if (
        not name
        or name in {".", ".."}
        or name.endswith(".")
        or not _REPOSITORY_NAME_PATTERN.fullmatch(name)
    ):
        raise ValueError("Repository name is invalid.")
    return name.lower()


def validate_description(value: str | None) -> str | None:
    if value is None:
        return None
    description = value.strip()
    if len(description) > 1000:
        raise ValueError("Repository description is too long.")
    return description or None


def create_personal_repository(
    factory: sessionmaker[Session],
    storage_root: Path,
    owner_user_id: uuid.UUID,
    *,
    name: str,
    description: str | None,
    visibility: str,
    request_id: str | None,
) -> Repository:
    """Create a personal repository through the shared lifecycle."""
    return _create_repository(
        factory,
        storage_root,
        owner_user_id=owner_user_id,
        owner_organization_id=None,
        actor_user_id=owner_user_id,
        name=name,
        description=description,
        visibility=visibility,
        request_id=request_id,
    )


def create_organization_repository(
    factory: sessionmaker[Session],
    storage_root: Path,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    name: str,
    description: str | None,
    visibility: str,
    request_id: str | None,
) -> Repository:
    """Create an organization repository for a current owner or admin."""
    return _create_repository(
        factory,
        storage_root,
        owner_user_id=None,
        owner_organization_id=organization_id,
        actor_user_id=actor_user_id,
        name=name,
        description=description,
        visibility=visibility,
        request_id=request_id,
    )


def _create_repository(
    factory: sessionmaker[Session],
    storage_root: Path,
    *,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    name: str,
    description: str | None,
    visibility: str,
    request_id: str | None,
) -> Repository:
    """Reserve, provision outside the transaction, then atomically publish."""
    slug = normalize_repository_name(name)
    clean_description = validate_description(description)
    if visibility not in {"public", "private"}:
        raise ValueError("Repository visibility is invalid.")
    if (owner_user_id is None) == (owner_organization_id is None):
        raise ValueError("Exactly one repository owner is required.")

    retrying_existing_record = False
    try:
        with transactional_session(factory) as db_session:
            if owner_organization_id is not None:
                organization = _lock_organization(
                    db_session, owner_organization_id
                )
                _require_active_organization(organization)
                _lock_authorized_organization_member(
                    db_session, owner_organization_id, actor_user_id
                )
            else:
                assert owner_user_id is not None
                _require_personal_owner(owner_user_id, actor_user_id)

            repository = _lock_existing_repository(
                db_session,
                owner_user_id,
                owner_organization_id,
                slug,
            )
            if repository is None:
                repository = Repository(
                    id=uuid.uuid4(),
                    owner_user_id=owner_user_id,
                    owner_organization_id=owner_organization_id,
                    created_by=actor_user_id,
                    slug=slug,
                    visibility=visibility,
                    storage_key=uuid.uuid4().hex,
                    lifecycle_state="provisioning",
                    description=clean_description,
                )
                db_session.add(repository)
                db_session.flush()
                db_session.add(
                    _audit_event(
                        actor_user_id,
                        "repository.provisioning",
                        repository.id,
                        request_id,
                        {
                            "name": repository.slug,
                            "owner_type": (
                                "organization"
                                if owner_organization_id is not None
                                else "personal"
                            ),
                            "visibility": repository.visibility,
                        },
                    )
                )
            elif repository.lifecycle_state == "error":
                retrying_existing_record = True
                repository.lifecycle_state = "provisioning"
                repository.description = clean_description
                repository.visibility = visibility
                db_session.add(
                    _audit_event(
                        actor_user_id,
                        "repository.provisioning",
                        repository.id,
                        request_id,
                        {
                            "name": repository.slug,
                            "owner_type": (
                                "organization"
                                if owner_organization_id is not None
                                else "personal"
                            ),
                            "visibility": repository.visibility,
                            "retry": True,
                        },
                    )
                )
            elif repository.lifecycle_state == "provisioning":
                raise RepositoryConflictError(
                    "Repository provisioning is already in progress."
                )
            else:
                raise RepositoryConflictError("Repository name is already in use.")
            repository_id = repository.id
            storage_key = repository.storage_key
    except (
        RepositoryConflictError,
        RepositoryNotFoundError,
        RepositoryPermissionError,
    ):
        raise
    except IntegrityError as exc:
        raise RepositoryConflictError("Repository name is already in use.") from exc
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository metadata could not be reserved.") from exc

    try:
        published_now = create_bare_repository(
            storage_root,
            storage_key,
            allow_existing=retrying_existing_record,
        )
    except RepositoryStorageError as exc:
        _record_provisioning_error(
            factory,
            repository_id,
            owner_organization_id,
            actor_user_id,
            request_id,
            "storage",
        )
        raise RepositoryOperationError("Repository storage could not be initialized.") from exc

    try:
        with transactional_session(factory) as db_session:
            if owner_organization_id is not None:
                organization = _lock_organization(
                    db_session, owner_organization_id
                )
                repository = _lock_repository(db_session, repository_id)
                _assert_repository_owner(
                    repository, owner_user_id, owner_organization_id
                )
                _require_active_organization(organization)
                _lock_authorized_organization_member(
                    db_session, owner_organization_id, actor_user_id
                )
            else:
                repository = _lock_repository(db_session, repository_id)
                _assert_repository_owner(
                    repository, owner_user_id, owner_organization_id
                )
                assert owner_user_id is not None
                _require_personal_owner(owner_user_id, actor_user_id)
            if repository.lifecycle_state != "provisioning":
                raise RepositoryOperationError(
                    "Repository provisioning state is inconsistent."
                )
            repository.lifecycle_state = "ready"
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "repository.created",
                    repository_id,
                    request_id,
                    {
                        "name": repository.slug,
                        "owner_type": (
                            "organization"
                            if owner_organization_id is not None
                            else "personal"
                        ),
                        "visibility": repository.visibility,
                    },
                )
            )
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        RepositoryOperationError,
    ):
        _compensate_failed_publication(
            factory,
            storage_root,
            repository_id,
            storage_key,
            owner_organization_id,
            actor_user_id,
            request_id,
            published_now,
        )
        raise
    except SQLAlchemyError as exc:
        _compensate_failed_publication(
            factory,
            storage_root,
            repository_id,
            storage_key,
            owner_organization_id,
            actor_user_id,
            request_id,
            published_now,
        )
        raise RepositoryOperationError(
            "Repository could not be published as ready."
        ) from exc

    return _load_repository(factory, repository_id)


def list_personal_repositories(
    factory: sessionmaker[Session],
    owner_user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Repository], int]:
    """List ready personal repositories in stable newest-first order."""
    try:
        with factory() as db_session:
            filters = (
                Repository.owner_user_id == owner_user_id,
                Repository.lifecycle_state == "ready",
            )
            total = db_session.scalar(
                select(func.count()).select_from(Repository).where(*filters)
            )
            items = list(
                db_session.scalars(
                    select(Repository)
                    .where(*filters)
                    .order_by(Repository.created_at.desc(), Repository.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            return items, int(total or 0)
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository list could not be loaded.") from exc


def get_personal_repository(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> Repository:
    """Return ready metadata only when the caller is its personal owner."""
    try:
        with factory() as db_session:
            repository = db_session.scalar(
                select(Repository).where(
                    Repository.id == repository_id,
                    Repository.owner_user_id == owner_user_id,
                    Repository.lifecycle_state == "ready",
                )
            )
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            return repository
    except RepositoryNotFoundError:
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository metadata could not be loaded.") from exc


def update_personal_repository(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
    description_provided: bool,
    visibility: str | None,
    request_id: str | None,
) -> Repository:
    """Update approved metadata fields and append a minimal audit event."""
    normalized_name = normalize_repository_name(name) if name is not None else None
    clean_description = validate_description(description) if description_provided else None
    if visibility is not None and visibility not in {"public", "private"}:
        raise ValueError("Repository visibility is invalid.")

    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(
                select(Repository).where(
                    Repository.id == repository_id,
                    Repository.owner_user_id == owner_user_id,
                    Repository.lifecycle_state == "ready",
                ).with_for_update()
            )
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            old_name = repository.slug
            old_visibility = repository.visibility
            if normalized_name is not None:
                repository.slug = normalized_name
            if description_provided:
                repository.description = clean_description
            if visibility is not None:
                repository.visibility = visibility
            db_session.flush()
            db_session.add(
                _audit_event(
                    owner_user_id,
                    "repository.updated",
                    repository_id,
                    request_id,
                    {
                        "name_changed": old_name != repository.slug,
                        "visibility_changed": old_visibility != repository.visibility,
                        "description_changed": description_provided,
                    },
                )
            )
    except RepositoryNotFoundError:
        raise
    except IntegrityError as exc:
        raise RepositoryConflictError("Repository name is already in use.") from exc
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository metadata could not be updated.") from exc
    return _load_repository(factory, repository_id)


def delete_personal_repository(
    factory: sessionmaker[Session],
    storage_root: Path,
    repository_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    *,
    request_id: str | None,
) -> None:
    """Delete an owner-only personal repository through the shared lifecycle."""
    _delete_repository(
        factory,
        storage_root,
        repository_id,
        owner_user_id=owner_user_id,
        owner_organization_id=None,
        actor_user_id=owner_user_id,
        request_id=request_id,
    )


def delete_organization_repository(
    factory: sessionmaker[Session],
    storage_root: Path,
    repository_id: uuid.UUID,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    request_id: str | None,
) -> None:
    """Delete an organization repository for a current owner or admin."""
    _delete_repository(
        factory,
        storage_root,
        repository_id,
        owner_user_id=None,
        owner_organization_id=organization_id,
        actor_user_id=actor_user_id,
        request_id=request_id,
    )


def _delete_repository(
    factory: sessionmaker[Session],
    storage_root: Path,
    repository_id: uuid.UUID,
    *,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    request_id: str | None,
) -> None:
    """Mark deleting, clean storage outside transactions, then finalize atomically."""
    try:
        with transactional_session(factory) as db_session:
            if owner_organization_id is not None:
                organization = _lock_organization(
                    db_session, owner_organization_id
                )
                repository = _lock_repository(db_session, repository_id)
                _assert_repository_owner(
                    repository, owner_user_id, owner_organization_id
                )
                _require_active_organization(organization)
                _lock_authorized_organization_member(
                    db_session, owner_organization_id, actor_user_id
                )
            else:
                repository = _lock_repository(db_session, repository_id)
                _assert_repository_owner(
                    repository, owner_user_id, owner_organization_id
                )
                assert owner_user_id is not None
                _require_personal_owner(owner_user_id, actor_user_id)

            if repository.lifecycle_state == "deleted":
                return

            storage_key = repository.storage_key
            prior_name = repository.slug
            if repository.lifecycle_state != "deleting":
                repository.lifecycle_state = "deleting"
                db_session.add(
                    _audit_event(
                        actor_user_id,
                        "repository.deleting",
                        repository_id,
                        request_id,
                        {
                            "name": prior_name,
                            "owner_type": (
                                "organization"
                                if owner_organization_id is not None
                                else "personal"
                            ),
                        },
                    )
                )
            db_session.execute(
                delete(RepositoryUserPermission).where(
                    RepositoryUserPermission.repository_id == repository_id
                )
            )
            invitations = db_session.scalars(
                select(Invitation).where(
                    Invitation.repository_id == repository_id,
                    Invitation.status == "pending",
                )
            )
            now = datetime.now(UTC)
            for invitation in invitations:
                invitation.status = "revoked"
                invitation.revoked_at = now
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
    ):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError(
            "Repository could not enter deleting state."
        ) from exc

    try:
        delete_bare_repository(storage_root, storage_key)
    except RepositoryStorageError as exc:
        raise RepositoryOperationError(
            "Repository deletion is pending safe storage cleanup; retry the request."
        ) from exc

    try:
        with transactional_session(factory) as db_session:
            if owner_organization_id is not None:
                _lock_organization(db_session, owner_organization_id)
            repository = _lock_repository(db_session, repository_id)
            _assert_repository_owner(
                repository, owner_user_id, owner_organization_id
            )
            if repository.lifecycle_state == "deleted":
                return
            if repository.lifecycle_state != "deleting":
                raise RepositoryOperationError(
                    "Repository deletion state is inconsistent."
                )
            tombstone_name = f"deleted~{repository_id.hex}"
            repository.slug = tombstone_name
            repository.lifecycle_state = "deleted"
            db_session.add(
                _audit_event(
                    actor_user_id,
                    "repository.deleted",
                    repository_id,
                    request_id,
                    {
                        "name": prior_name,
                        "owner_type": (
                            "organization"
                            if owner_organization_id is not None
                            else "personal"
                        ),
                    },
                )
            )
    except (
        RepositoryNotFoundError,
        RepositoryOperationError,
    ):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError(
            "Repository storage was removed; metadata finalization is pending retry."
        ) from exc


def _repository_owner_filters(
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    if owner_user_id is not None:
        return (
            Repository.owner_user_id == owner_user_id,
            Repository.owner_organization_id.is_(None),
        )
    assert owner_organization_id is not None
    return (
        Repository.owner_user_id.is_(None),
        Repository.owner_organization_id == owner_organization_id,
    )


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
        raise RepositoryNotFoundError("Repository not found.")
    return organization


def _require_active_organization(organization: Organization) -> None:
    if organization.state != "active":
        raise RepositoryPermissionError("Organization is not active.")


def _lock_authorized_organization_member(
    db_session: Session,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> OrganizationMembership:
    membership = db_session.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == actor_user_id,
        )
        .with_for_update()
    )
    actor = db_session.scalar(
        select(User).where(User.id == actor_user_id).with_for_update()
    )
    if (
        membership is None
        or actor is None
        or actor.account_state != "active"
    ):
        raise RepositoryNotFoundError("Repository not found.")
    if membership.role not in {"owner", "admin"}:
        raise RepositoryPermissionError(
            "Organization repository management is not permitted."
        )
    return membership


def _require_personal_owner(
    owner_user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    if actor_user_id != owner_user_id:
        raise RepositoryNotFoundError("Repository not found.")


def _lock_repository(
    db_session: Session,
    repository_id: uuid.UUID,
) -> Repository:
    repository = db_session.scalar(
        select(Repository)
        .where(Repository.id == repository_id)
        .with_for_update()
    )
    if repository is None:
        raise RepositoryNotFoundError("Repository not found.")
    return repository


def _lock_existing_repository(
    db_session: Session,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
    slug: str,
) -> Repository | None:
    return db_session.scalar(
        select(Repository)
        .where(
            *_repository_owner_filters(owner_user_id, owner_organization_id),
            func.lower(Repository.slug) == slug,
        )
        .with_for_update()
    )


def _assert_repository_owner(
    repository: Repository,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
) -> None:
    if (
        repository.owner_user_id != owner_user_id
        or repository.owner_organization_id != owner_organization_id
    ):
        raise RepositoryNotFoundError("Repository not found.")


def _repository_state_for_cleanup(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    owner_organization_id: uuid.UUID | None,
) -> str | None:
    try:
        with transactional_session(factory) as db_session:
            if owner_organization_id is not None:
                _lock_organization(db_session, owner_organization_id)
            repository = _lock_repository(db_session, repository_id)
            return repository.lifecycle_state
    except RepositoryNotFoundError:
        return None
    except SQLAlchemyError as exc:
        raise RepositoryOperationError(
            "Repository publication state could not be verified."
        ) from exc


def _record_provisioning_error(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    owner_organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    request_id: str | None,
    phase: str,
) -> None:
    try:
        with transactional_session(factory) as db_session:
            if owner_organization_id is not None:
                _lock_organization(db_session, owner_organization_id)
            repository = _lock_repository(db_session, repository_id)
            if repository.lifecycle_state == "provisioning":
                repository.lifecycle_state = "error"
                db_session.add(
                    _audit_event(
                        actor_user_id,
                        "repository.provisioning_failed",
                        repository_id,
                        request_id,
                        {
                            "phase": phase,
                            "owner_type": (
                                "organization"
                                if owner_organization_id is not None
                                else "personal"
                            ),
                        },
                    )
                )
    except RepositoryNotFoundError:
        return
    except SQLAlchemyError as exc:
        raise RepositoryOperationError(
            "Repository provisioning failure could not be recorded."
        ) from exc


def _compensate_failed_publication(
    factory: sessionmaker[Session],
    storage_root: Path,
    repository_id: uuid.UUID,
    storage_key: str,
    owner_organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    request_id: str | None,
    published_now: bool,
) -> None:
    lifecycle_state = _repository_state_for_cleanup(
        factory, repository_id, owner_organization_id
    )
    cleanup_error: RepositoryStorageError | None = None
    if published_now and lifecycle_state in {"provisioning", "deleting", "deleted"}:
        try:
            delete_bare_repository(storage_root, storage_key)
        except RepositoryStorageError as exc:
            cleanup_error = exc
    _record_provisioning_error(
        factory,
        repository_id,
        owner_organization_id,
        actor_user_id,
        request_id,
        "publication",
    )
    if cleanup_error is not None:
        raise RepositoryOperationError(
            "Repository publication failed and storage cleanup requires retry."
        ) from cleanup_error


def _load_repository(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
) -> Repository:
    try:
        with factory() as db_session:
            repository = db_session.get(Repository, repository_id)
            if repository is None:
                raise RepositoryOperationError("Repository metadata is missing.")
            return repository
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository metadata could not be loaded.") from exc


def _audit_event(
    actor_user_id: uuid.UUID,
    action: str,
    repository_id: uuid.UUID,
    request_id: str | None,
    event_metadata: dict[str, object],
) -> AuditEvent:
    return AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        target_type="repository",
        target_id=str(repository_id),
        request_id=request_id,
        event_metadata=event_metadata,
    )
