"""Invitation scopes and opaque server-side session records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from commitverse_hub.db.base import Base
from commitverse_hub.db.models._timestamps import TimestampMixin


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


class RepositoryIssue(Base, TimestampMixin):
    __tablename__ = "repository_issues"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(String(10000))
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    __table_args__ = (
        CheckConstraint("state IN ('open', 'closed')", name="repository_issue_state"),
        Index("ix_repository_issues_repository_state", "repository_id", "state"),
        Index("uq_repository_issue_number", "repository_id", "number", unique=True),
    )


class IssueComment(Base, TimestampMixin):
    __tablename__ = "issue_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issue_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repository_issues.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(String(10000), nullable=False)


class PullRequest(Base, TimestampMixin):
    __tablename__ = "pull_requests"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(String(10000))
    source_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    merge_commit_id: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (
        CheckConstraint("state IN ('open', 'closed', 'merged')", name="pull_request_state"),
        Index("ix_pull_requests_repository_state", "repository_id", "state"),
        Index("uq_pull_request_number", "repository_id", "number", unique=True),
    )


class PullRequestReview(Base, TimestampMixin):
    __tablename__ = "pull_request_reviews"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'approved', 'changes_requested', 'dismissed')", name="review_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    body: Mapped[str | None] = mapped_column(String(10000))


class PullRequestReviewComment(Base, TimestampMixin):
    __tablename__ = "pull_request_review_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pull_request_reviews.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(4096), nullable=False)
    line: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(String(10000), nullable=False)


class BranchProtection(Base, TimestampMixin):
    __tablename__ = "branch_protections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    require_pull_request: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    require_ci_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (Index("uq_branch_protection", "repository_id", "branch_name", unique=True),)


class CIWorkflow(Base, TimestampMixin):
    __tablename__ = "ci_workflows"
    __table_args__ = (
        Index("uq_ci_workflow", "repository_id", "name", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)


class ExecutionJob(Base, TimestampMixin):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'scheduled', 'starting', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out')",
            name="execution_job_status",
        ),
        Index("ix_execution_jobs_repository_status", "repository_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ci_workflows.id", ondelete="SET NULL")
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    commit_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(2000))


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stream: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExecutionArtifact(Base):
    __tablename__ = "execution_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(4096), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIEngineeringTask(Base, TimestampMixin):
    __tablename__ = "ai_engineering_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ai_engineering_task_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_data: Mapped[dict | None] = mapped_column(JSON)


class AIFinding(Base, TimestampMixin):
    __tablename__ = "ai_findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="ai_finding_severity",
        ),
        Index("ix_ai_findings_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_engineering_tasks.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(4096), nullable=False)
    line: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
