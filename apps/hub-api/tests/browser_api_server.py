"""Disposable local API server used by the Hub Web browser integration test."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event

from commitverse_hub.config import Settings
from commitverse_hub.db.base import Base
from commitverse_hub.main import create_app


def main() -> None:
    """Run the test API against a temporary SQLite database on loopback."""
    origin = os.environ.get("HUB_BROWSER_TEST_ORIGIN")
    if not origin:
        raise RuntimeError("HUB_BROWSER_TEST_ORIGIN must be set for browser tests.")

    # The storage layer rejects symlinked path components. macOS exposes the
    # default temporary directory as /var/... even though /var is a symlink to
    # /private/var, so use the canonical system temp location when available.
    temporary_directory_root = Path("/private/tmp")
    temporary_directory_kwargs = (
        {"dir": str(temporary_directory_root)}
        if temporary_directory_root.is_dir()
        else {}
    )
    with tempfile.TemporaryDirectory(
        prefix="commitverse-hub-browser-", **temporary_directory_kwargs
    ) as directory:
        database_path = Path(directory) / "hub-browser.sqlite"
        engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        settings = Settings(
            environment="testing",
            database_url="postgresql+psycopg://browser-test@127.0.0.1/browser-test",
            csrf_allowed_origins=(origin,),
            repository_storage_root=Path(directory) / "repositories",
        )
        app = create_app(
            settings=settings,
            database_engine_factory=lambda _database_url: engine,
        )

        import uvicorn

        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=8001,
                log_level="warning",
                access_log=False,
            )
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
