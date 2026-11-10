"""FastAPI application factory and local server entry point."""

from __future__ import annotations

from fastapi import FastAPI

from commitverse_hub.api.v1.router import router as v1_router
from commitverse_hub.config import Settings
from commitverse_hub.errors.handlers import register_exception_handlers
from commitverse_hub.logging.context import RequestContextMiddleware

_DESCRIPTION = (
    "The CommitVerse Hub API. The current backend foundation provides "
    "process-level health reporting and does not connect to Core or a database."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct an independent FastAPI application instance."""
    resolved_settings = settings or Settings.from_environment()
    app = FastAPI(
        title=resolved_settings.application_name,
        description=_DESCRIPTION,
        version=resolved_settings.api_version,
        debug=resolved_settings.debug,
    )
    app.state.settings = resolved_settings
    app.add_middleware(RequestContextMiddleware)
    app.include_router(v1_router, prefix=resolved_settings.api_prefix)
    register_exception_handlers(app)
    return app


def run() -> None:
    """Run the local development server on loopback."""
    import uvicorn

    from commitverse_hub.logging.setup import configure_logging

    settings = Settings.from_environment()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app,
        factory=True,
        host="127.0.0.1",
        port=8000,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
