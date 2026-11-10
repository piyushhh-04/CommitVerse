"""Request correlation and logging tests."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from commitverse_hub.logging.context import request_id_context


def test_request_id_is_generated_and_returned(client) -> None:
    response = client.get("/api/v1/health")

    request_id = response.headers["x-request-id"]
    assert 32 <= len(request_id) <= 64
    assert all(char in "0123456789abcdef" for char in request_id)


def test_valid_incoming_request_id_is_preserved(client) -> None:
    response = client.get(
        "/api/v1/health", headers={"X-Request-ID": "client.request-17"}
    )

    assert response.headers["x-request-id"] == "client.request-17"


def test_invalid_or_duplicate_request_id_is_replaced(client) -> None:
    response = client.get(
        "/api/v1/health",
        headers=[("X-Request-ID", "contains spaces"), ("X-Request-ID", "second")],
    )

    assert response.headers["x-request-id"] not in {"contains spaces", "second"}
    assert len(response.headers["x-request-id"]) == 32


def test_request_log_contains_route_status_and_correlation_id(
    app, client, caplog
) -> None:
    caplog.set_level(logging.INFO, logger="commitverse_hub.request")

    response = client.get(
        "/api/v1/health", headers={"X-Request-ID": "log-check"}
    )

    record = next(
        record for record in caplog.records if record.getMessage() == "http_request"
    )
    assert response.status_code == 200
    assert record.request_id == "log-check"
    assert record.http_method == "GET"
    assert record.route == "/health"
    assert record.status_code == 200
    assert record.duration_ms >= 0


def test_request_context_is_isolated_between_concurrent_requests(app) -> None:
    async def current_context() -> dict[str, str | None]:
        await asyncio.sleep(0.01)
        return {"request_id": request_id_context.get()}

    app.add_api_route("/_test/context", current_context, methods=["GET"])

    def request_with_id(request_id: str) -> tuple[str | None, str | None]:
        with TestClient(app) as client:
            response = client.get(
                "/_test/context", headers={"X-Request-ID": request_id}
            )
        return response.json()["request_id"], response.headers["x-request-id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request_with_id, "concurrent-one")
        second = executor.submit(request_with_id, "concurrent-two")

    assert first.result() == ("concurrent-one", "concurrent-one")
    assert second.result() == ("concurrent-two", "concurrent-two")
