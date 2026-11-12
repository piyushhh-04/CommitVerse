"""Database configuration, resource lifecycle, and health diagnostics."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.config import Settings
from commitverse_hub.db.base import Base
from commitverse_hub.db.engine import build_engine, check_database_connection
from commitverse_hub.db.session import create_session_factory, transactional_session
from commitverse_hub.db import models as _models
from commitverse_hub.main import create_app

DATABASE_URL = "postgresql+psycopg://hub_user:secret-value@127.0.0.1:5432/hub_test"


def test_database_url_is_optional_for_non_database_configuration() -> None:
    settings = Settings.from_environment({})

    assert settings.database_url is None


def test_postgresql_url_is_accepted_and_secret_is_redacted() -> None:
    settings = Settings.from_environment({"HUB_DATABASE_URL": DATABASE_URL})

    assert settings.database_url == DATABASE_URL
    assert "secret-value" not in repr(settings)
    assert "hub_user" not in repr(settings)


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///local.db",
        "postgresql://hub_user:secret-value@localhost/hub",
        "postgresql+psycopg://hub_user:secret-value@localhost",
        "postgresql+psycopg://hub_user:secret-value@/hub",
        "not a database URL",
        "",
    ],
)
def test_invalid_database_urls_are_rejected_without_echoing_secrets(
    database_url: str,
) -> None:
    with pytest.raises(ValueError) as error:
        Settings.from_environment({"HUB_DATABASE_URL": database_url})

    assert "secret-value" not in str(error.value)


def test_engine_uses_bounded_postgresql_pool(monkeypatch) -> None:
    engine = MagicMock(spec=Engine)
    create_engine_mock = MagicMock(return_value=engine)
    monkeypatch.setattr("commitverse_hub.db.engine.create_engine", create_engine_mock)

    result = build_engine(DATABASE_URL)

    assert result is engine
    create_engine_mock.assert_called_once_with(
        DATABASE_URL,
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=3000",
        },
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
    )


def test_engine_is_created_without_opening_a_connection() -> None:
    engine = build_engine(DATABASE_URL)

    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
        assert engine.pool.size() == 2
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_session_factory_is_bound_to_engine() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = create_session_factory(engine)

    assert factory.kw["bind"] is engine
    assert not factory.kw["autoflush"]
    assert not factory.kw["expire_on_commit"]
    engine.dispose()


def test_transactional_session_closes_session() -> None:
    class TrackingSession(Session):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessionmaker(bind=engine, class_=TrackingSession)

    with transactional_session(factory) as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1

    assert session.closed
    engine.dispose()


def test_transactional_session_rolls_back_on_error() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sample (value INTEGER)"))
    factory = create_session_factory(engine)

    with pytest.raises(RuntimeError, match="abort transaction"):
        with transactional_session(factory) as session:
            session.execute(text("INSERT INTO sample (value) VALUES (1)"))
            raise RuntimeError("abort transaction")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM sample")).scalar_one() == 0
    engine.dispose()


def test_database_connectivity_probe_returns_success_for_select_one() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert check_database_connection(engine)

    engine.dispose()


def test_database_connectivity_probe_safely_handles_database_error() -> None:
    engine = MagicMock(spec=Engine)
    engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception("credential=secret-value")
    )

    assert not check_database_connection(engine)


def test_application_and_process_health_need_no_database() -> None:
    app = create_app(Settings(environment="testing"))

    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {
            "status": "ok",
            "service": "commitverse-hub",
        }
        response = client.get("/api/v1/health/database")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "service": "commitverse-hub-database",
    }


def test_database_health_returns_success_using_injected_engine() -> None:
    engine = MagicMock(spec=Engine)
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = 1
    app = create_app(
        Settings(environment="testing", database_url=DATABASE_URL),
        database_engine_factory=lambda _: engine,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "commitverse-hub-database",
    }
    engine.dispose.assert_called_once_with()


def test_database_health_failure_is_redacted_and_logged(caplog) -> None:
    engine = MagicMock(spec=Engine)
    engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception("credential=secret-value")
    )
    app = create_app(
        Settings(environment="testing", database_url=DATABASE_URL),
        database_engine_factory=lambda _: engine,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health/database",
            headers={"X-Request-ID": "database-diagnostic"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "service": "commitverse-hub-database",
    }
    assert "secret-value" not in response.text
    assert any(
        record.getMessage() == "database_connectivity_failed"
        and record.request_id == "database-diagnostic"
        for record in caplog.records
    )
    assert "secret-value" not in caplog.text
    engine.dispose.assert_called_once_with()


def test_engine_factory_runs_only_during_lifespan_and_no_migration_runs(
    monkeypatch,
) -> None:
    engine = MagicMock(spec=Engine)
    factory = MagicMock(return_value=engine)
    upgrade = MagicMock()
    monkeypatch.setattr(alembic_command, "upgrade", upgrade)
    app = create_app(
        Settings(environment="testing", database_url=DATABASE_URL),
        database_engine_factory=factory,
    )

    factory.assert_not_called()
    with TestClient(app):
        factory.assert_called_once_with(DATABASE_URL)
        engine.connect.assert_not_called()
        upgrade.assert_not_called()
        assert app.state.session_factory is not None
    engine.dispose.assert_called_once_with()


def test_alembic_uses_shared_metadata_without_embedding_credentials() -> None:
    package_root = Path(__file__).parents[1]
    config = Config(str(package_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    env_source = (package_root / "migrations" / "env.py").read_text(
        encoding="utf-8"
    )
    ast.parse(env_source)

    assert Path(script.dir).resolve() == (package_root / "migrations").resolve()
    assert config.get_main_option("sqlalchemy.url") == ""
    assert "target_metadata = Base.metadata" in env_source
    assert len(Base.metadata.tables) == 9
    revisions = list(script.walk_revisions())
    assert [revision.revision for revision in revisions] == [
        "a7d4d1d1f7ed",
        "40037b3edad7",
    ]
    assert revisions[0].down_revision == revisions[1].revision
    assert revisions[1].down_revision is None
