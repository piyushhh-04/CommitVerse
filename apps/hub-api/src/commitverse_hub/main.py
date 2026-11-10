"""FastAPI application factory and local server entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from commitverse_hub.api.v1.router import router as v1_router
from commitverse_hub.config import Settings
from commitverse_hub.db.engine import build_engine
from commitverse_hub.db.session import create_session_factory
from commitverse_hub.errors.handlers import register_exception_handlers
from commitverse_hub.logging.context import RequestContextMiddleware

_DESCRIPTION = (
    "The CommitVerse Hub API. The current backend foundation provides "
    "health diagnostics and does not connect to CommitVerse Core."
)


def create_app(
    settings: Settings | None = None,
    *,
    database_engine_factory: Callable[[str], Engine] | None = None,
) -> FastAPI:
    """Construct an independent FastAPI application instance."""
    resolved_settings = settings or Settings.from_environment()
    engine_factory = database_engine_factory or build_engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = (
            engine_factory(resolved_settings.database_url)
            if resolved_settings.database_url is not None
            else None
        )
        app.state.db_engine = engine
        app.state.session_factory = (
            None if engine is None else create_session_factory(engine)
        )
        try:
            yield
        finally:
            try:
                if engine is not None:
                    engine.dispose()
            finally:
                app.state.db_engine = None
                app.state.session_factory = None

    app = FastAPI(
        title=resolved_settings.application_name,
        description=_DESCRIPTION,
        version=resolved_settings.api_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.db_engine = None
    app.state.session_factory = None
    app.state.database_engine_factory = engine_factory
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
