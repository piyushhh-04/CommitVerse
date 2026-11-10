"""Narrow adapter for the public CommitVerse Core repository API."""

from __future__ import annotations

from pathlib import Path

from commitverse_core.repository import (
    RepositoryError as CoreRepositoryError,
    discover_repository,
    initialize_repository,
)


class CoreAdapterError(Exception):
    """Raised when CommitVerse Core cannot initialize or verify a repository."""


def initialize_bare_repository(path: Path) -> None:
    """Initialize a new bare repository through Core and verify its capability."""
    try:
        repository = initialize_repository(path, bare=True)
    except (CoreRepositoryError, OSError, RuntimeError, ValueError) as exc:
        raise CoreAdapterError("CommitVerse Core could not initialize the repository.") from exc
    if not repository.bare or not repository.created:
        raise CoreAdapterError("CommitVerse Core did not initialize a new bare repository.")
    verify_bare_repository(path)


def verify_bare_repository(path: Path) -> None:
    """Verify that Core discovers exactly the requested path as a bare repository."""
    try:
        repository = discover_repository(path)
    except (CoreRepositoryError, OSError, RuntimeError, ValueError) as exc:
        raise CoreAdapterError("CommitVerse Core could not verify the repository.") from exc
    if not repository.bare or repository.git_dir != path:
        raise CoreAdapterError("CommitVerse Core discovered an unexpected repository.")
