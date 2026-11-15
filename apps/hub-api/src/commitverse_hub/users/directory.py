"""Bounded, privacy-preserving active-user discovery."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, sessionmaker

from commitverse_hub.db.models import User, UserProfile

MAX_SEARCH_LENGTH = 64
MAX_RESULTS = 20


class UserDirectoryError(Exception):
    """Raised when the user directory cannot be queried safely."""


def search_users(
    factory: sessionmaker[Session],
    query: str,
    *,
    limit: int = MAX_RESULTS,
) -> list[User]:
    """Find active users by username or display-name prefix.

    Email addresses and disabled accounts are intentionally excluded from the
    result contract. Search is prefix-only to avoid an unrestricted directory.
    """
    normalized = query.strip().casefold()
    if len(normalized) < 2 or len(normalized) > MAX_SEARCH_LENGTH:
        raise ValueError("Search query must contain 2 to 64 characters.")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError("Search limit is outside the supported range.")
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"{escaped}%"
    try:
        with factory() as db_session:
            return list(
                db_session.scalars(
                    select(User)
                    .join(UserProfile)
                    .options(joinedload(User.profile))
                    .where(
                        User.account_state == "active",
                        or_(
                            func.lower(UserProfile.username).like(pattern, escape="\\"),
                            func.lower(UserProfile.display_name).like(pattern, escape="\\"),
                        ),
                    )
                    .order_by(func.lower(UserProfile.username), User.id)
                    .limit(limit)
                )
            )
    except SQLAlchemyError as exc:
        raise UserDirectoryError("User discovery is unavailable.") from exc
