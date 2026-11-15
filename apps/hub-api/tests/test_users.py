"""Privacy-preserving user directory API tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from commitverse_hub.auth.cookies import AuthCookieSettings
from commitverse_hub.auth.sessions import create_session_record
from commitverse_hub.config import Settings
from commitverse_hub.db.base import Base
from commitverse_hub.db.models import User, UserProfile
from commitverse_hub.db.session import transactional_session
from commitverse_hub.main import create_app


def test_user_search_returns_public_active_profile_fields_only(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'users.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    owner_id = uuid.uuid4()
    disabled_id = uuid.uuid4()
    active_id = uuid.uuid4()
    with transactional_session(factory) as db_session:
        db_session.add_all(
            [
                User(id=owner_id, normalized_email="owner@example.test", password_hash="hash"),
                User(
                    id=disabled_id,
                    normalized_email="dev-disabled@example.test",
                    password_hash="hash",
                    account_state="disabled",
                ),
                User(
                    id=uuid.uuid4(),
                    normalized_email="other@example.test",
                    password_hash="hash",
                ),
                User(
                    id=active_id,
                    normalized_email="dev-active@example.test",
                    password_hash="hash",
                ),
            ]
        )
        db_session.add_all(
            [
                UserProfile(user_id=owner_id, username="owner", display_name="Owner"),
                UserProfile(user_id=disabled_id, username="dev-disabled", display_name="Dev Disabled"),
                UserProfile(user_id=active_id, username="dev-active", display_name="Dev Active"),
            ]
        )
        _, session_token = create_session_record(db_session, owner_id, lifetime=timedelta(hours=1))
    settings = Settings(
        environment="testing",
        database_url="postgresql+psycopg://test@localhost/test",
        auth_cookie=AuthCookieSettings(secure=False, max_age_seconds=3600),
        csrf_allowed_origins=("https://hub.example.test",),
    )
    app = create_app(settings, database_engine_factory=lambda _url: engine)
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie.name, session_token)
        response = client.get("/api/v1/users/search", params={"query": "dev"})
        assert response.status_code == 200, response.text
        assert [item["username"] for item in response.json()["items"]] == ["dev-active"]
        assert "email" not in response.text

        short_query = client.get("/api/v1/users/search", params={"query": "d"})
        assert short_query.status_code == 422

        client.cookies.delete(settings.auth_cookie.name)
        unauthenticated = client.get("/api/v1/users/search", params={"query": "owner"})
        assert unauthenticated.status_code == 401
    engine.dispose()
