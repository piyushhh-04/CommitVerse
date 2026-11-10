"""Application exceptions and safe HTTP error responses."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

logger = logging.getLogger("commitverse_hub.errors")


class HubApplicationError(Exception):
    """An expected application error safe to expose to an API client."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        if not 400 <= status_code <= 599:
            raise ValueError("status_code must be an HTTP error status.")
        if not code or not code.replace("_", "").isalnum():
            raise ValueError("code must contain only letters, digits, or underscores.")
        if not message.strip():
            raise ValueError("message must not be empty.")
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _error_content(
    request_id: str,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error, "request_id": request_id}


def _response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content=_error_content(request_id, code, message, details),
        headers={"X-Request-ID": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install stable error mappings without exposing internal input values."""

    @app.exception_handler(HubApplicationError)
    async def handle_application_error(
        request: Request, exc: HubApplicationError
    ) -> JSONResponse:
        return _response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "code": str(error.get("type", "invalid_value")),
                "message": "Invalid value.",
            }
            for error in exc.errors()
        ]
        return _response(
            request,
            422,
            "validation_error",
            "Request validation failed.",
            details,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled request exception",
            extra={"request_id": _request_id(request)},
        )
        return _response(
            request,
            500,
            "internal_error",
            "An unexpected error occurred.",
        )
