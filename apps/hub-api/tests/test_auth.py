"""Authentication primitives and session persistence tests."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher, Type
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from commitverse_hub.auth.cookies import (
    AuthCookieSettings,
    clear_session_cookie,
    set_session_cookie,
)
from commitverse_hub.auth.csrf import (
    CsrfValidationError,
    generate_csrf_token,
    require_csrf_protection,
    validate_csrf_token,
)
from commitverse_hub.auth.passwords import (
    hash_password,
    password_needs_rehash,
    verify_password,
)
from commitverse_hub.auth.sessions import (
    create_session_record,
    get_active_session,
    revoke_session,
    revoke_user_sessions,
)
from commitverse_hub.auth.tokens import (
    compare_token_hashes,
    generate_session_token,
    hash_session_token,
    validate_session_token,
)
from commitverse_hub.config import Settings
from commitverse_hub.api.v1 import auth as auth_api
from commitverse_hub.db.base import Base
from commitverse_hub.main import create_app
from commitverse_hub.db.models import SessionRecord, User
from commitverse_hub.db.session import create_session_factory, transactional_session


def get_set_cookie_values(headers):
    if hasattr(headers, "get_list"):
        return headers.get_list("set-cookie")
    if hasattr(headers, "getlist"):
        return headers.getlist("set-cookie")
    value = headers.get("set-cookie")
    return [value] if value else []


@pytest.fixture
def auth_api_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth-api.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    settings = Settings(
        environment="testing",
        database_url="postgresql+psycopg://commitverse_app:secret@localhost:5432/commitverse",
        auth_cookie=AuthCookieSettings(secure=False, max_age_seconds=3600),
        csrf_allowed_origins=("https://hub.example.test",),
    )
    app = create_app(
        settings=settings,
        database_engine_factory=lambda _url: engine,
    )

    with TestClient(app) as client:
        yield client, app.state.session_factory
    engine.dispose()


def register_auth_test_user(client):
    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": "https://hub.example.test"},
        json={
            "email": "recovery@example.test",
            "password": "strong password",
            "username": "recoveryuser",
        },
    )
    assert response.status_code == 200
    return response


def set_auth_cookie(client, token):
    client.cookies.set(
        "commitverse_session",
        token,
        domain="testserver.local",
        path="/",
    )


def set_session_state(factory, token, state):
    with transactional_session(factory) as db_session:
        if state == "expired":
            now = datetime.now(UTC)
            db_session.execute(
                update(SessionRecord)
                .where(SessionRecord.token_hash == hash_session_token(token))
                .values(
                    created_at=now - timedelta(hours=2),
                    expires_at=now - timedelta(hours=1),
                )
            )
        elif state == "revoked":
            assert revoke_session(db_session, token)
        else:
            raise AssertionError(f"Unsupported session state: {state}")


@pytest.fixture
def auth_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    user_id = uuid.uuid4()
    with transactional_session(factory) as db_session:
        db_session.add(
            User(
                id=user_id,
                normalized_email="auth@example.test",
                password_hash="test-only-placeholder-hash",
            )
        )
    yield factory, user_id
    engine.dispose()


def test_argon2id_password_hash_verification_and_unique_salts() -> None:
    password = "test-only password 🌱"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert first_hash.startswith("$argon2id$")
    assert verify_password(first_hash, password)
    assert not verify_password(first_hash, "incorrect password")
    assert not password_needs_rehash(first_hash)


def test_argon2id_rehash_detection_for_outdated_parameters() -> None:
    outdated_hash = PasswordHasher(
        time_cost=1,
        memory_cost=8 * 1024,
        parallelism=1,
        type=Type.ID,
    ).hash("test-only password")

    assert password_needs_rehash(outdated_hash)


@pytest.mark.parametrize("encoded_hash", ["", "not-a-password-hash", "$argon2id$broken"])
def test_malformed_password_hashes_fail_safely(encoded_hash: str) -> None:
    assert not verify_password(encoded_hash, "test password")
    assert password_needs_rehash(encoded_hash)


@pytest.mark.parametrize("password", ["", None, 123, "x" * 1025])
def test_invalid_password_inputs_are_rejected(password: object) -> None:
    with pytest.raises(ValueError):
        hash_password(password)
    assert not verify_password("$argon2id$malformed", password)


def test_session_tokens_are_opaque_valid_and_have_256_bits_of_entropy() -> None:
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert validate_session_token(first)
    assert validate_session_token(second)
    assert len(first) == 43
    assert not validate_session_token("12345678-1234-1234-1234-123456789012")
    assert hash_session_token(first) != first
    assert compare_token_hashes(hash_session_token(first), hash_session_token(first))
    assert not compare_token_hashes(hash_session_token(first), hash_session_token(second))
    assert not compare_token_hashes("malformed", "malformed")


def test_session_create_retrieve_expire_and_store_hash_only(auth_database) -> None:
    factory, user_id = auth_database
    now = datetime.now(UTC)

    with transactional_session(factory) as db_session:
        record, token = create_session_record(
            db_session,
            user_id,
            lifetime=timedelta(hours=1),
            now=now,
        )
        record_id = record.id
        token_hash = record.token_hash

    assert token_hash == hash_session_token(token)
    assert token not in token_hash
    with transactional_session(factory) as db_session:
        active = get_active_session(db_session, token, now=now + timedelta(minutes=5))
        assert active is not None
        assert active.id == record_id
        assert active.user_id == user_id
        assert active.created_at.replace(tzinfo=UTC) == now
        assert active.expires_at.replace(tzinfo=UTC) == now + timedelta(hours=1)
        assert get_active_session(db_session, token, now=now + timedelta(hours=1)) is None
        assert get_active_session(db_session, "malformed", now=now) is None
        stored_hash = db_session.scalar(
            select(SessionRecord.token_hash).where(SessionRecord.id == record_id)
        )
        assert stored_hash == hash_session_token(token)


def test_session_revocation_and_account_wide_revocation(auth_database) -> None:
    factory, user_id = auth_database
    with transactional_session(factory) as db_session:
        first_record, first_token = create_session_record(
            db_session, user_id, lifetime=timedelta(hours=1)
        )
        second_record, second_token = create_session_record(
            db_session, user_id, lifetime=timedelta(hours=1)
        )
        first_id = first_record.id
        second_id = second_record.id

    with transactional_session(factory) as db_session:
        assert revoke_session(db_session, first_token)
        assert not revoke_session(db_session, first_token)
        assert not revoke_session(db_session, "malformed")
    with transactional_session(factory) as db_session:
        assert get_active_session(db_session, first_token) is None
        assert get_active_session(db_session, second_token) is not None
        assert revoke_user_sessions(db_session, user_id) == 1
    with transactional_session(factory) as db_session:
        assert get_active_session(db_session, second_token) is None
        assert db_session.scalar(
            select(func.count()).select_from(SessionRecord).where(
                SessionRecord.id.in_([first_id, second_id]),
                SessionRecord.revoked_at.is_not(None),
            )
        ) == 2


def test_session_helpers_leave_commit_and_rollback_to_the_caller(auth_database) -> None:
    factory, user_id = auth_database
    with pytest.raises(RuntimeError, match="caller rollback"):
        with transactional_session(factory) as db_session:
            create_session_record(
                db_session, user_id, lifetime=timedelta(hours=1)
            )
            raise RuntimeError("caller rollback")

    with transactional_session(factory) as db_session:
        assert db_session.scalar(select(func.count()).select_from(SessionRecord)) == 0


def test_disabled_user_sessions_are_not_active(auth_database) -> None:
    factory, user_id = auth_database
    with transactional_session(factory) as db_session:
        _, token = create_session_record(
            db_session, user_id, lifetime=timedelta(hours=1)
        )
    with transactional_session(factory) as db_session:
        db_session.execute(
            update(User)
            .where(User.id == user_id)
            .values(account_state="disabled")
        )
    with transactional_session(factory) as db_session:
        assert get_active_session(db_session, token) is None


def test_session_creation_rejects_invalid_lifetime_and_naive_time(auth_database) -> None:
    factory, user_id = auth_database
    with transactional_session(factory) as db_session:
        with pytest.raises(ValueError, match="positive"):
            create_session_record(db_session, user_id, lifetime=timedelta(0))
        with pytest.raises(ValueError, match="timezone-aware"):
            create_session_record(
                db_session,
                user_id,
                lifetime=timedelta(hours=1),
                now=datetime(2026, 1, 1),
            )


def test_session_lifecycle_on_postgresql_in_a_rolled_back_schema() -> None:
    database_url = os.environ.get("HUB_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("HUB_TEST_DATABASE_URL is not configured.")

    engine = create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    schema = f"hub_auth_test_{uuid.uuid4().hex}"
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
        now = datetime.now(UTC)
        with factory.begin() as db_session:
            user_id = uuid.uuid4()
            db_session.add(
                User(
                    id=user_id,
                    normalized_email="postgres-auth@example.test",
                    password_hash="test-only-placeholder-hash",
                )
            )
            record, token = create_session_record(
                db_session,
                user_id,
                lifetime=timedelta(minutes=5),
                now=now,
            )
            record_id = record.id
        with factory.begin() as db_session:
            assert get_active_session(db_session, token, now=now) is not None
            assert (
                get_active_session(
                    db_session,
                    token,
                    now=now + timedelta(minutes=5),
                )
                is None
            )
            assert revoke_session(db_session, token, now=now)
        with factory.begin() as db_session:
            assert get_active_session(db_session, token, now=now) is None
            assert db_session.scalar(
                select(SessionRecord.token_hash).where(SessionRecord.id == record_id)
            ) == hash_session_token(token)
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_auth_routes_register_login_me_and_logout(tmp_path, monkeypatch) -> None:
    sqlite_path = tmp_path / "hub-auth-routes.sqlite"
    engine = create_engine(f"sqlite:///{sqlite_path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    settings = Settings(
        environment="testing",
        database_url="postgresql+psycopg://commitverse_app:secret@localhost:5432/commitverse",
        auth_cookie=AuthCookieSettings(secure=False, max_age_seconds=3600),
        csrf_allowed_origins=("https://hub.example.test",),
    )

    app = create_app(
        settings=settings,
        database_engine_factory=lambda _url: engine,
    )

    with TestClient(app) as client:
        origin_headers = {"Origin": "https://hub.example.test"}
        register_response = client.post(
            "/api/v1/auth/register",
            headers=origin_headers,
            json={
                "email": " ALICE@example.test ",
                "password": "strong password",
                "username": " Alice ",
                "display_name": " Alice ",
            },
        )
        assert register_response.status_code == 200
        payload = register_response.json()
        assert payload["email"] == "alice@example.test"
        assert payload["username"] == "Alice"
        assert payload["display_name"] == "Alice"
        assert "commitverse_session" in client.cookies
        csrf_token = register_response.headers["X-CSRF-Token"]

        me_response = client.get("/api/v1/me")
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "alice@example.test"

        def fail_revocation(_db_session, _token):
            raise SQLAlchemyError("database failure")

        monkeypatch.setattr(auth_api, "revoke_session", fail_revocation)
        failed_logout = client.post(
            "/api/v1/auth/logout",
            headers={**origin_headers, "X-CSRF-Token": csrf_token},
        )
        assert failed_logout.status_code == 503
        assert failed_logout.json()["error"]["code"] == "session_revocation_failed"
        assert "Max-Age=0" not in ";".join(
            get_set_cookie_values(failed_logout.headers)
        )

        monkeypatch.undo()
        logout_response = client.post(
            "/api/v1/auth/logout",
            headers={**origin_headers, "X-CSRF-Token": csrf_token},
        )
        assert logout_response.status_code == 200
        assert logout_response.json()["status"] == "ok"
        assert "Max-Age=0" in get_set_cookie_values(logout_response.headers)[-1]

        unauthenticated = client.get("/api/v1/me")
        assert unauthenticated.status_code == 401


def test_auth_routes_reject_duplicate_accounts_and_bad_login(tmp_path) -> None:
    sqlite_path = tmp_path / "hub-auth-duplicates.sqlite"
    engine = create_engine(f"sqlite:///{sqlite_path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    settings = Settings(
        environment="testing",
        database_url="postgresql+psycopg://commitverse_app:secret@localhost:5432/commitverse",
        auth_cookie=AuthCookieSettings(secure=False, max_age_seconds=3600),
        csrf_allowed_origins=("https://hub.example.test",),
    )

    app = create_app(
        settings=settings,
        database_engine_factory=lambda _url: engine,
    )

    with TestClient(app) as client:
        origin_headers = {"Origin": "https://hub.example.test"}
        first = client.post(
            "/api/v1/auth/register",
            headers=origin_headers,
            json={
                "email": "duplicate@example.test",
                "password": "strong password",
                "username": "duplicateuser",
            },
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/auth/register",
            headers=origin_headers,
            json={
                "email": "duplicate@example.test",
                "password": "another strong password",
                "username": "otheruser",
            },
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "account_exists"

        session_token = client.cookies.get("commitverse_session")
        csrf = generate_csrf_token(session_token)
        bad_login = client.post(
            "/api/v1/auth/login",
            headers={**origin_headers, "X-CSRF-Token": csrf},
            json={
                "email": "duplicate@example.test",
                "password": "wrong-password",
            },
        )
        assert bad_login.status_code == 401
        assert bad_login.json()["error"]["code"] == "authentication_failed"


def test_me_restores_a_session_bound_csrf_token_without_changing_user_body(auth_api_client) -> None:
    client, factory = auth_api_client
    registration = register_auth_test_user(client)
    session_token = client.cookies.get("commitverse_session")
    assert session_token is not None
    user_id = uuid.UUID(registration.json()["id"])

    with transactional_session(factory) as db_session:
        _, another_session = create_session_record(
            db_session,
            user_id,
            lifetime=timedelta(hours=1),
        )

    response = client.get("/api/v1/me")
    csrf_token = response.headers.get("X-CSRF-Token")

    assert response.status_code == 200
    assert response.json() == registration.json()
    assert csrf_token is not None
    assert validate_csrf_token(session_token, csrf_token)
    assert not validate_csrf_token(another_session, csrf_token)
    assert response.headers["Cache-Control"] == "no-store"
    assert session_token not in response.text


def test_me_does_not_issue_csrf_token_without_a_session(auth_api_client) -> None:
    client, _ = auth_api_client

    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers.get("X-CSRF-Token") is None


@pytest.mark.parametrize("cookie_value", ["malformed", generate_session_token()])
def test_me_does_not_issue_csrf_token_for_an_invalid_session(
    auth_api_client,
    cookie_value: str,
) -> None:
    client, _ = auth_api_client
    set_auth_cookie(client, cookie_value)

    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers.get("X-CSRF-Token") is None


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_me_does_not_issue_csrf_token_for_an_inactive_session(auth_api_client, state: str) -> None:
    client, factory = auth_api_client
    register_auth_test_user(client)
    session_token = client.cookies.get("commitverse_session")
    assert session_token is not None
    set_session_state(factory, session_token, state)

    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers.get("X-CSRF-Token") is None


def test_login_without_a_cookie_authenticates_and_returns_csrf(auth_api_client) -> None:
    client, _ = auth_api_client
    register_auth_test_user(client)
    client.cookies.clear()

    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://hub.example.test"},
        json={"email": "recovery@example.test", "password": "strong password"},
    )

    session_token = client.cookies.get("commitverse_session")
    assert response.status_code == 200
    assert response.json()["email"] == "recovery@example.test"
    assert session_token is not None
    assert validate_csrf_token(
        session_token,
        response.headers.get("X-CSRF-Token"),
    )


@pytest.mark.parametrize("csrf_header", [None, "invalid-csrf-token"])
def test_login_with_an_active_session_requires_valid_csrf(
    auth_api_client,
    csrf_header: str | None,
) -> None:
    client, _ = auth_api_client
    register_auth_test_user(client)
    headers = {"Origin": "https://hub.example.test"}
    if csrf_header is not None:
        headers["X-CSRF-Token"] = csrf_header

    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": "recovery@example.test", "password": "strong password"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_validation_failed"


@pytest.mark.parametrize("state", ["expired", "revoked", "malformed"])
def test_login_recovers_from_a_stale_or_malformed_cookie(auth_api_client, state: str) -> None:
    client, factory = auth_api_client
    register_auth_test_user(client)
    old_token = client.cookies.get("commitverse_session")
    assert old_token is not None
    if state == "malformed":
        set_auth_cookie(client, "not-a-session-token")
    else:
        set_session_state(factory, old_token, state)

    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://hub.example.test"},
        json={"email": "recovery@example.test", "password": "strong password"},
    )

    new_token = client.cookies.get("commitverse_session")
    assert response.status_code == 200
    assert new_token is not None
    assert new_token != old_token
    assert validate_csrf_token(
        new_token,
        response.headers.get("X-CSRF-Token"),
    )


@pytest.mark.parametrize("cookie_state", ["absent", "active", "expired", "revoked", "malformed"])
def test_login_rejects_untrusted_origin_for_every_cookie_state(
    auth_api_client,
    cookie_state: str,
) -> None:
    client, factory = auth_api_client
    if cookie_state != "absent":
        register_auth_test_user(client)
        token = client.cookies.get("commitverse_session")
        assert token is not None
        if cookie_state in {"expired", "revoked"}:
            set_session_state(factory, token, cookie_state)
        elif cookie_state == "malformed":
            set_auth_cookie(client, "malformed-cookie")
    else:
        client.cookies.clear()

    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://attacker.example.test"},
        json={"email": "recovery@example.test", "password": "strong password"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_login_preserves_previous_active_sessions(auth_api_client) -> None:
    client, factory = auth_api_client
    registration = register_auth_test_user(client)
    first_token = client.cookies.get("commitverse_session")
    first_csrf = registration.headers["X-CSRF-Token"]
    assert first_token is not None

    login_response = client.post(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://hub.example.test",
            "X-CSRF-Token": first_csrf,
        },
        json={"email": "recovery@example.test", "password": "strong password"},
    )
    second_token = client.cookies.get("commitverse_session")

    assert login_response.status_code == 200
    assert second_token is not None and second_token != first_token
    with factory() as db_session:
        assert get_active_session(db_session, first_token) is not None
        assert get_active_session(db_session, second_token) is not None

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "https://hub.example.test",
            "X-CSRF-Token": login_response.headers["X-CSRF-Token"],
        },
    )
    assert logout_response.status_code == 200
    with factory() as db_session:
        assert get_active_session(db_session, first_token) is not None
        assert get_active_session(db_session, second_token) is None


def test_login_does_not_treat_session_store_failure_as_a_stale_cookie(
    auth_api_client,
    monkeypatch,
) -> None:
    client, _ = auth_api_client
    register_auth_test_user(client)

    def fail_session_lookup(*_args, **_kwargs):
        raise SQLAlchemyError("session store unavailable")

    monkeypatch.setattr(auth_api, "get_active_session", fail_session_lookup)
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://hub.example.test"},
        json={"email": "recovery@example.test", "password": "strong password"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "session_validation_failed"


@pytest.mark.parametrize("csrf_header", [None, "invalid-csrf-token"])
def test_logout_with_an_active_session_requires_valid_csrf(
    auth_api_client,
    csrf_header: str | None,
) -> None:
    client, _ = auth_api_client
    register_auth_test_user(client)
    headers = {"Origin": "https://hub.example.test"}
    if csrf_header is not None:
        headers["X-CSRF-Token"] = csrf_header

    response = client.post("/api/v1/auth/logout", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_validation_failed"
    assert "Max-Age=0" not in ";".join(get_set_cookie_values(response.headers))


@pytest.mark.parametrize("state", ["expired", "revoked", "malformed"])
def test_logout_clears_a_stale_or_malformed_cookie(auth_api_client, state: str) -> None:
    client, factory = auth_api_client
    register_auth_test_user(client)
    token = client.cookies.get("commitverse_session")
    assert token is not None
    if state == "malformed":
        set_auth_cookie(client, "not-a-session-token")
    else:
        set_session_state(factory, token, state)

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://hub.example.test"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "Max-Age=0" in ";".join(get_set_cookie_values(response.headers))


@pytest.mark.parametrize("state", ["expired", "revoked", "malformed"])
def test_logout_rejects_untrusted_origin_for_stale_cookies(auth_api_client, state: str) -> None:
    client, factory = auth_api_client
    register_auth_test_user(client)
    token = client.cookies.get("commitverse_session")
    assert token is not None
    if state == "malformed":
        set_auth_cookie(client, "not-a-session-token")
    else:
        set_session_state(factory, token, state)

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://attacker.example.test"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert "Max-Age=0" not in ";".join(get_set_cookie_values(response.headers))


def test_logout_without_a_cookie_keeps_safe_origin_only_behavior(auth_api_client) -> None:
    client, _ = auth_api_client

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://hub.example.test"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "Max-Age=0" in ";".join(get_set_cookie_values(response.headers))


def test_logout_does_not_clear_a_cookie_when_session_validation_fails(
    auth_api_client,
    monkeypatch,
) -> None:
    client, _ = auth_api_client
    register_auth_test_user(client)

    def fail_session_lookup(*_args, **_kwargs):
        raise SQLAlchemyError("session store unavailable")

    monkeypatch.setattr(auth_api, "get_active_session", fail_session_lookup)
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://hub.example.test"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "session_validation_failed"
    assert "Max-Age=0" not in ";".join(get_set_cookie_values(response.headers))


def test_csrf_tokens_are_random_and_bound_to_the_session() -> None:
    first_session = generate_session_token()
    second_session = generate_session_token()
    first_csrf = generate_csrf_token(first_session)
    second_csrf = generate_csrf_token(first_session)

    assert first_csrf != second_csrf
    assert validate_csrf_token(first_session, first_csrf)
    assert validate_csrf_token(first_session, second_csrf)
    assert not validate_csrf_token(second_session, first_csrf)
    assert not validate_csrf_token(first_session, None)
    assert not validate_csrf_token(first_session, "malformed")
    assert not validate_csrf_token(first_session, f"{first_csrf[:43]}.{('é' * 64)}")
    tampered_csrf = first_csrf[:-1] + ("0" if first_csrf[-1] != "0" else "1")
    assert not validate_csrf_token(first_session, tampered_csrf)


@pytest.mark.parametrize(
    "origin",
    [
        "https://hub.example.test",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://[::1]:8000",
    ],
)
def test_csrf_protection_accepts_exact_allow_listed_origin(origin: str) -> None:
    session_token = generate_session_token()
    csrf_token = generate_csrf_token(session_token)

    require_csrf_protection(
        session_token,
        csrf_token,
        origin,
        {origin},
    )


@pytest.mark.parametrize("csrf_token", [None, "invalid"])
def test_csrf_protection_rejects_missing_or_invalid_tokens(
    csrf_token: str | None,
) -> None:
    session_token = generate_session_token()
    allowed_origins = {"https://hub.example.test"}
    with pytest.raises(CsrfValidationError, match="CSRF validation failed"):
        require_csrf_protection(
            session_token,
            csrf_token,
            "https://hub.example.test",
            allowed_origins,
        )


@pytest.mark.parametrize(
    ("origin", "allowed_origins"),
    [
        (None, {"https://hub.example.test"}),
        ("https://attacker.example.test", {"https://hub.example.test"}),
        ("*", {"https://hub.example.test"}),
        ("https://*.example.test", {"https://hub.example.test"}),
        ("https://foo..example.test", {"https://hub.example.test"}),
        ("https://-bad.example.test", {"https://hub.example.test"}),
        ("https://bad_.example.test", {"https://hub.example.test"}),
        ("https://hub.example.test\t", {"https://hub.example.test"}),
        ("https://hub.example.test\n", {"https://hub.example.test"}),
        ("https://user@hub.example.test", {"https://hub.example.test"}),
        ("https://user:password@hub.example.test", {"https://hub.example.test"}),
    ],
)
def test_csrf_protection_rejects_invalid_origins_with_valid_token(
    origin: str | None,
    allowed_origins: set[str],
) -> None:
    session_token = generate_session_token()
    csrf_token = generate_csrf_token(session_token)
    with pytest.raises(CsrfValidationError):
        require_csrf_protection(
            session_token,
            csrf_token,
            origin,
            allowed_origins,
        )


@pytest.mark.parametrize(
    "invalid_allowed_origin",
    [
        "*",
        "https://*.example.test",
        "https://hub.example.test/path",
        "https://foo..example.test",
        "https://-bad.example.test",
        "https://bad_.example.test",
        "https://hub.example.test\t",
        "https://hub.example.test\n",
        "https://hub.example.test\r",
        "https://hub.example.test\0",
        "https://hub.example.test\x7f",
    ],
)
def test_csrf_protection_rejects_invalid_allowlist_entries_with_valid_token(
    invalid_allowed_origin: str,
) -> None:
    session_token = generate_session_token()
    csrf_token = generate_csrf_token(session_token)
    with pytest.raises(CsrfValidationError):
        require_csrf_protection(
            session_token,
            csrf_token,
            "https://hub.example.test",
            {invalid_allowed_origin},
        )


@pytest.mark.parametrize(
    ("origin", "allowed_origins"),
    [
        ("null", {"null"}),
        ("https://hub.example.test/path", {"https://hub.example.test/path"}),
        ("https://hub.example.test:invalid", {"https://hub.example.test:invalid"}),
    ],
)
def test_csrf_protection_rejects_non_origin_values(
    origin: str,
    allowed_origins: set[str],
) -> None:
    session_token = generate_session_token()
    csrf_token = generate_csrf_token(session_token)
    with pytest.raises(CsrfValidationError):
        require_csrf_protection(
            session_token,
            csrf_token,
            origin,
            allowed_origins,
        )


def test_cookie_defaults_and_set_clear_headers() -> None:
    settings = AuthCookieSettings()
    response = Response()

    set_session_cookie(response, generate_session_token(), settings)
    set_header = response.headers["set-cookie"]
    assert "HttpOnly" in set_header
    assert "Secure" in set_header
    assert "SameSite=lax" in set_header
    assert "Path=/" in set_header
    assert "Max-Age=2592000" in set_header
    assert "Domain=" not in set_header

    clear_session_cookie(response, settings)
    assert "Max-Age=0" in get_set_cookie_values(response.headers)[-1]


def test_cookie_settings_enforce_production_security() -> None:
    secure_cookie = AuthCookieSettings.from_environment(
        {"HUB_SESSION_COOKIE_SECURE": "true"}
    )
    assert Settings(environment="production", auth_cookie=secure_cookie)

    insecure_cookie = AuthCookieSettings.from_environment(
        {"HUB_SESSION_COOKIE_SECURE": "false"}
    )
    with pytest.raises(ValueError, match="Secure in production"):
        Settings(environment="production", auth_cookie=insecure_cookie)
    with pytest.raises(ValueError, match="Secure in production"):
        Settings.from_environment(
            {
                "HUB_ENVIRONMENT": "production",
                "HUB_SESSION_COOKIE_SECURE": "false",
            }
        )
    with pytest.raises(ValueError, match="HttpOnly"):
        AuthCookieSettings(httponly=False)
    with pytest.raises(ValueError, match="SameSite=None"):
        AuthCookieSettings(secure=False, samesite="none")
    with pytest.raises(ValueError, match="domain"):
        AuthCookieSettings(domain="*.example.test")


def test_cookie_environment_configuration_is_loaded() -> None:
    settings = Settings.from_environment(
        {
            "HUB_ENVIRONMENT": "testing",
            "HUB_SESSION_COOKIE_NAME": "hub_session",
            "HUB_SESSION_COOKIE_SECURE": "false",
            "HUB_SESSION_COOKIE_SAMESITE": "strict",
            "HUB_SESSION_COOKIE_PATH": "/api",
            "HUB_SESSION_COOKIE_DOMAIN": "hub.example.test",
            "HUB_SESSION_COOKIE_MAX_AGE": "3600",
        }
    )

    assert settings.auth_cookie == AuthCookieSettings(
        name="hub_session",
        secure=False,
        samesite="strict",
        path="/api",
        domain="hub.example.test",
        max_age_seconds=3600,
    )
    assert settings.auth_cookie.httponly
    with pytest.raises(ValueError, match="HttpOnly"):
        Settings.from_environment({"HUB_SESSION_COOKIE_HTTPONLY": "false"})
