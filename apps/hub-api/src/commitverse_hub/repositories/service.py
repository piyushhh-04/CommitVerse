"""Transactional personal-repository workflows coordinated with local storage."""

from __future__ import annotations

import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.db.models import (
    AuditEvent,
    Invitation,
    Repository,
    RepositoryUserPermission,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.repositories.storage import (
    RepositoryStorageError,
    create_bare_repository,
    delete_bare_repository,
)

_REPOSITORY_NAME_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_LIFECYCLE_LOCK = threading.RLock()


class RepositoryConflictError(Exception):
    """Raised when a personal repository name is already in use."""


class RepositoryNotFoundError(Exception):
    """Raised when the caller cannot access a ready personal repository."""


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
    """Create metadata, provision a Core bare repository, then publish as ready."""
    slug = normalize_repository_name(name)
    clean_description = validate_description(description)
    if visibility not in {"public", "private"}:
        raise ValueError("Repository visibility is invalid.")

    with _LIFECYCLE_LOCK:
        retrying_existing_record = False
        try:
            with transactional_session(factory) as db_session:
                repository = db_session.scalar(
                    select(Repository).where(
                        Repository.owner_user_id == owner_user_id,
                        func.lower(Repository.slug) == slug,
                    )
                )
                if repository is None:
                    repository = Repository(
                        id=uuid.uuid4(),
                        owner_user_id=owner_user_id,
                        owner_organization_id=None,
                        created_by=owner_user_id,
                        slug=slug,
                        visibility=visibility,
                        storage_key=uuid.uuid4().hex,
                        lifecycle_state="provisioning",
                        description=clean_description,
                    )
                    db_session.add(repository)
                    db_session.flush()
                elif repository.lifecycle_state in {"provisioning", "error"}:
                    retrying_existing_record = True
                    repository.lifecycle_state = "provisioning"
                    repository.description = clean_description
                    repository.visibility = visibility
                else:
                    raise RepositoryConflictError("Repository name is already in use.")
                repository_id = repository.id
                storage_key = repository.storage_key
        except RepositoryConflictError:
            raise
        except IntegrityError as exc:
            raise RepositoryConflictError("Repository name is already in use.") from exc
        except SQLAlchemyError as exc:
            raise RepositoryOperationError("Repository metadata could not be created.") from exc

        try:
            published_now = create_bare_repository(
                storage_root,
                storage_key,
                allow_existing=retrying_existing_record,
            )
        except RepositoryStorageError as exc:
            _set_lifecycle_state(factory, repository_id, "error")
            raise RepositoryOperationError("Repository storage could not be initialized.") from exc

        try:
            with transactional_session(factory) as db_session:
                repository = db_session.get(Repository, repository_id)
                if repository is None or repository.lifecycle_state != "provisioning":
                    raise RepositoryOperationError("Repository provisioning state is inconsistent.")
                repository.lifecycle_state = "ready"
                db_session.add(
                    _audit_event(
                        owner_user_id,
                        "repository.created",
                        repository_id,
                        request_id,
                        {"name": repository.slug, "visibility": repository.visibility},
                    )
                )
        except (RepositoryOperationError, SQLAlchemyError) as exc:
            cleanup_error: RepositoryStorageError | None = None
            if published_now:
                try:
                    delete_bare_repository(storage_root, storage_key)
                except RepositoryStorageError as cleanup_exc:
                    cleanup_error = cleanup_exc
            _set_lifecycle_state(factory, repository_id, "error")
            if cleanup_error is not None:
                raise RepositoryOperationError(
                    "Repository metadata publication failed and storage cleanup requires retry."
                ) from cleanup_error
            raise RepositoryOperationError("Repository could not be published as ready.") from exc

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
    """Mark deleting, safely remove storage, and retain an idempotent tombstone."""
    with _LIFECYCLE_LOCK:
        try:
            with transactional_session(factory) as db_session:
                repository = db_session.scalar(
                    select(Repository).where(
                        Repository.id == repository_id,
                        Repository.owner_user_id == owner_user_id,
                    ).with_for_update()
                )
                if repository is None:
                    raise RepositoryNotFoundError("Repository not found.")
                storage_key = repository.storage_key
                prior_name = repository.slug
                repository.lifecycle_state = "deleting"
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
        except RepositoryNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise RepositoryOperationError("Repository could not enter deleting state.") from exc

        try:
            delete_bare_repository(storage_root, storage_key)
        except RepositoryStorageError as exc:
            raise RepositoryOperationError(
                "Repository deletion is pending safe storage cleanup; retry the request."
            ) from exc

        try:
            with transactional_session(factory) as db_session:
                repository = db_session.get(Repository, repository_id)
                if repository is None:
                    return
                tombstone_name = f"deleted~{repository_id.hex}"
                repository.slug = tombstone_name
                already_audited = db_session.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.action == "repository.deleted",
                        AuditEvent.target_type == "repository",
                        AuditEvent.target_id == str(repository_id),
                    )
                )
                if already_audited is None:
                    db_session.add(
                        _audit_event(
                            owner_user_id,
                            "repository.deleted",
                            repository_id,
                            request_id,
                            {"name": prior_name},
                        )
                    )
        except SQLAlchemyError as exc:
            raise RepositoryOperationError(
                "Repository storage was removed; metadata finalization is pending retry."
            ) from exc


def _set_lifecycle_state(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    state: str,
) -> None:
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.get(Repository, repository_id)
            if repository is not None:
                repository.lifecycle_state = state
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Repository lifecycle state could not be updated.") from exc


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
