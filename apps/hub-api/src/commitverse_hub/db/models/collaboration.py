"""Invitation scopes and opaque server-side session records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from commitverse_hub.db.base import Base


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(
            "(organization_id IS NOT NULL AND repository_id IS NULL) OR "
            "(organization_id IS NULL AND repository_id IS NOT NULL)",
            name="exactly_one_scope",
        ),
        CheckConstraint(
            "(organization_id IS NOT NULL AND role IN ('owner', 'admin', 'member')) OR "
            "(repository_id IS NOT NULL AND role IN ('reader', 'writer', 'admin'))",
            name="scope_compatible_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="invitation_status",
        ),
        CheckConstraint(
            "(status = 'accepted' AND accepted_at IS NOT NULL) OR "
            "(status != 'accepted' AND accepted_at IS NULL)",
            name="accepted_timestamp",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status != 'revoked' AND revoked_at IS NULL)",
            name="revoked_timestamp",
        ),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "target_email = lower(target_email)",
            name="normalized_target_email",
        ),
        Index(
            "uq_invitations_pending_organization_email",
            "organization_id",
            text("lower(target_email)"),
            unique=True,
            postgresql_where=text("status = 'pending' AND organization_id IS NOT NULL"),
            sqlite_where=text("status = 'pending' AND organization_id IS NOT NULL"),
        ),
        Index(
            "uq_invitations_pending_repository_email",
            "repository_id",
            text("lower(target_email)"),
            unique=True,
            postgresql_where=text("status = 'pending' AND repository_id IS NOT NULL"),
            sqlite_where=text("status = 'pending' AND repository_id IS NOT NULL"),
        ),
        Index("ix_invitations_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    inviter_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_email: Mapped[str] = mapped_column(String(320), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="RESTRICT"),
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inviter: Mapped["User"] = relationship(foreign_keys=[inviter_user_id])
    organization: Mapped["Organization | None"] = relationship(
        back_populates="invitations"
    )
    repository: Mapped["Repository | None"] = relationship(
        back_populates="invitations"
    )


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_sessions_user_id_expires_at", "user_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    user: Mapped["User"] = relationship(back_populates="sessions")
