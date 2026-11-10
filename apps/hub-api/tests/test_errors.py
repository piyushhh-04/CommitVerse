"""Safe error response tests."""

import logging

from fastapi.testclient import TestClient

from commitverse_hub.errors.handlers import HubApplicationError


def test_validation_error_has_consistent_safe_shape(app, client) -> None:
    def endpoint(count: int) -> dict[str, int]:
        return {"count": count}

    app.add_api_route("/_test/validation", endpoint, methods=["GET"])
    response = client.get("/_test/validation", params={"count": "not-an-int"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["message"] == "Request validation failed."
    assert response.json()["error"]["details"][0]["field"] == "query.count"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "not-an-int" not in response.text


def test_application_error_is_mapped_to_safe_response(app, client) -> None:
    def endpoint() -> None:
        raise HubApplicationError(404, "not_found", "Resource not found.")

    app.add_api_route("/_test/not-found", endpoint, methods=["GET"])
    response = client.get("/_test/not-found")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Resource not found.",
    }
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_unexpected_error_is_redacted_and_logged(app, caplog) -> None:
    def endpoint() -> None:
        raise RuntimeError("private path /internal/secret")

    app.add_api_route("/_test/failure", endpoint, methods=["GET"])
    caplog.set_level(logging.ERROR, logger="commitverse_hub.errors")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/_test/failure", headers={"X-Request-ID": "failure-case"}
        )

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
    }
    assert "private path" not in response.text
    assert "/internal/secret" not in response.text
    assert response.headers["x-request-id"] == "failure-case"
    assert any(
        record.request_id == "failure-case"
        and record.getMessage() == "Unhandled request exception"
        for record in caplog.records
    )
