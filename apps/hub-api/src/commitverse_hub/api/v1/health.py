"""Health endpoint and response schema."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    """Public response for process-level health."""

    status: Literal["ok"]
    service: Literal["commitverse-hub"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the HTTP API process is serving requests."""
    return HealthResponse(status="ok", service="commitverse-hub")
