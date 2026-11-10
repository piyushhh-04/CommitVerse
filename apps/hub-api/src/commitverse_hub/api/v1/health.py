"""Health endpoint and response schema."""

import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from commitverse_hub.db.engine import check_database_connection

router = APIRouter()
logger = logging.getLogger("commitverse_hub.database")


class HealthResponse(BaseModel):
    """Public response for process-level health."""

    status: Literal["ok"]
    service: Literal["commitverse-hub"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the HTTP API process is serving requests."""
    return HealthResponse(status="ok", service="commitverse-hub")


class DatabaseHealthResponse(BaseModel):
    """Public response for the optional PostgreSQL connectivity probe."""

    status: Literal["ok", "unavailable"]
    service: Literal["commitverse-hub-database"]


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    responses={503: {"model": DatabaseHealthResponse}},
)
async def database_health(
    request: Request, response: Response
) -> DatabaseHealthResponse:
    """Check PostgreSQL connectivity without blocking the ASGI event loop."""
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        response.status_code = 503
        return DatabaseHealthResponse(
            status="unavailable",
            service="commitverse-hub-database",
        )

    available = await run_in_threadpool(check_database_connection, engine)
    if not available:
        response.status_code = 503
        logger.warning(
            "database_connectivity_failed",
            extra={"request_id": getattr(request.state, "request_id", "unavailable")},
        )
    return DatabaseHealthResponse(
        status="ok" if available else "unavailable",
        service="commitverse-hub-database",
    )
