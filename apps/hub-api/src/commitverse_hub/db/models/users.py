"""User accounts and their one-to-one public profile data."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from commitverse_hub.db.base import Base
from commitverse_hub.db.models._timestamps import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "account_state IN ('active', 'disabled')",
            name="account_state",
        ),
        CheckConstraint(
            "normalized_email = lower(normalized_email)",
            name="normalized_email",
        ),
        Index(
            "uq_users_normalized_email",
            text("lower(normalized_email)"),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    account_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    organization_memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="user", passive_deletes=True
    )
    sessions: Mapped[list["SessionRecord"]] = relationship(
        back_populates="user", passive_deletes=True
    )
    owned_repositories: Mapped[list["Repository"]] = relationship(
        foreign_keys="Repository.owner_user_id",
        back_populates="owner_user",
        passive_deletes=True,
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="actor",
        passive_deletes=True,
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        Index(
            "uq_user_profiles_username",
            text("lower(username)"),
            unique=True,
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    username: Mapped[str] = mapped_column(String(39), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[str | None] = mapped_column(String(500))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    user: Mapped[User] = relationship(back_populates="profile")
