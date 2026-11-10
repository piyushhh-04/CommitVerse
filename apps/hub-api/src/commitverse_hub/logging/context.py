"""ASGI request ID middleware and request-scoped logging context."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_context: ContextVar[str | None] = ContextVar(
    "commitverse_hub_request_id", default=None
)
_REQUEST_ID_HEADER = b"x-request-id"
_REQUEST_ID_PATTERN = re.compile(rb"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_REQUEST_LOGGER = logging.getLogger("commitverse_hub.request")


def _incoming_request_id(scope: Scope) -> str | None:
    matches = [
        value
        for name, value in scope.get("headers", [])
        if name.lower() == _REQUEST_ID_HEADER
    ]
    if len(matches) != 1 or not _REQUEST_ID_PATTERN.fullmatch(matches[0]):
        return None
    return matches[0].decode("ascii")


def _route_template(scope: Scope) -> str:
    route: Any = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestContextMiddleware:
    """Set, return, and log a validated correlation ID for HTTP requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != _REQUEST_ID_HEADER
                ]
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            _REQUEST_LOGGER.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "http_method": scope.get("method", "UNKNOWN"),
                    "route": _route_template(scope),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                },
            )
            request_id_context.reset(token)
