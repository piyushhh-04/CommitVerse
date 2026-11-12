"""add_repository_deleted_state

Revision ID: a7d4d1d1f7ed
Revises: 40037b3edad7
Create Date: 2026-11-12 22:35:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "a7d4d1d1f7ed"
down_revision = "40037b3edad7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("repositories", schema=None) as batch_op:
        batch_op.drop_constraint("ck_repositories_repository_lifecycle_state")
        batch_op.create_check_constraint(
            "repository_lifecycle_state",
            "lifecycle_state IN ('provisioning', 'ready', 'deleting', 'error', 'deleted')",
        )

    op.execute(
        """
        UPDATE repositories
        SET lifecycle_state = 'deleted'
        WHERE lifecycle_state = 'deleting'
          AND slug = 'deleted~' || lower(replace(CAST(id AS TEXT), '-', ''))
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_repositories_personal_slug ON repositories (owner_user_id, lower(slug)) WHERE owner_user_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_repositories_organization_slug ON repositories (owner_organization_id, lower(slug)) WHERE owner_organization_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_repositories_owner_user_id ON repositories (owner_user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repositories_owner_organization_id ON repositories (owner_organization_id)"
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE repositories
        SET lifecycle_state = 'deleting'
        WHERE lifecycle_state = 'deleted'
        """
    )
    with op.batch_alter_table("repositories", schema=None) as batch_op:
        batch_op.drop_constraint("ck_repositories_repository_lifecycle_state")
        batch_op.create_check_constraint(
            "repository_lifecycle_state",
            "lifecycle_state IN ('provisioning', 'ready', 'deleting', 'error')",
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_repositories_personal_slug ON repositories (owner_user_id, lower(slug)) WHERE owner_user_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_repositories_organization_slug ON repositories (owner_organization_id, lower(slug)) WHERE owner_organization_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_repositories_owner_user_id ON repositories (owner_user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repositories_owner_organization_id ON repositories (owner_organization_id)"
    )
