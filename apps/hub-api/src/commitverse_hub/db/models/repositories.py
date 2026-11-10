"""Repository metadata and direct user permission grants."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from commitverse_hub.db.base import Base
from commitverse_hub.db.models._timestamps import TimestampMixin

_REPOSITORY_NAME = (
    "(owner_user_id IS NOT NULL AND owner_organization_id IS NULL) OR "
    "(owner_user_id IS NULL AND owner_organization_id IS NOT NULL)"
)


class Repository(TimestampMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (
        CheckConstraint(_REPOSITORY_NAME, name="exactly_one_owner"),
        CheckConstraint(
            "visibility IN ('public', 'private')",
            name="repository_visibility",
        ),
        CheckConstraint(
            "lifecycle_state IN ('provisioning', 'ready', 'deleting', 'error')",
            name="repository_lifecycle_state",
        ),
        Index(
            "uq_repositories_personal_slug",
            "owner_user_id",
            text("lower(slug)"),
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
            sqlite_where=text("owner_user_id IS NOT NULL"),
        ),
        Index(
            "uq_repositories_organization_slug",
            "owner_organization_id",
            text("lower(slug)"),
            unique=True,
            postgresql_where=text("owner_organization_id IS NOT NULL"),
            sqlite_where=text("owner_organization_id IS NOT NULL"),
        ),
        Index("ix_repositories_owner_user_id", "owner_user_id"),
        Index("ix_repositories_owner_organization_id", "owner_organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        default=lambda: uuid.uuid4().hex,
    )
    lifecycle_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="provisioning", server_default="provisioning"
    )
    description: Mapped[str | None] = mapped_column(String(1000))
    owner_user: Mapped["User | None"] = relationship(
        foreign_keys=[owner_user_id], back_populates="owned_repositories"
    )
    owner_organization: Mapped["Organization | None"] = relationship(
        foreign_keys=[owner_organization_id], back_populates="repositories"
    )
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    user_permissions: Mapped[list["RepositoryUserPermission"]] = relationship(
        back_populates="repository", passive_deletes=True
    )
    invitations: Mapped[list["Invitation"]] = relationship(
        back_populates="repository", passive_deletes=True
    )


class RepositoryUserPermission(TimestampMixin, Base):
    __tablename__ = "repository_user_permissions"
    __table_args__ = (
        CheckConstraint("role IN ('reader', 'writer', 'admin')", name="repository_user_role"),
        Index("ix_repository_user_permissions_user_id", "user_id"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    repository: Mapped[Repository] = relationship(back_populates="user_permissions")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    grantor: Mapped["User"] = relationship(foreign_keys=[granted_by])
