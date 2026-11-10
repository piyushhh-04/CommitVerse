"""Caller-transaction-managed persistence for opaque server-side sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DatabaseSession

from commitverse_hub.auth.tokens import generate_session_token, hash_session_token
from commitverse_hub.db.models import SessionRecord, User


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Session timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def create_session_record(
    db_session: DatabaseSession,
    user_id: uuid.UUID,
    *,
    lifetime: timedelta,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> tuple[SessionRecord, str]:
    """Add and flush a hashed-token session without committing the transaction."""
    if lifetime <= timedelta(0):
        raise ValueError("Session lifetime must be positive.")
    if user_agent is not None and len(user_agent) > 512:
        raise ValueError("User agent exceeds the supported length.")

    created_at = _utc_now(now)
    token = generate_session_token()
    record = SessionRecord(
        user_id=user_id,
        token_hash=hash_session_token(token),
        created_at=created_at,
        expires_at=created_at + lifetime,
        user_agent=user_agent,
    )
    db_session.add(record)
    db_session.flush()
    return record, token


def get_active_session(
    db_session: DatabaseSession,
    token: str,
    *,
    now: datetime | None = None,
) -> SessionRecord | None:
    """Return an unrevoked, unexpired session matching the supplied raw token."""
    try:
        token_hash = hash_session_token(token)
    except ValueError:
        return None
    current_time = _utc_now(now)
    statement = (
        select(SessionRecord)
        .join(SessionRecord.user)
        .where(
            SessionRecord.token_hash == token_hash,
            SessionRecord.revoked_at.is_(None),
            SessionRecord.expires_at > current_time,
            User.account_state == "active",
        )
    )
    return db_session.scalar(statement)


def revoke_session(
    db_session: DatabaseSession,
    token: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Revoke one token atomically without committing the caller's transaction."""
    try:
        token_hash = hash_session_token(token)
    except ValueError:
        return False
    result = db_session.execute(
        update(SessionRecord)
        .where(
            SessionRecord.token_hash == token_hash,
            SessionRecord.revoked_at.is_(None),
        )
        .values(revoked_at=_utc_now(now))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def revoke_user_sessions(
    db_session: DatabaseSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Revoke every currently unrevoked session for a user in one UPDATE."""
    result = db_session.execute(
        update(SessionRecord)
        .where(
            SessionRecord.user_id == user_id,
            SessionRecord.revoked_at.is_(None),
        )
        .values(revoked_at=_utc_now(now))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0
