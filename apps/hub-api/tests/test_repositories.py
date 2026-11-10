"""Personal repository API and Core-backed lifecycle tests."""

from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from commitverse_core.repository import discover_repository, initialize_repository
from commitverse_hub.auth.cookies import AuthCookieSettings
from commitverse_hub.auth.csrf import generate_csrf_token
from commitverse_hub.auth.sessions import create_session_record
from commitverse_hub.config import Settings
from commitverse_hub.db.base import Base
from commitverse_hub.db.models import AuditEvent, Repository, User, UserProfile
from commitverse_hub.db.session import transactional_session
from commitverse_hub.main import create_app
from commitverse_hub.repositories.service import (
    RepositoryConflictError,
    create_personal_repository,
    delete_personal_repository,
    get_personal_repository,
    list_personal_repositories,
    update_personal_repository,
)
from commitverse_hub.repositories.storage import (
    RepositoryStorageError,
    create_bare_repository,
)


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
                AuditEvent.action == "repository.created",
                AuditEvent.target_id == str(repository.id),
            )
        ) == 1


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
        assert tombstone.lifecycle_state == "deleting"
        assert tombstone.slug == f"deleted~{uuid.UUID(repository_id).hex}"
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
    assert transaction_count == 3

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
            assert tombstone.lifecycle_state == "deleting"
            assert tombstone.slug == f"deleted~{repository.id.hex}"
            assert db_session.scalar(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.target_id == str(repository.id)
                )
            ) == 3
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
