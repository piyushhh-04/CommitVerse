"""Versioned API route registration."""

from fastapi import APIRouter

from commitverse_hub.api.v1.auth import me_router, router as auth_router
from commitverse_hub.api.v1.browse import router as browse_router
from commitverse_hub.api.v1.collaboration import router as collaboration_router
from commitverse_hub.api.v1.platform import router as platform_router
from commitverse_hub.api.v1.health import router as health_router
from commitverse_hub.api.v1.organizations import (
    invitations_router,
    router as organizations_router,
)
from commitverse_hub.api.v1.repositories import (
    organization_router as organization_repositories_router,
    router as repositories_router,
)
from commitverse_hub.api.v1.users import router as users_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(me_router)
router.include_router(organizations_router)
router.include_router(invitations_router)
router.include_router(repositories_router)
router.include_router(organization_repositories_router)
router.include_router(users_router)
router.include_router(browse_router)
router.include_router(collaboration_router)
router.include_router(platform_router)
