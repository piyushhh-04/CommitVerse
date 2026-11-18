"""Repository issue and pull request collaboration API tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from commitverse_hub.auth.cookies import AuthCookieSettings
from commitverse_hub.auth.csrf import generate_csrf_token
from commitverse_hub.auth.sessions import create_session_record
from commitverse_hub.config import Settings
from commitverse_hub.db.base import Base
from commitverse_hub.db.models import User, UserProfile
from commitverse_hub.db.session import transactional_session
from commitverse_hub.main import create_app


@pytest.fixture
def collaboration_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'collaboration.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    user_id = uuid.uuid4()
    with transactional_session(factory) as db:
        db.add(User(id=user_id, normalized_email="builder@example.test", password_hash="test-only-placeholder"))
        db.add(UserProfile(user_id=user_id, username="builder", display_name="Builder"))
        _, token = create_session_record(db, user_id, lifetime=timedelta(hours=1))
    settings = Settings(
        environment="testing",
        database_url="postgresql+psycopg://test@localhost/test",
        auth_cookie=AuthCookieSettings(secure=False, max_age_seconds=3600),
        csrf_allowed_origins=("https://hub.example.test",),
        repository_storage_root=(tmp_path / "repositories").resolve(),
    )
    app = create_app(settings, database_engine_factory=lambda _url: engine)
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie.name, token)
        yield client, settings, factory, user_id, generate_csrf_token(token)
    engine.dispose()


def _headers(csrf: str) -> dict[str, str]:
    return {"Origin": "https://hub.example.test", "X-CSRF-Token": csrf}


def test_issue_lifecycle_and_comments(collaboration_client):
    client, _settings, _factory, _user_id, csrf = collaboration_client
    created = client.post(
        "/api/v1/repositories",
        headers=_headers(csrf),
        json={"name": "collaboration-demo", "visibility": "private"},
    )
    assert created.status_code == 201
    repository_id = created.json()["id"]

    issue = client.post(
        f"/api/v1/repositories/{repository_id}/issues",
        headers=_headers(csrf),
        json={"title": "Add workflow documentation", "body": "Document the CI contract."},
    )
    assert issue.status_code == 201
    issue_id = issue.json()["id"]
    assert issue.json()["number"] == 1

    comment = client.post(
        f"/api/v1/repositories/{repository_id}/issues/{issue_id}/comments",
        headers=_headers(csrf),
        json={"body": "I can take this."},
    )
    assert comment.status_code == 201

    listed = client.get(f"/api/v1/repositories/{repository_id}/issues")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    closed = client.patch(
        f"/api/v1/repositories/{repository_id}/issues/{issue_id}",
        headers=_headers(csrf),
        json={"state": "closed"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed"
