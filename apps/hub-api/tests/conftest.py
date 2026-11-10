"""Shared fixtures for Hub API tests."""

import pytest
from fastapi.testclient import TestClient

from commitverse_hub.config import Settings
from commitverse_hub.main import create_app


@pytest.fixture
def app():
    return create_app(Settings(environment="testing"))


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
