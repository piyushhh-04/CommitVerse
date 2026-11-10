"""SQLAlchemy session factory and explicit transaction context."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions bound to one application-managed engine."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def transactional_session(
    factory: sessionmaker[Session],
) -> Iterator[Session]:
    """Own one transaction; commit on success, roll back on error, always close."""
    with factory() as session:
        with session.begin():
            yield session
