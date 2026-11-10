"""Lazy PostgreSQL engine construction and connectivity diagnostics."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def build_engine(database_url: str) -> Engine:
    """Create a small synchronous Psycopg-backed connection pool."""
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=3000",
        },
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
    )


def check_database_connection(engine: Engine) -> bool:
    """Run a bounded read-only connectivity probe without leaking failures."""
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    except SQLAlchemyError:
        return False
