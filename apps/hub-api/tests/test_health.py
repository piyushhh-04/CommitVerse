"""Health endpoint tests."""

from fastapi.testclient import TestClient

from commitverse_hub.config import Settings
from commitverse_hub.main import create_app


def test_health_endpoint_returns_process_status(client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "commitverse-hub"}
    assert response.headers["content-type"].startswith("application/json")


def test_health_endpoint_uses_configured_api_prefix() -> None:
    app = create_app(Settings(environment="testing", api_prefix="/test/v1"))

    with TestClient(app) as client:
        assert client.get("/test/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 404


def test_health_endpoint_does_not_claim_dependencies_are_available(client) -> None:
    body = client.get("/api/v1/health").json()

    assert set(body) == {"status", "service"}
    assert "database" not in body
    assert "core" not in body
