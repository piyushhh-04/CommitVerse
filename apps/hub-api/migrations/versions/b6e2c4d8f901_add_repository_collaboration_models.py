"""add repository collaboration models

Revision ID: b6e2c4d8f901
Revises: a7d4d1d1f7ed
Create Date: 2026-11-18 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b6e2c4d8f901"
down_revision = "a7d4d1d1f7ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.String(length=10000), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint("state IN ('open', 'closed')", name="repository_issue_state"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repository_issues_repository_state", "repository_issues", ["repository_id", "state"])
    op.create_index("uq_repository_issue_number", "repository_issues", ["repository_id", "number"], unique=True)

    op.create_table(
        "issue_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(length=10000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issue_id"], ["repository_issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.String(length=10000), nullable=True),
        sa.Column("source_branch", sa.String(length=255), nullable=False),
        sa.Column("target_branch", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("merge_commit_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint("state IN ('open', 'closed', 'merged')", name="pull_request_state"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["merged_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pull_requests_repository_state", "pull_requests", ["repository_id", "state"])
    op.create_index("uq_pull_request_number", "pull_requests", ["repository_id", "number"], unique=True)

    op.create_table(
        "pull_request_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("body", sa.String(length=10000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint("state IN ('pending', 'approved', 'changes_requested', 'dismissed')", name="review_state"),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pull_request_review_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("body", sa.String(length=10000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_id"], ["pull_request_reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "branch_protections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("require_pull_request", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("required_approvals", sa.Integer(), server_default="0", nullable=False),
        sa.Column("require_ci_success", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_branch_protection", "branch_protections", ["repository_id", "branch_name"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_branch_protection", table_name="branch_protections")
    op.drop_table("branch_protections")
    op.drop_table("pull_request_review_comments")
    op.drop_table("pull_request_reviews")
    op.drop_index("uq_pull_request_number", table_name="pull_requests")
    op.drop_index("ix_pull_requests_repository_state", table_name="pull_requests")
    op.drop_table("pull_requests")
    op.drop_table("issue_comments")
    op.drop_index("uq_repository_issue_number", table_name="repository_issues")
    op.drop_index("ix_repository_issues_repository_state", table_name="repository_issues")
    op.drop_table("repository_issues")
