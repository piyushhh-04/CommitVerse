"""Versioned API route registration."""

from fastapi import APIRouter

from commitverse_hub.api.v1.auth import me_router, router as auth_router
from commitverse_hub.api.v1.health import router as health_router
from commitverse_hub.api.v1.organizations import router as organizations_router
from commitverse_hub.api.v1.repositories import router as repositories_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(me_router)
router.include_router(organizations_router)
router.include_router(repositories_router)
