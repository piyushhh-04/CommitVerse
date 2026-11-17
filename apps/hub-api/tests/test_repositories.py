"""Personal repository API and Core-backed lifecycle tests."""

from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_core.repository import discover_repository, initialize_repository
from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_hub.auth.cookies import AuthCookieSettings
from commitverse_hub.auth.csrf import generate_csrf_token
from commitverse_hub.auth.sessions import create_session_record
from commitverse_hub.auth.tokens import hash_session_token, validate_session_token
from commitverse_hub.config import Settings
from commitverse_hub.db.base import Base
from commitverse_hub.db.models import (
    AuditEvent,
    Invitation,
    Organization,
    OrganizationMembership,
    Repository,
    RepositoryUserPermission,
    User,
    UserProfile,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.main import create_app
from commitverse_hub.repositories.service import (
    RepositoryConflictError,
    RepositoryNotFoundError,
    RepositoryOperationError,
    RepositoryPermissionError,
    create_organization_repository,
    create_personal_repository,
    delete_organization_repository,
    delete_personal_repository,
    get_personal_repository,
    get_repository_for_access,
    list_personal_repositories,
    update_personal_repository,
)
from commitverse_hub.repositories import service as repository_service
from commitverse_hub.repositories.invitations import (
    accept_repository_invitation,
    create_repository_invitation,
    list_repository_invitations,
    revoke_repository_invitation,
)
from commitverse_hub.repositories import invitations as repository_invitation_service
from commitverse_hub.repositories.storage import (
    RepositoryStorageError,
    create_bare_repository,
    delete_bare_repository,
)
from commitverse_core.objects.store import write_object
from commitverse_core.trees import TreeEntry, serialize_tree
from commitverse_core.refs import write_ref


@pytest.fixture
def repository_client(tmp_path):
    database_path = tmp_path / "repositories.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    user_ids = (uuid.uuid4(), uuid.uuid4())
    session_tokens: list[str] = []
    with transactional_session(factory) as db_session:
        for index, user_id in enumerate(user_ids):
            db_session.add(
                User(
                    id=user_id,
                    normalized_email=f"repo-user-{index}@example.test",
                    password_hash="test-only-placeholder-hash",
                )
            )
            db_session.add(
                UserProfile(
                    user_id=user_id,
                    username=f"repo-user-{index}",
                    display_name=f"Repo User {index}",
                )
            )
            _, token = create_session_record(
                db_session,
                user_id,
                lifetime=timedelta(hours=1),
            )
            session_tokens.append(token)

    storage_root = (tmp_path / "repository-storage").resolve()
    settings = Settings(
        environment="testing",
        database_url="postgresql+psycopg://test@localhost/test",
        auth_cookie=AuthCookieSettings(secure=False, max_age_seconds=3600),
        csrf_allowed_origins=("https://hub.example.test",),
        repository_storage_root=storage_root,
    )
    app = create_app(settings, database_engine_factory=lambda _url: engine)
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie.name, session_tokens[0])
        yield {
            "client": client,
            "engine": engine,
            "factory": factory,
            "settings": settings,
            "storage_root": storage_root,
            "user_ids": user_ids,
            "session_tokens": tuple(session_tokens),
            "csrf_tokens": tuple(
                generate_csrf_token(token) for token in session_tokens
            ),
        }
    engine.dispose()


def _browser_headers(csrf_token: str | None = None) -> dict[str, str]:
    headers = {"Origin": "https://hub.example.test"}
    if csrf_token is not None:
        headers["X-CSRF-Token"] = csrf_token
    return headers


def _create(client, csrf_token: str, name: str, **fields):
    return client.post(
        "/api/v1/repositories",
        headers=_browser_headers(csrf_token),
        json={"name": name, **fields},
    )


def _create_invitation(client, repository_id: str, csrf_token: str, *, email: str, role: str = "reader"):
    return client.post(
        f"/api/v1/repositories/{repository_id}/invitations",
        headers=_browser_headers(csrf_token),
        json={"target_email": email, "role": role},
    )


def _create_test_organization(
    factory: sessionmaker[Session],
    user_ids: tuple[uuid.UUID, uuid.UUID],
    *,
    second_role: str = "admin",
) -> uuid.UUID:
    organization_id = uuid.uuid4()
    with transactional_session(factory) as db_session:
        db_session.add(
            Organization(
                id=organization_id,
                slug=f"repo-org-{organization_id.hex[:8]}",
                name="Repository Test Organization",
                created_by=user_ids[0],
                state="active",
            )
        )
        db_session.add_all(
            [
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=user_ids[0],
                    role="owner",
                ),
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=user_ids[1],
                    role=second_role,
                ),
            ]
        )
    return organization_id


def test_repository_creation_uses_authenticated_owner_and_core(repository_client) -> None:
    client = repository_client["client"]
    response = _create(
        client,
        repository_client["csrf_tokens"][0],
        "  First-Repo  ",
        description="  a personal repository  ",
        visibility="public",
        owner_user_id=str(repository_client["user_ids"][1]),
    )

    assert response.status_code == 422
    response = _create(
        client,
        repository_client["csrf_tokens"][0],
        "  First-Repo  ",
        description="  a personal repository  ",
        visibility="public",
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "first-repo"
    assert payload["description"] == "a personal repository"
    assert payload["visibility"] == "public"
    assert "storage_key" not in payload
    assert "storage_path" not in payload

    with repository_client["factory"]() as db_session:
        repository = db_session.get(Repository, uuid.UUID(payload["id"]))
        assert repository is not None
        assert repository.owner_user_id == repository_client["user_ids"][0]
        assert repository.created_by == repository_client["user_ids"][0]
        assert repository.lifecycle_state == "ready"
        assert repository.storage_key not in payload.values()
        stored_path = repository_client["storage_root"] / f"{repository.storage_key}.git"
        assert discover_repository(stored_path).bare
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.provisioning",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.created",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1


def test_organization_repository_routes_manage_core_backed_storage(repository_client) -> None:
    organization_id = _create_test_organization(
        repository_client["factory"], repository_client["user_ids"], second_role="admin"
    )
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    base_path = f"/api/v1/organizations/{organization_id}/repositories"

    created = client.post(
        base_path,
        headers=_browser_headers(csrf),
        json={"name": "shared-repo", "description": "shared", "visibility": "private"},
    )
    assert created.status_code == 201
    repository_id = created.json()["id"]
    assert created.json()["name"] == "shared-repo"

    listed = client.get(base_path)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == repository_id

    detail_path = f"{base_path}/{repository_id}"
    detail = client.get(detail_path)
    assert detail.status_code == 200
    assert detail.json()["description"] == "shared"

    updated = client.patch(
        detail_path,
        headers=_browser_headers(csrf),
        json={"name": "shared-renamed", "description": None, "visibility": "public"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "shared-renamed"
    assert updated.json()["description"] is None
    assert updated.json()["visibility"] == "public"

    with repository_client["factory"]() as db_session:
        repository = db_session.get(Repository, uuid.UUID(repository_id))
        assert repository is not None
        storage_path = repository_client["storage_root"] / f"{repository.storage_key}.git"
        assert discover_repository(storage_path).bare

    deleted = client.delete(detail_path, headers=_browser_headers(csrf))
    assert deleted.status_code == 204
    assert not storage_path.exists()


def test_organization_repository_routes_do_not_grant_member_visibility(repository_client) -> None:
    organization_id = _create_test_organization(
        repository_client["factory"], repository_client["user_ids"], second_role="member"
    )
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    base_path = f"/api/v1/organizations/{organization_id}/repositories"
    created = client.post(
        base_path,
        headers=_browser_headers(csrf),
        json={"name": "owner-only-repo"},
    )
    assert created.status_code == 201

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    member_list = client.get(base_path)
    assert member_list.status_code == 403
    assert member_list.json()["error"]["code"] == "repository_permission_denied"


def test_repository_listing_paginates_and_hides_other_users(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    for name in ("repo-one", "repo-two", "repo-three"):
        assert _create(client, csrf, name).status_code == 201

    first_page = client.get("/api/v1/repositories?limit=2&offset=0")
    second_page = client.get("/api/v1/repositories?limit=2&offset=2")
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 1
    assert set(item["name"] for item in first_page.json()["items"]).isdisjoint(
        item["name"] for item in second_page.json()["items"]
    )

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    other_user = client.get("/api/v1/repositories")
    assert other_user.status_code == 200
    assert other_user.json()["items"] == []
    assert other_user.json()["total"] == 0


def test_repository_direct_permissions_are_owner_managed_and_audited(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    target_user_id = str(repository_client["user_ids"][1])
    created = _create(client, csrf, "permissioned-repo")
    assert created.status_code == 201
    repository_id = created.json()["id"]
    permissions_path = f"/api/v1/repositories/{repository_id}/permissions"

    assert client.get(permissions_path).json() == []
    granted = client.post(
        permissions_path,
        headers=_browser_headers(csrf),
        json={"user_id": target_user_id, "role": "reader"},
    )
    assert granted.status_code == 201
    assert granted.json()["user_id"] == target_user_id
    assert granted.json()["role"] == "reader"

    duplicate = client.post(
        permissions_path,
        headers=_browser_headers(csrf),
        json={"user_id": target_user_id, "role": "writer"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "repository_conflict"

    updated = client.patch(
        f"{permissions_path}/{target_user_id}",
        headers=_browser_headers(csrf),
        json={"role": "admin"},
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "admin"

    revoked = client.delete(
        f"{permissions_path}/{target_user_id}",
        headers=_browser_headers(csrf),
    )
    assert revoked.status_code == 204
    assert client.get(permissions_path).json() == []

    with repository_client["factory"]() as db_session:
        audit_actions = db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.target_id == repository_id,
                AuditEvent.action.like("repository.permission_%"),
            )
        ).all()
    assert audit_actions == [
        "repository.permission_granted",
        "repository.permission_updated",
        "repository.permission_revoked",
    ]


def test_repository_invitation_http_lifecycle_is_private_email_bound_and_audited(
    repository_client,
) -> None:
    client = repository_client["client"]
    owner_id, invited_user_id = repository_client["user_ids"]
    owner_csrf, invited_user_csrf = repository_client["csrf_tokens"]
    created = _create(client, owner_csrf, "invitation-lifecycle")
    assert created.status_code == 201
    repository_id = created.json()["id"]
    invitations_path = f"/api/v1/repositories/{repository_id}/invitations"

    issued = _create_invitation(
        client,
        repository_id,
        owner_csrf,
        email="  REPO-USER-1@EXAMPLE.TEST ",
        role="writer",
    )
    assert issued.status_code == 201
    created_payload = issued.json()
    token = created_payload["token"]
    invitation_id = created_payload["id"]
    assert validate_session_token(token)
    assert created_payload["target_email"] == "repo-user-1@example.test"
    assert created_payload["role"] == "writer"

    with repository_client["factory"]() as db_session:
        invitation = db_session.get(Invitation, uuid.UUID(invitation_id))
        assert invitation is not None
        assert invitation.token_hash == hash_session_token(token)
        assert invitation.token_hash != token
        assert len(invitation.token_hash) == 64

    listed = client.get(invitations_path)
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] == 1
    assert len(listed_payload["items"]) == 1
    assert listed_payload["items"][0] == {
        "id": invitation_id,
        "target_email": "repo-user-1@example.test",
        "role": "writer",
        "status": "pending",
        "expires_at": created_payload["expires_at"],
        "created_at": created_payload["created_at"],
    }
    assert "token" not in listed_payload["items"][0]
    assert "token_hash" not in listed_payload["items"][0]
    assert token not in listed.text

    duplicate = _create_invitation(
        client,
        repository_id,
        owner_csrf,
        email="repo-user-1@example.test",
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == (
        "Invitation conflicts with existing repository access or invitation."
    )
    assert "repo-user-1@example.test" not in duplicate.text
    assert token not in duplicate.text
    invalid_email = _create_invitation(
        client,
        repository_id,
        owner_csrf,
        email="not-an-email",
    )
    assert invalid_email.status_code == 422
    assert "not-an-email" not in invalid_email.text

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    unauthorized_list = client.get(invitations_path)
    assert unauthorized_list.status_code == 404
    assert "repo-user-1@example.test" not in unauthorized_list.text
    unauthorized_revoke = client.delete(
        f"{invitations_path}/{invitation_id}",
        headers=_browser_headers(invited_user_csrf),
    )
    assert unauthorized_revoke.status_code == 404
    assert "repo-user-1@example.test" not in unauthorized_revoke.text
    unauthorized_create = _create_invitation(
        client,
        repository_id,
        invited_user_csrf,
        email="unauthorized@example.test",
    )
    assert unauthorized_create.status_code == 404
    assert "unauthorized@example.test" not in unauthorized_create.text
    missing_accept_csrf = client.post(
        f"/api/v1/repositories/invitations/{token}/accept",
        headers={"Origin": "https://hub.example.test"},
    )
    assert missing_accept_csrf.status_code == 403
    assert token not in missing_accept_csrf.text

    accepted = client.post(
        f"/api/v1/repositories/invitations/{token}/accept",
        headers=_browser_headers(invited_user_csrf),
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"repository_id": repository_id, "role": "writer"}
    replayed = client.post(
        f"/api/v1/repositories/invitations/{token}/accept",
        headers=_browser_headers(invited_user_csrf),
    )
    assert replayed.status_code == 404
    assert token not in replayed.text

    with repository_client["factory"]() as db_session:
        permission = db_session.get(
            RepositoryUserPermission,
            (uuid.UUID(repository_id), invited_user_id),
        )
        invitation = db_session.get(Invitation, uuid.UUID(invitation_id))
        assert permission is not None
        assert permission.role == "writer"
        assert permission.granted_by == owner_id
        assert invitation is not None
        assert invitation.status == "accepted"
        assert invitation.accepted_at is not None
        events = db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.target_id == repository_id,
                AuditEvent.action.in_(
                    ["repository.invitation_created", "repository.invitation_accepted"]
                ),
            )
        ).all()
    assert {
        event.action: event.event_metadata for event in events
    } == {
        "repository.invitation_created": {
            "invitation_id": invitation_id,
            "role": "writer",
        },
        "repository.invitation_accepted": {
            "invitation_id": invitation_id,
            "role": "writer",
        },
    }

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][0],
    )
    mismatched_email = "not-the-invited-user@example.test"
    mismatched = _create_invitation(
        client,
        repository_id,
        owner_csrf,
        email=mismatched_email,
    )
    assert mismatched.status_code == 201
    mismatch_token = mismatched.json()["token"]
    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    mismatch_response = client.post(
        f"/api/v1/repositories/invitations/{mismatch_token}/accept",
        headers=_browser_headers(invited_user_csrf),
    )
    assert mismatch_response.status_code == 403
    assert mismatched_email not in mismatch_response.text
    assert mismatch_token not in mismatch_response.text

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][0],
    )
    revoked = client.delete(
        f"{invitations_path}/{mismatched.json()['id']}",
        headers=_browser_headers(owner_csrf),
    )
    assert revoked.status_code == 204
    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    revoked_response = client.post(
        f"/api/v1/repositories/invitations/{mismatch_token}/accept",
        headers=_browser_headers(invited_user_csrf),
    )
    assert revoked_response.status_code == 404
    assert mismatch_token not in revoked_response.text

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][0],
    )
    already_has_access = _create_invitation(
        client,
        repository_id,
        owner_csrf,
        email="repo-user-1@example.test",
    )
    assert already_has_access.status_code == 409


def test_repository_invitations_reject_invalid_mismatched_revoked_expired_and_unready(
    repository_client,
) -> None:
    factory = repository_client["factory"]
    owner_id, invited_user_id = repository_client["user_ids"]
    client = repository_client["client"]
    owner_csrf, _ = repository_client["csrf_tokens"]
    created = _create(client, owner_csrf, "invitation-validation")
    assert created.status_code == 201
    repository_id = uuid.UUID(created.json()["id"])

    revoked = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="repo-user-1@example.test",
        role="admin",
        expires_in_days=7,
        request_id="repository-invite-revoked",
    )
    with pytest.raises(RepositoryPermissionError):
        accept_repository_invitation(
            factory,
            revoked.token,
            owner_id,
            request_id="repository-invite-mismatch",
        )
    with factory() as db_session:
        stored = db_session.get(Invitation, revoked.invitation.id)
        assert stored is not None
        assert stored.status == "pending"

    revoke_repository_invitation(
        factory,
        repository_id,
        owner_id,
        revoked.invitation.id,
        request_id="repository-invite-revoke",
    )
    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            revoked.token,
            invited_user_id,
            request_id="repository-invite-revoked-accept",
        )
    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            "malformed-token",
            invited_user_id,
            request_id="repository-invite-malformed",
        )

    expired = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="expired-invite@example.test",
        role="reader",
        expires_in_days=7,
        request_id="repository-invite-expired",
    )
    with transactional_session(factory) as db_session:
        stored = db_session.get(Invitation, expired.invitation.id)
        assert stored is not None
        stored.created_at = datetime.now(UTC) - timedelta(days=3)
        stored.expires_at = datetime.now(UTC) - timedelta(days=1)
    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            expired.token,
            invited_user_id,
            request_id="repository-invite-expired-accept",
        )
    with factory() as db_session:
        stored = db_session.get(Invitation, expired.invitation.id)
        assert stored is not None
        assert stored.status == "expired"
        assert stored.accepted_at is None

    unavailable = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="repo-user-1@example.test",
        role="reader",
        expires_in_days=7,
        request_id="repository-invite-lifecycle",
    )
    with transactional_session(factory) as db_session:
        repository = db_session.get(Repository, repository_id)
        assert repository is not None
        repository.lifecycle_state = "deleting"
    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            unavailable.token,
            invited_user_id,
            request_id="repository-invite-unready",
        )
    with factory() as db_session:
        stored = db_session.get(Invitation, unavailable.invitation.id)
        assert stored is not None
        assert stored.status == "pending"
    with transactional_session(factory) as db_session:
        repository = db_session.get(Repository, repository_id)
        assert repository is not None
        repository.lifecycle_state = "ready"
    permission = accept_repository_invitation(
        factory,
        unavailable.token,
        invited_user_id,
        request_id="repository-invite-ready",
    )
    assert permission.role == "reader"

    pending_delete = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="pending-deletion@example.test",
        role="reader",
        expires_in_days=7,
        request_id="repository-invite-pending-delete",
    )
    with transactional_session(factory) as db_session:
        repository = db_session.get(Repository, repository_id)
        assert repository is not None
        repository.lifecycle_state = "deleting"
    with pytest.raises(RepositoryNotFoundError):
        create_repository_invitation(
            factory,
            repository_id,
            owner_id,
            target_email="cannot-invite@example.test",
            role="reader",
            expires_in_days=7,
            request_id="repository-invite-create-deleting",
        )
    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            pending_delete.token,
            invited_user_id,
            request_id="repository-invite-accept-deleting",
        )
    with factory() as db_session:
        stored = db_session.get(Invitation, pending_delete.invitation.id)
        assert stored is not None
        assert stored.status == "pending"


def test_repository_invitation_accept_reloads_status_after_repository_lock(
    repository_client,
    monkeypatch,
) -> None:
    factory = repository_client["factory"]
    owner_id, invited_user_id = repository_client["user_ids"]
    client = repository_client["client"]
    owner_csrf = repository_client["csrf_tokens"][0]
    created = _create(client, owner_csrf, "invitation-lock-recheck")
    assert created.status_code == 201
    repository_id = uuid.UUID(created.json()["id"])
    issued = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="repo-user-1@example.test",
        role="reader",
        expires_in_days=7,
        request_id="repository-invitation-lock-recheck",
    )
    original_lock = repository_invitation_service._lock_repository

    def revoke_before_repository_lock(db_session, current_repository_id):
        db_session.execute(
            update(Invitation)
            .where(Invitation.id == issued.invitation.id)
            .values(status="revoked", revoked_at=datetime.now(UTC)),
            execution_options={"synchronize_session": False},
        )
        return original_lock(db_session, current_repository_id)

    monkeypatch.setattr(
        repository_invitation_service,
        "_lock_repository",
        revoke_before_repository_lock,
    )

    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            issued.token,
            invited_user_id,
            request_id="repository-accept-revoked-during-lock",
        )

    with factory() as db_session:
        assert db_session.get(
            RepositoryUserPermission,
            (repository_id, invited_user_id),
        ) is None


def test_repository_invitation_accept_reloads_lifecycle_after_repository_lock(
    repository_client,
    monkeypatch,
) -> None:
    factory = repository_client["factory"]
    owner_id, invited_user_id = repository_client["user_ids"]
    client = repository_client["client"]
    owner_csrf = repository_client["csrf_tokens"][0]
    created = _create(client, owner_csrf, "invitation-lifecycle-recheck")
    assert created.status_code == 201
    repository_id = uuid.UUID(created.json()["id"])
    issued = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="repo-user-1@example.test",
        role="reader",
        expires_in_days=7,
        request_id="repository-invitation-lifecycle-recheck",
    )
    original_lock = repository_invitation_service._lock_repository

    def mark_deleting_before_repository_lock(db_session, current_repository_id):
        db_session.execute(
            update(Repository)
            .where(Repository.id == repository_id)
            .values(lifecycle_state="deleting"),
            execution_options={"synchronize_session": False},
        )
        return original_lock(db_session, current_repository_id)

    monkeypatch.setattr(
        repository_invitation_service,
        "_lock_repository",
        mark_deleting_before_repository_lock,
    )

    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            factory,
            issued.token,
            invited_user_id,
            request_id="repository-accept-deleting-during-lock",
        )

    with factory() as db_session:
        assert db_session.get(
            RepositoryUserPermission,
            (repository_id, invited_user_id),
        ) is None


def test_repository_access_reloads_lifecycle_after_repository_lock(
    repository_client,
    monkeypatch,
) -> None:
    factory = repository_client["factory"]
    owner_id = repository_client["user_ids"][0]
    client = repository_client["client"]
    owner_csrf = repository_client["csrf_tokens"][0]
    created = _create(client, owner_csrf, "repository-access-lifecycle-recheck")
    assert created.status_code == 201
    repository_id = uuid.UUID(created.json()["id"])
    original_lock = repository_service._lock_repository

    def mark_deleting_before_repository_lock(db_session, current_repository_id):
        db_session.execute(
            update(Repository)
            .where(Repository.id == repository_id)
            .values(lifecycle_state="deleting"),
            execution_options={"synchronize_session": False},
        )
        return original_lock(db_session, current_repository_id)

    monkeypatch.setattr(
        repository_service,
        "_lock_repository",
        mark_deleting_before_repository_lock,
    )

    with pytest.raises(RepositoryNotFoundError):
        get_repository_for_access(factory, repository_id, owner_id)


def test_expired_repository_invitations_do_not_block_reissue_or_appear_pending(
    repository_client,
) -> None:
    factory = repository_client["factory"]
    owner_id = repository_client["user_ids"][0]
    client = repository_client["client"]
    owner_csrf = repository_client["csrf_tokens"][0]
    created = _create(client, owner_csrf, "invitation-reissue")
    repository_id = uuid.UUID(created.json()["id"])
    stale = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="stale-repository-invite@example.test",
        role="reader",
        expires_in_days=7,
        request_id="stale-repository-invitation",
    )
    with transactional_session(factory) as db_session:
        invitation = db_session.get(Invitation, stale.invitation.id)
        assert invitation is not None
        invitation.created_at = datetime.now(UTC) - timedelta(days=3)
        invitation.expires_at = datetime.now(UTC) - timedelta(days=2)

    listed, total = list_repository_invitations(
        factory, repository_id, owner_id, limit=100, offset=0
    )
    assert total == 0
    assert listed == []

    replacement = create_repository_invitation(
        factory,
        repository_id,
        owner_id,
        target_email="stale-repository-invite@example.test",
        role="writer",
        expires_in_days=7,
        request_id="replacement-repository-invitation",
    )
    with factory() as db_session:
        assert db_session.get(Invitation, stale.invitation.id).status == "expired"
        assert db_session.get(Invitation, replacement.invitation.id).status == "pending"


def test_repository_invitation_mutations_require_origin_and_csrf(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    created = _create(client, csrf, "invitation-csrf")
    assert created.status_code == 201
    repository_id = created.json()["id"]
    invitations_path = f"/api/v1/repositories/{repository_id}/invitations"

    missing_origin = client.post(
        invitations_path,
        json={"target_email": "csrf@example.test", "role": "reader"},
    )
    assert missing_origin.status_code == 403
    missing_csrf = client.post(
        invitations_path,
        headers={"Origin": "https://hub.example.test"},
        json={"target_email": "csrf@example.test", "role": "reader"},
    )
    assert missing_csrf.status_code == 403

    issued = _create_invitation(
        client, repository_id, csrf, email="csrf@example.test"
    )
    assert issued.status_code == 201
    token = issued.json()["token"]
    invitation_id = issued.json()["id"]
    missing_revoke_origin = client.delete(f"{invitations_path}/{invitation_id}")
    assert missing_revoke_origin.status_code == 403
    missing_revoke_csrf = client.delete(
        f"{invitations_path}/{invitation_id}",
        headers={"Origin": "https://hub.example.test"},
    )
    assert missing_revoke_csrf.status_code == 403
    missing_accept_origin = client.post(
        f"/api/v1/repositories/invitations/{token}/accept",
        headers={"X-CSRF-Token": csrf},
    )
    assert missing_accept_origin.status_code == 403
    assert token not in missing_accept_origin.text

    revoked = client.delete(
        f"{invitations_path}/{invitation_id}",
        headers=_browser_headers(csrf),
    )
    assert revoked.status_code == 204
    with repository_client["factory"]() as db_session:
        audit_event = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == repository_id,
                AuditEvent.action == "repository.invitation_revoked",
            )
        )
    assert audit_event is not None
    assert audit_event.event_metadata == {"invitation_id": invitation_id}
    with pytest.raises(RepositoryNotFoundError):
        accept_repository_invitation(
            repository_client["factory"],
            token,
            repository_client["user_ids"][1],
            request_id="repository-invite-csrf-revoked",
        )


def test_repository_direct_permissions_do_not_grant_management_to_recipient(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    target_user_id = str(repository_client["user_ids"][1])
    created = _create(client, csrf, "permission-management-boundary")
    assert created.status_code == 201
    repository_id = created.json()["id"]
    permissions_path = f"/api/v1/repositories/{repository_id}/permissions"
    granted = client.post(
        permissions_path,
        headers=_browser_headers(csrf),
        json={"user_id": target_user_id, "role": "writer"},
    )
    assert granted.status_code == 201

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    recipient_list = client.get(permissions_path)
    assert recipient_list.status_code == 404
    assert recipient_list.json()["error"]["code"] == "repository_not_found"


def test_repository_browse_requires_effective_access_and_reads_core_objects(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    target_user_id = str(repository_client["user_ids"][1])
    created = _create(client, csrf, "browse-repo")
    assert created.status_code == 201
    repository_id = created.json()["id"]
    with repository_client["factory"]() as db_session:
        repository = db_session.get(Repository, uuid.UUID(repository_id))
        assert repository is not None
        storage_path = repository_client["storage_root"] / f"{repository.storage_key}.git"

    core_repository = discover_repository(storage_path)
    readme_id = write_object(core_repository.objects_dir, "blob", b"Hello CommitVerse\n")
    nested_id = write_object(core_repository.objects_dir, "blob", b"nested content\n")
    nested_tree_id = write_object(
        core_repository.objects_dir,
        "tree",
        serialize_tree((TreeEntry("100644", b"note.txt", nested_id),)),
    )
    root_tree_id = write_object(
        core_repository.objects_dir,
        "tree",
        serialize_tree(
            (
                TreeEntry("100644", b"README.md", readme_id),
                TreeEntry("40000", b"docs", nested_tree_id),
            )
        ),
    )
    identity = CommitIdentity("CommitVerse Test", "test@example.test", 1_700_000_000, 0)
    commit_id = write_commit(
        core_repository.objects_dir,
        Commit(root_tree_id, (), identity, identity, b"Initial browser snapshot\n"),
    )
    write_ref(core_repository, "refs/heads/main", commit_id)
    write_ref(core_repository, "refs/heads/feature/docs", commit_id)
    write_ref(core_repository, "refs/tags/v1.0.0", commit_id)

    base_path = f"/api/v1/repositories/{repository_id}"
    refs = client.get(f"{base_path}/refs")
    assert refs.status_code == 200
    assert [(item["kind"], item["name"]) for item in refs.json()["refs"]] == [
        ("branch", "feature/docs"),
        ("branch", "main"),
        ("tag", "v1.0.0"),
    ]
    tree = client.get(f"{base_path}/tree")
    assert tree.status_code == 200
    assert tree.json()["commit_id"] == commit_id
    assert {entry["name"] for entry in tree.json()["entries"]} == {"README.md", "docs"}

    nested_tree = client.get(f"{base_path}/tree", params={"path": "docs"})
    assert nested_tree.status_code == 200
    assert nested_tree.json()["entries"][0]["name"] == "note.txt"
    blob = client.get(f"{base_path}/blob", params={"path": "README.md"})
    assert blob.status_code == 200
    assert blob.json()["content"] == "Hello CommitVerse\n"
    history = client.get(f"{base_path}/commits")
    assert history.status_code == 200
    assert history.json()["commits"][0]["object_id"] == commit_id
    detail = client.get(f"{base_path}/commits/{commit_id}")
    assert detail.status_code == 200
    assert detail.json()["tree_id"] == root_tree_id
    assert detail.json()["message"] == "Initial browser snapshot\n"
    unreachable = client.get(f"{base_path}/commits/{'f' * 40}")
    assert unreachable.status_code == 404
    selected = client.get(f"{base_path}/tree", params={"ref": "refs/tags/v1.0.0"})
    assert selected.status_code == 200
    assert selected.json()["commit_id"] == commit_id
    invalid_ref = client.get(f"{base_path}/tree", params={"ref": "refs/remotes/origin/main"})
    assert invalid_ref.status_code == 404

    updated_readme_id = write_object(core_repository.objects_dir, "blob", b"Updated CommitVerse\n")
    updated_root_tree_id = write_object(
        core_repository.objects_dir,
        "tree",
        serialize_tree(
            (
                TreeEntry("100644", b"README.md", updated_readme_id),
                TreeEntry("40000", b"docs", nested_tree_id),
            )
        ),
    )
    updated_commit_id = write_commit(
        core_repository.objects_dir,
        Commit(updated_root_tree_id, (commit_id,), identity, identity, b"Update README\n"),
    )
    write_ref(core_repository, "refs/heads/main", updated_commit_id)
    diff = client.get(f"{base_path}/commits/{updated_commit_id}/diff")
    assert diff.status_code == 200
    assert diff.json()["base_commit_id"] == commit_id
    assert diff.json()["files"][0]["path"] == "README.md"
    assert "-Hello CommitVerse" in diff.json()["files"][0]["patch"]
    assert "+Updated CommitVerse" in diff.json()["files"][0]["patch"]

    traversal = client.get(f"{base_path}/blob", params={"path": "../README.md"})
    assert traversal.status_code == 404

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    denied = client.get(f"{base_path}/tree")
    assert denied.status_code == 404

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][0],
    )
    granted = client.post(
        f"{base_path}/permissions",
        headers=_browser_headers(csrf),
        json={"user_id": target_user_id, "role": "reader"},
    )
    assert granted.status_code == 201
    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    permitted = client.get(f"{base_path}/tree")
    assert permitted.status_code == 200

    client.cookies.delete(repository_client["settings"].auth_cookie.name)
    anonymous_private = client.get(f"{base_path}/tree")
    assert anonymous_private.status_code == 404
    made_public = client.patch(
        base_path,
        headers=_browser_headers(csrf),
        json={"visibility": "public"},
    )
    assert made_public.status_code == 401
    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][0],
    )
    made_public = client.patch(
        base_path,
        headers=_browser_headers(csrf),
        json={"visibility": "public"},
    )
    assert made_public.status_code == 200
    client.cookies.delete(repository_client["settings"].auth_cookie.name)
    anonymous_public = client.get(f"{base_path}/tree")
    assert anonymous_public.status_code == 200


def test_repository_detail_and_updates_require_owner(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    created = _create(client, csrf, "editable", description="original")
    repository_id = created.json()["id"]
    with repository_client["factory"]() as db_session:
        row = db_session.get(Repository, uuid.UUID(repository_id))
        assert row is not None
        storage_key = row.storage_key
    original_path = repository_client["storage_root"] / f"{storage_key}.git"

    detail = client.get(f"/api/v1/repositories/{repository_id}")
    assert detail.status_code == 200
    updated = client.patch(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
        json={"name": "renamed", "description": None, "visibility": "public"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "renamed"
    assert updated.json()["description"] is None
    assert updated.json()["visibility"] == "public"
    assert original_path.is_dir()
    assert discover_repository(original_path).bare

    forbidden_field = client.patch(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
        json={"owner_user_id": str(repository_client["user_ids"][1])},
    )
    assert forbidden_field.status_code == 422
    empty_patch = client.patch(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
        json={},
    )
    assert empty_patch.status_code == 422

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    assert client.get(f"/api/v1/repositories/{repository_id}").status_code == 404
    denied_update = client.patch(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(repository_client["csrf_tokens"][1]),
        json={"visibility": "private"},
    )
    assert denied_update.status_code == 404
    assert original_path.is_dir()


def test_duplicate_names_invalid_values_and_core_failure_are_recoverable(
    repository_client,
    monkeypatch,
) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    created = _create(client, csrf, "same-name")
    assert created.status_code == 201
    duplicate = _create(client, csrf, "SAME-NAME")
    assert duplicate.status_code == 409
    invalid_name = _create(client, csrf, "../outside")
    assert invalid_name.status_code == 422
    invalid_visibility = _create(client, csrf, "private-repo", visibility="hidden")
    assert invalid_visibility.status_code == 422
    long_description = _create(client, csrf, "too-long", description="x" * 1001)
    assert long_description.status_code == 422

    from commitverse_hub.repositories import service

    def fail_initialization(*_args, **_kwargs):
        raise RepositoryStorageError("simulated")

    monkeypatch.setattr(service, "create_bare_repository", fail_initialization)
    failed = _create(client, csrf, "retryable")
    assert failed.status_code == 503
    with repository_client["factory"]() as db_session:
        row = db_session.scalar(
            select(Repository).where(
                Repository.owner_user_id == repository_client["user_ids"][0],
                Repository.slug == "retryable",
            )
        )
        assert row is not None
        assert row.lifecycle_state == "error"

    monkeypatch.undo()
    retried = _create(client, csrf, "retryable")
    assert retried.status_code == 201
    assert retried.json()["name"] == "retryable"


def test_repository_delete_is_owner_only_safe_and_idempotent(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    created = _create(client, csrf, "delete-me")
    repository_id = created.json()["id"]
    with repository_client["factory"]() as db_session:
        repository = db_session.get(Repository, uuid.UUID(repository_id))
        assert repository is not None
        storage_key = repository.storage_key
    path = repository_client["storage_root"] / f"{storage_key}.git"
    assert path.is_dir()

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][1],
    )
    denied = client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(repository_client["csrf_tokens"][1]),
    )
    assert denied.status_code == 404
    assert path.is_dir()

    client.cookies.set(
        repository_client["settings"].auth_cookie.name,
        repository_client["session_tokens"][0],
    )
    deleted = client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
    )
    assert deleted.status_code == 204
    assert not path.exists()
    assert client.get(f"/api/v1/repositories/{repository_id}").status_code == 404
    assert client.get("/api/v1/repositories").json()["total"] == 0
    assert client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
    ).status_code == 204

    with repository_client["factory"]() as db_session:
        tombstone = db_session.get(Repository, uuid.UUID(repository_id))
        assert tombstone is not None
        assert tombstone.lifecycle_state == "deleted"
        assert tombstone.slug == f"deleted~{uuid.UUID(repository_id).hex}"
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleting",
                AuditEvent.target_id == repository_id,
            )
        ) == 1
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleted",
                AuditEvent.target_id == repository_id,
            )
        ) == 1


def test_repository_delete_refuses_symlinked_storage_target(repository_client) -> None:
    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    created = _create(client, csrf, "symlink-target")
    repository_id = created.json()["id"]
    with repository_client["factory"]() as db_session:
        repository = db_session.get(Repository, uuid.UUID(repository_id))
        assert repository is not None
        storage_key = repository.storage_key

    outside = repository_client["storage_root"].parent / "outside-repository.git"
    outside.mkdir()
    initialize_repository(outside, bare=True)
    path = repository_client["storage_root"] / f"{storage_key}.git"
    shutil.rmtree(path)
    path.symlink_to(outside, target_is_directory=True)

    response = client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
    )
    assert response.status_code == 503
    assert outside.is_dir()
    with repository_client["factory"]() as db_session:
        repository = db_session.get(Repository, uuid.UUID(repository_id))
        assert repository is not None
        assert repository.lifecycle_state == "deleting"


def test_repository_mutations_require_exact_origin_and_csrf(repository_client) -> None:
    client = repository_client["client"]
    missing_csrf = client.post(
        "/api/v1/repositories",
        headers={"Origin": "https://hub.example.test"},
        json={"name": "missing-csrf"},
    )
    assert missing_csrf.status_code == 403

    wrong_origin = client.post(
        "/api/v1/repositories",
        headers={
            "Origin": "https://attacker.example.test",
            "X-CSRF-Token": repository_client["csrf_tokens"][0],
        },
        json={"name": "wrong-origin"},
    )
    assert wrong_origin.status_code == 403


def test_concurrent_personal_creation_has_one_winner(repository_client) -> None:
    factory = repository_client["factory"]
    storage_root = repository_client["storage_root"]
    owner_user_id = repository_client["user_ids"][0]

    def create():
        return create_personal_repository(
            factory,
            storage_root,
            owner_user_id,
            name="concurrent",
            description=None,
            visibility="private",
            request_id="concurrent-test",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _try_create(create), range(2)))

    assert sum(isinstance(result, Repository) for result in results) == 1
    assert sum(isinstance(result, RepositoryConflictError) for result in results) == 1
    with factory() as db_session:
        assert db_session.scalar(
            select(func.count()).select_from(Repository).where(
                Repository.owner_user_id == owner_user_id,
                Repository.slug == "concurrent",
                Repository.lifecycle_state == "ready",
            )
        ) == 1


def _try_create(create):
    try:
        return create()
    except RepositoryConflictError as exc:
        return exc


def test_failed_delete_keeps_retryable_lifecycle_state(
    repository_client,
    monkeypatch,
) -> None:
    from commitverse_hub.repositories import service

    client = repository_client["client"]
    csrf = repository_client["csrf_tokens"][0]
    created = _create(client, csrf, "delete-retry")
    repository_id = created.json()["id"]

    def fail_delete(*_args, **_kwargs):
        raise RepositoryStorageError("simulated storage failure")

    monkeypatch.setattr(service, "delete_bare_repository", fail_delete)
    failed = client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
    )
    assert failed.status_code == 503
    with repository_client["factory"]() as db_session:
        row = db_session.get(Repository, uuid.UUID(repository_id))
        assert row is not None
        assert row.lifecycle_state == "deleting"

    monkeypatch.undo()
    retried = client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=_browser_headers(csrf),
    )
    assert retried.status_code == 204


def test_database_failure_after_core_publication_cleans_exact_repository(
    repository_client,
    monkeypatch,
) -> None:
    from contextlib import contextmanager

    from commitverse_hub.repositories import service

    original_transaction = service.transactional_session
    transaction_count = 0

    @contextmanager
    def fail_ready_publication(factory):
        nonlocal transaction_count
        transaction_count += 1
        if transaction_count == 2:
            raise SQLAlchemyError("simulated database failure")
        with original_transaction(factory) as db_session:
            yield db_session

    monkeypatch.setattr(service, "transactional_session", fail_ready_publication)
    response = _create(
        repository_client["client"],
        repository_client["csrf_tokens"][0],
        "db-failure",
    )
    assert response.status_code == 503
    assert transaction_count == 4

    with repository_client["factory"]() as db_session:
        repository = db_session.scalar(
            select(Repository).where(
                Repository.owner_user_id == repository_client["user_ids"][0],
                Repository.slug == "db-failure",
            )
        )
        assert repository is not None
        assert repository.lifecycle_state == "error"
        assert not (
            repository_client["storage_root"] / f"{repository.storage_key}.git"
        ).exists()


def test_organization_repository_lifecycle_and_audit(repository_client) -> None:
    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(factory, user_ids)
    actor_user_id = user_ids[1]

    repository = create_organization_repository(
        factory,
        repository_client["storage_root"],
        organization_id,
        actor_user_id,
        name="team-repository",
        description="Organization-owned",
        visibility="private",
        request_id="org-repo-create",
    )
    repository_path = (
        repository_client["storage_root"] / f"{repository.storage_key}.git"
    )
    assert repository.lifecycle_state == "ready"
    assert repository.owner_user_id is None
    assert repository.owner_organization_id == organization_id
    assert repository.created_by == actor_user_id
    assert discover_repository(repository_path).bare

    delete_organization_repository(
        factory,
        repository_client["storage_root"],
        repository.id,
        organization_id,
        actor_user_id,
        request_id="org-repo-delete",
    )
    assert not repository_path.exists()
    with factory() as db_session:
        deleted = db_session.get(Repository, repository.id)
        assert deleted is not None
        assert deleted.lifecycle_state == "deleted"
        assert deleted.slug == f"deleted~{repository.id.hex}"
        actions = list(
            db_session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.target_id == str(repository.id)
                )
            )
        )
    assert actions.count("repository.provisioning") == 1
    assert actions.count("repository.created") == 1
    assert actions.count("repository.deleting") == 1
    assert actions.count("repository.deleted") == 1

    delete_organization_repository(
        factory,
        repository_client["storage_root"],
        repository.id,
        organization_id,
        actor_user_id,
        request_id="org-repo-delete-retry",
    )
    with factory() as db_session:
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleted",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1


def test_organization_repository_authorization_is_checked_in_transactions(
    repository_client,
    monkeypatch,
) -> None:
    from commitverse_hub.repositories import service

    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(
        factory,
        user_ids,
        second_role="member",
    )

    def storage_must_not_be_touched(*_args, **_kwargs):
        raise AssertionError("Unauthorized operation reached repository storage.")

    monkeypatch.setattr(service, "create_bare_repository", storage_must_not_be_touched)
    with pytest.raises(RepositoryPermissionError):
        create_organization_repository(
            factory,
            repository_client["storage_root"],
            organization_id,
            user_ids[1],
            name="denied-create",
            description=None,
            visibility="private",
            request_id="denied-create",
        )

    monkeypatch.undo()
    repository = create_organization_repository(
        factory,
        repository_client["storage_root"],
        organization_id,
        user_ids[0],
        name="denied-delete",
        description=None,
        visibility="private",
        request_id="owner-create",
    )
    repository_path = (
        repository_client["storage_root"] / f"{repository.storage_key}.git"
    )
    with pytest.raises(RepositoryPermissionError):
        delete_organization_repository(
            factory,
            repository_client["storage_root"],
            repository.id,
            organization_id,
            user_ids[1],
            request_id="denied-delete",
        )
    assert repository_path.is_dir()
    with factory() as db_session:
        stored = db_session.get(Repository, repository.id)
        assert stored is not None
        assert stored.lifecycle_state == "ready"


def test_organization_repository_provisioning_failure_is_retryable(
    repository_client,
    monkeypatch,
) -> None:
    from commitverse_hub.repositories import service

    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(factory, user_ids)

    def fail_initialization(*_args, **_kwargs):
        raise RepositoryStorageError("simulated organization storage failure")

    monkeypatch.setattr(service, "create_bare_repository", fail_initialization)
    with pytest.raises(RepositoryOperationError):
        create_organization_repository(
            factory,
            repository_client["storage_root"],
            organization_id,
            user_ids[1],
            name="retry-organization-repo",
            description=None,
            visibility="private",
            request_id="org-provisioning-failure",
        )

    with factory() as db_session:
        repository = db_session.scalar(
            select(Repository).where(
                Repository.owner_organization_id == organization_id,
                Repository.slug == "retry-organization-repo",
            )
        )
        assert repository is not None
        repository_id = repository.id
        assert repository.lifecycle_state == "error"
        actions = list(
            db_session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.target_id == str(repository_id)
                )
            )
        )
    assert actions.count("repository.provisioning") == 1
    assert actions.count("repository.provisioning_failed") == 1

    monkeypatch.undo()
    retried = create_organization_repository(
        factory,
        repository_client["storage_root"],
        organization_id,
        user_ids[0],
        name="retry-organization-repo",
        description=None,
        visibility="private",
        request_id="org-provisioning-retry",
    )
    assert retried.lifecycle_state == "ready"
    with factory() as db_session:
        actions = list(
            db_session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.target_id == str(repository_id)
                )
            )
        )
    assert actions.count("repository.provisioning") == 2
    assert actions.count("repository.provisioning_failed") == 1
    assert actions.count("repository.created") == 1


def test_organization_repository_cleanup_failure_retries_without_duplicate_audit(
    repository_client,
    monkeypatch,
) -> None:
    from commitverse_hub.repositories import service

    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(factory, user_ids)
    repository = create_organization_repository(
        factory,
        repository_client["storage_root"],
        organization_id,
        user_ids[0],
        name="retry-cleanup",
        description=None,
        visibility="private",
        request_id="cleanup-create",
    )
    original_delete = service.delete_bare_repository
    cleanup_calls = 0

    def fail_first_cleanup(*args, **kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise RepositoryStorageError("simulated cleanup failure")
        return original_delete(*args, **kwargs)

    monkeypatch.setattr(service, "delete_bare_repository", fail_first_cleanup)
    with pytest.raises(RepositoryOperationError):
        delete_organization_repository(
            factory,
            repository_client["storage_root"],
            repository.id,
            organization_id,
            user_ids[0],
            request_id="cleanup-failure",
        )

    with factory() as db_session:
        pending = db_session.get(Repository, repository.id)
        assert pending is not None
        assert pending.lifecycle_state == "deleting"
        assert pending.slug == "retry-cleanup"

    monkeypatch.undo()
    delete_organization_repository(
        factory,
        repository_client["storage_root"],
        repository.id,
        organization_id,
        user_ids[1],
        request_id="cleanup-retry",
    )
    with factory() as db_session:
        finalized = db_session.get(Repository, repository.id)
        assert finalized is not None
        assert finalized.lifecycle_state == "deleted"
        assert finalized.slug == f"deleted~{repository.id.hex}"
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleting",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleted",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1


def test_organization_repository_finalization_failure_retries_idempotently(
    repository_client,
    monkeypatch,
) -> None:
    from contextlib import contextmanager

    from commitverse_hub.repositories import service

    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(factory, user_ids)
    repository = create_organization_repository(
        factory,
        repository_client["storage_root"],
        organization_id,
        user_ids[0],
        name="retry-finalization",
        description=None,
        visibility="private",
        request_id="finalize-create",
    )
    repository_path = (
        repository_client["storage_root"] / f"{repository.storage_key}.git"
    )
    original_transaction = service.transactional_session
    transaction_count = 0

    @contextmanager
    def fail_finalization(factory):
        nonlocal transaction_count
        transaction_count += 1
        if transaction_count == 2:
            raise SQLAlchemyError("simulated finalization failure")
        with original_transaction(factory) as db_session:
            yield db_session

    monkeypatch.setattr(service, "transactional_session", fail_finalization)
    with pytest.raises(RepositoryOperationError):
        delete_organization_repository(
            factory,
            repository_client["storage_root"],
            repository.id,
            organization_id,
            user_ids[0],
            request_id="finalize-failure",
        )
    assert not repository_path.exists()
    with factory() as db_session:
        pending = db_session.get(Repository, repository.id)
        assert pending is not None
        assert pending.lifecycle_state == "deleting"
        assert pending.slug == "retry-finalization"
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleted",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 0

    monkeypatch.undo()
    delete_organization_repository(
        factory,
        repository_client["storage_root"],
        repository.id,
        organization_id,
        user_ids[1],
        request_id="finalize-retry",
    )
    with factory() as db_session:
        finalized = db_session.get(Repository, repository.id)
        assert finalized is not None
        assert finalized.lifecycle_state == "deleted"
        assert finalized.slug == f"deleted~{repository.id.hex}"
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleting",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleted",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1


def test_organization_repository_revalidates_membership_and_lock_order(
    repository_client,
    monkeypatch,
) -> None:
    from commitverse_hub.repositories import service

    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(factory, user_ids)
    lock_order: list[str] = []
    original_lock_organization = service._lock_organization
    original_lock_repository = service._lock_repository
    original_lock_existing = service._lock_existing_repository
    original_create_storage = service.create_bare_repository

    def lock_organization(*args, **kwargs):
        lock_order.append("organization")
        return original_lock_organization(*args, **kwargs)

    def lock_repository(*args, **kwargs):
        lock_order.append("repository")
        return original_lock_repository(*args, **kwargs)

    def lock_existing_repository(*args, **kwargs):
        lock_order.append("repository")
        return original_lock_existing(*args, **kwargs)

    def create_then_revoke_role(*args, **kwargs):
        published = original_create_storage(*args, **kwargs)
        with transactional_session(factory) as db_session:
            membership = db_session.get(
                OrganizationMembership,
                {
                    "organization_id": organization_id,
                    "user_id": user_ids[0],
                },
            )
            assert membership is not None
            membership.role = "member"
        return published

    monkeypatch.setattr(service, "_lock_organization", lock_organization)
    monkeypatch.setattr(service, "_lock_repository", lock_repository)
    monkeypatch.setattr(
        service, "_lock_existing_repository", lock_existing_repository
    )
    monkeypatch.setattr(
        service, "create_bare_repository", create_then_revoke_role
    )

    with pytest.raises(RepositoryPermissionError):
        create_organization_repository(
            factory,
            repository_client["storage_root"],
            organization_id,
            user_ids[0],
            name="authorization-revalidation",
            description=None,
            visibility="private",
            request_id="role-revalidation",
        )
    with factory() as db_session:
        repository = db_session.scalar(
            select(Repository).where(
                Repository.owner_organization_id == organization_id,
                Repository.slug == "authorization-revalidation",
            )
        )
        assert repository is not None
        assert repository.lifecycle_state == "error"
        assert not (
            repository_client["storage_root"] / f"{repository.storage_key}.git"
        ).exists()
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.created",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 0

    monkeypatch.setattr(service, "create_bare_repository", original_create_storage)
    repository = create_organization_repository(
        factory,
        repository_client["storage_root"],
        organization_id,
        user_ids[1],
        name="authorization-revalidation",
        description=None,
        visibility="private",
        request_id="admin-retry",
    )
    delete_organization_repository(
        factory,
        repository_client["storage_root"],
        repository.id,
        organization_id,
        user_ids[1],
        request_id="admin-delete",
    )

    latest_organization_lock = -1
    for index, lock in enumerate(lock_order):
        if lock == "organization":
            latest_organization_lock = index
        elif lock == "repository":
            assert latest_organization_lock < index


def test_organization_repository_cleans_storage_published_after_delete(
    repository_client,
    monkeypatch,
) -> None:
    from commitverse_hub.repositories import service

    factory = repository_client["factory"]
    user_ids = repository_client["user_ids"]
    organization_id = _create_test_organization(factory, user_ids)
    original_create_storage = service.create_bare_repository
    storage_keys: list[str] = []
    repository_ids: list[uuid.UUID] = []

    def delete_before_late_storage_publication(
        storage_root,
        storage_key,
        *,
        allow_existing=False,
    ):
        storage_keys.append(storage_key)
        with factory() as db_session:
            repository = db_session.scalar(
                select(Repository).where(
                    Repository.owner_organization_id == organization_id,
                    Repository.slug == "late-storage-publication",
                )
            )
            assert repository is not None
            repository_id = repository.id
            repository_ids.append(repository_id)
        delete_organization_repository(
            factory,
            storage_root,
            repository_id,
            organization_id,
            user_ids[0],
            request_id="concurrent-delete",
        )
        return original_create_storage(
            storage_root,
            storage_key,
            allow_existing=allow_existing,
        )

    monkeypatch.setattr(
        service,
        "create_bare_repository",
        delete_before_late_storage_publication,
    )
    with pytest.raises(RepositoryOperationError):
        create_organization_repository(
            factory,
            repository_client["storage_root"],
            organization_id,
            user_ids[0],
            name="late-storage-publication",
            description=None,
            visibility="private",
            request_id="concurrent-create",
        )

    with factory() as db_session:
        repository = db_session.get(Repository, repository_ids[0])
        assert repository is not None
        assert repository.lifecycle_state == "deleted"
        assert repository.slug == f"deleted~{repository.id.hex}"
        assert db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "repository.deleted",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1
        assert not (
            repository_client["storage_root"] / f"{storage_keys[0]}.git"
        ).exists()


def test_storage_rejects_symlinked_root(tmp_path) -> None:
    canonical_tmp_path = tmp_path.resolve()
    actual_root = canonical_tmp_path / "actual"
    actual_root.mkdir()
    linked_root = canonical_tmp_path / "linked"
    linked_root.symlink_to(actual_root, target_is_directory=True)

    with pytest.raises(RepositoryStorageError):
        create_bare_repository(linked_root, uuid.uuid4().hex)


def test_storage_only_reuses_existing_destination_for_recovery(tmp_path) -> None:
    storage_root = (tmp_path / "repositories").resolve()
    storage_key = uuid.uuid4().hex

    assert create_bare_repository(storage_root, storage_key)
    with pytest.raises(RepositoryStorageError, match="destination already exists"):
        create_bare_repository(storage_root, storage_key)
    assert not create_bare_repository(
        storage_root,
        storage_key,
        allow_existing=True,
    )


def test_storage_delete_is_idempotent_when_another_worker_removes_the_path(
    tmp_path,
    monkeypatch,
) -> None:
    import shutil as shutil_module

    storage_root = (tmp_path / "repositories").resolve()
    storage_key = uuid.uuid4().hex
    assert create_bare_repository(storage_root, storage_key)
    original_rmtree = shutil_module.rmtree

    def remove_then_report_missing(path):
        original_rmtree(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(shutil_module, "rmtree", remove_then_report_missing)
    assert delete_bare_repository(storage_root, storage_key) is False
    assert not (storage_root / f"{storage_key}.git").exists()


def test_postgresql_repository_lifecycle_in_isolated_schema(tmp_path) -> None:
    database_url = os.environ.get("HUB_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("HUB_TEST_DATABASE_URL is not configured.")

    engine = create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    schema = f"hub_repository_test_{uuid.uuid4().hex}"
    storage_root = tmp_path / "postgres-repositories"
    try:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped_connection = connection.execution_options(
            schema_translate_map={None: schema}
        )
        Base.metadata.create_all(scoped_connection)
        factory = sessionmaker(
            bind=scoped_connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        owner_id = uuid.uuid4()
        with transactional_session(factory) as db_session:
            db_session.add(
                User(
                    id=owner_id,
                    normalized_email="postgres-repo@example.test",
                    password_hash="test-only-placeholder-hash",
                )
            )

        repository = create_personal_repository(
            factory,
            storage_root,
            owner_id,
            name="postgres-backed",
            description="PostgreSQL and Core integration",
            visibility="private",
            request_id="postgres-test",
        )
        assert repository.lifecycle_state == "ready"
        repository_path = storage_root / f"{repository.storage_key}.git"
        assert discover_repository(repository_path).bare
        items, total = list_personal_repositories(
            factory,
            owner_id,
            limit=10,
            offset=0,
        )
        assert total == 1
        assert [item.id for item in items] == [repository.id]
        assert get_personal_repository(factory, repository.id, owner_id).id == repository.id
        update_personal_repository(
            factory,
            repository.id,
            owner_id,
            name="postgres-renamed",
            description=None,
            description_provided=True,
            visibility="public",
            request_id="postgres-test",
        )
        delete_personal_repository(
            factory,
            storage_root,
            repository.id,
            owner_id,
            request_id="postgres-test",
        )
        assert not repository_path.exists()
        with factory() as db_session:
            tombstone = db_session.get(Repository, repository.id)
            assert tombstone is not None
            assert tombstone.lifecycle_state == "deleted"
            assert tombstone.slug == f"deleted~{repository.id.hex}"
            assert db_session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.target_id == str(repository.id)
                )
            ) == 5
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_postgresql_concurrent_repository_invitation_acceptance_is_single_use(tmp_path) -> None:
    database_url = os.environ.get("HUB_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("HUB_TEST_DATABASE_URL is not configured.")

    engine = create_engine(database_url)
    schema = f"hub_repository_invitation_test_{uuid.uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped_engine = engine.execution_options(
            schema_translate_map={None: schema}
        )
        Base.metadata.create_all(scoped_engine)
        factory = sessionmaker(
            bind=scoped_engine,
            autoflush=False,
            expire_on_commit=False,
        )
        owner_id, invitee_id = uuid.uuid4(), uuid.uuid4()
        with transactional_session(factory) as db_session:
            db_session.add_all(
                [
                    User(
                        id=owner_id,
                        normalized_email="postgres-repo-owner@example.test",
                        password_hash="test-only-placeholder-hash",
                    ),
                    User(
                        id=invitee_id,
                        normalized_email="postgres-repo-invitee@example.test",
                        password_hash="test-only-placeholder-hash",
                    ),
                ]
            )
        repository = create_personal_repository(
            factory,
            tmp_path / "postgres-invitation-repositories",
            owner_id,
            name="postgres-invitation",
            description=None,
            visibility="private",
            request_id="postgres-invitation-test",
        )
        invitation = create_repository_invitation(
            factory,
            repository.id,
            owner_id,
            target_email="postgres-repo-invitee@example.test",
            role="reader",
            expires_in_days=7,
            request_id="postgres-invitation-test",
        )
        start = Barrier(2)

        def accept() -> bool:
            start.wait(timeout=10)
            try:
                accept_repository_invitation(
                    factory,
                    invitation.token,
                    invitee_id,
                    request_id="postgres-concurrent-invitation-accept",
                )
            except RepositoryNotFoundError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: accept(), range(2)))

        assert sum(outcomes) == 1
        with factory() as db_session:
            stored_invitation = db_session.get(Invitation, invitation.invitation.id)
            assert stored_invitation is not None
            assert stored_invitation.status == "accepted"
            assert db_session.get(
                RepositoryUserPermission,
                (repository.id, invitee_id),
            ) is not None
            assert db_session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == "repository.invitation_accepted",
                    AuditEvent.target_id == str(repository.id),
                )
            ) == 1
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def test_postgresql_repository_invitation_rechecks_lifecycle_after_lock_wait(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = os.environ.get("HUB_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("HUB_TEST_DATABASE_URL is not configured.")

    engine = create_engine(database_url)
    schema = f"hub_repo_lifecycle_invite_{uuid.uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped_engine = engine.execution_options(
            schema_translate_map={None: schema}
        )
        Base.metadata.create_all(scoped_engine)
        factory = sessionmaker(
            bind=scoped_engine,
            autoflush=False,
            expire_on_commit=False,
        )
        owner_id, invitee_id = uuid.uuid4(), uuid.uuid4()
        with transactional_session(factory) as db_session:
            db_session.add_all(
                [
                    User(
                        id=owner_id,
                        normalized_email="postgres-lifecycle-owner@example.test",
                        password_hash="test-only-placeholder-hash",
                    ),
                    User(
                        id=invitee_id,
                        normalized_email="postgres-lifecycle-invitee@example.test",
                        password_hash="test-only-placeholder-hash",
                    ),
                ]
            )
        repository = create_personal_repository(
            factory,
            tmp_path / "postgres-lifecycle-invitation-repositories",
            owner_id,
            name="postgres-lifecycle-invitation",
            description=None,
            visibility="private",
            request_id="postgres-lifecycle-invitation-test",
        )
        invitation = create_repository_invitation(
            factory,
            repository.id,
            owner_id,
            target_email="postgres-lifecycle-invitee@example.test",
            role="reader",
            expires_in_days=7,
            request_id="postgres-lifecycle-invitation-test",
        )
        lock_attempted = Event()
        original_lock = repository_invitation_service._lock_repository

        def signal_lock_attempt(db_session: Session, repository_id: uuid.UUID) -> Repository:
            lock_attempted.set()
            return original_lock(db_session, repository_id)

        monkeypatch.setattr(
            repository_invitation_service,
            "_lock_repository",
            signal_lock_attempt,
        )
        blocking_connection = scoped_engine.connect()
        blocking_transaction = blocking_connection.begin()
        blocking_connection.execute(
            select(Repository.id)
            .where(Repository.id == repository.id)
            .with_for_update()
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                acceptance = executor.submit(
                    accept_repository_invitation,
                    factory,
                    invitation.token,
                    invitee_id,
                    request_id="postgres-lifecycle-race-accept",
                )
                try:
                    assert lock_attempted.wait(timeout=10)
                    blocking_connection.execute(
                        update(Repository)
                        .where(Repository.id == repository.id)
                        .values(lifecycle_state="deleting")
                    )
                    blocking_transaction.commit()
                except Exception:
                    if blocking_transaction.is_active:
                        blocking_transaction.rollback()
                    raise
                with pytest.raises(RepositoryNotFoundError):
                    acceptance.result(timeout=10)
        finally:
            if blocking_transaction.is_active:
                blocking_transaction.rollback()
            blocking_connection.close()

        with factory() as db_session:
            assert db_session.get(
                RepositoryUserPermission,
                (repository.id, invitee_id),
            ) is None
            stored_invitation = db_session.get(Invitation, invitation.invitation.id)
            assert stored_invitation is not None
            assert stored_invitation.status == "pending"
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()
