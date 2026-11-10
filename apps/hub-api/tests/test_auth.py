"""Authentication primitives and session persistence tests."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher, Type
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, update
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


def test_auth_routes_register_login_me_and_logout(tmp_path) -> None:
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


def test_csrf_protection_accepts_exact_allow_listed_origin() -> None:
    session_token = generate_session_token()
    csrf_token = generate_csrf_token(session_token)

    require_csrf_protection(
        session_token,
        csrf_token,
        "https://hub.example.test",
        {"https://hub.example.test"},
    )


@pytest.mark.parametrize(
    ("csrf_token", "origin"),
    [
        (None, "https://hub.example.test"),
        ("invalid", "https://hub.example.test"),
        ("valid-token", None),
        ("valid-token", "https://attacker.example.test"),
    ],
)
def test_csrf_protection_rejects_missing_or_invalid_values(
    csrf_token: str | None,
    origin: str | None,
) -> None:
    allowed_origins = {"https://hub.example.test"}
    with pytest.raises(CsrfValidationError, match="CSRF validation failed"):
        require_csrf_protection(
            generate_session_token(),
            csrf_token,
            origin,
            allowed_origins,
        )


def test_csrf_protection_rejects_wildcard_origin_configuration() -> None:
    with pytest.raises(CsrfValidationError):
        require_csrf_protection(
            generate_session_token(),
            "token",
            "https://hub.example.test",
            {"*"},
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
    with pytest.raises(CsrfValidationError):
        require_csrf_protection(
            generate_session_token(),
            "invalid",
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
