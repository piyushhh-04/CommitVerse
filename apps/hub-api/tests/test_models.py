"""Schema metadata, constraints, relationships, and migration behavior."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CheckConstraint

from commitverse_hub.db import models
from commitverse_hub.db.base import Base

_EXPECTED_TABLES = {
    "users",
    "user_profiles",
    "organizations",
    "organization_memberships",
    "repositories",
    "repository_user_permissions",
    "invitations",
    "sessions",
    "audit_events",
}


def _migration_config(connection) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def migrated_engine(tmp_path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'hub-schema.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with engine.connect() as connection:
        command.upgrade(_migration_config(connection), "head")

    yield engine
    engine.dispose()


def test_all_approved_tables_are_registered() -> None:
    model_classes = [getattr(models, name) for name in models.__all__]

    assert set(Base.metadata.tables) == _EXPECTED_TABLES
    assert all(model.__table__.metadata is Base.metadata for model in model_classes)


def test_primary_keys_foreign_keys_and_delete_rules() -> None:
    assert [column.name for column in models.User.__table__.primary_key] == ["id"]
    assert [column.name for column in models.UserProfile.__table__.primary_key] == [
        "user_id"
    ]
    assert [column.name for column in models.OrganizationMembership.__table__.primary_key] == [
        "organization_id",
        "user_id",
    ]
    assert [column.name for column in models.RepositoryUserPermission.__table__.primary_key] == [
        "repository_id",
        "user_id",
    ]

    profile_fk = next(iter(models.UserProfile.__table__.c.user_id.foreign_keys))
    assert profile_fk.target_fullname == "users.id"
    assert profile_fk.ondelete == "CASCADE"

    repository_fks = {
        fk.parent.name: (fk.target_fullname, fk.ondelete)
        for fk in models.Repository.__table__.foreign_keys
    }
    assert repository_fks == {
        "owner_user_id": ("users.id", "RESTRICT"),
        "owner_organization_id": ("organizations.id", "RESTRICT"),
        "created_by": ("users.id", "RESTRICT"),
    }
    audit_actor = next(iter(models.AuditEvent.__table__.c.actor_user_id.foreign_keys))
    assert audit_actor.ondelete == "SET NULL"


def test_unique_and_check_constraints_are_declared() -> None:
    assert {
        index.name
        for index in models.User.__table__.indexes
        if index.unique
    } == {"uq_users_normalized_email"}
    assert {
        index.name
        for index in models.UserProfile.__table__.indexes
        if index.unique
    } == {"uq_user_profiles_username"}
    assert {
        index.name
        for index in models.Repository.__table__.indexes
        if index.unique
    } == {
        "uq_repositories_personal_slug",
        "uq_repositories_organization_slug",
    }
    assert {
        constraint.name for constraint in models.Repository.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_repositories_exactly_one_owner",
        "ck_repositories_repository_visibility",
        "ck_repositories_repository_lifecycle_state",
    }
    assert "ck_invitations_exactly_one_scope" in {
        constraint.name for constraint in models.Invitation.__table__.constraints
    }


def test_relationships_are_configured_and_one_to_one_profile() -> None:
    mapper = inspect(models.User)
    assert mapper.relationships.profile.uselist is False
    assert mapper.relationships.profile.back_populates == "user"
    assert mapper.relationships.owned_repositories.back_populates == "owner_user"
    assert mapper.relationships.repository_permissions.back_populates == "user"
    assert mapper.relationships.granted_repository_permissions.back_populates == "grantor"
    assert inspect(models.Organization).relationships.memberships.back_populates == (
        "organization"
    )
    assert inspect(models.Repository).relationships.user_permissions.back_populates == (
        "repository"
    )
    assert inspect(models.RepositoryUserPermission).relationships.user.back_populates == (
        "repository_permissions"
    )
    assert inspect(models.RepositoryUserPermission).relationships.grantor.back_populates == (
        "granted_repository_permissions"
    )


def test_repository_owner_and_slug_invariants_are_database_enforced(
    migrated_engine: Engine,
) -> None:
    user_id = uuid.uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            models.User.__table__.insert().values(
                id=user_id,
                normalized_email="owner@example.test",
                password_hash="hash",
            )
        )
        connection.execute(
            models.Repository.__table__.insert().values(
                id=uuid.uuid4(),
                owner_user_id=user_id,
                created_by=user_id,
                slug="CommitVerse",
                visibility="private",
                storage_key="opaque-1",
            )
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                models.Repository.__table__.insert().values(
                    id=uuid.uuid4(),
                    created_by=user_id,
                    slug="unowned",
                    visibility="private",
                    storage_key="opaque-2",
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                models.Repository.__table__.insert().values(
                    id=uuid.uuid4(),
                    owner_user_id=user_id,
                    created_by=user_id,
                    slug="commitverse",
                    visibility="private",
                    storage_key="opaque-3",
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                models.Repository.__table__.insert().values(
                    id=uuid.uuid4(),
                    owner_user_id=user_id,
                    created_by=user_id,
                    slug="other",
                    visibility="not-public-or-private",
                    storage_key="opaque-4",
                )
            )


def test_membership_role_and_pair_uniqueness_are_database_enforced(
    migrated_engine: Engine,
) -> None:
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            models.User.__table__.insert().values(
                id=user_id,
                normalized_email="member@example.test",
                password_hash="hash",
            )
        )
        connection.execute(
            models.Organization.__table__.insert().values(
                id=organization_id,
                slug="commitverse",
                name="CommitVerse",
                created_by=user_id,
            )
        )
        membership = models.OrganizationMembership.__table__.insert().values(
            organization_id=organization_id,
            user_id=user_id,
            role="owner",
        )
        connection.execute(membership)
        with pytest.raises(IntegrityError):
            connection.execute(membership)
        with pytest.raises(IntegrityError):
            connection.execute(
                models.OrganizationMembership.__table__.insert().values(
                    organization_id=organization_id,
                    user_id=uuid.uuid4(),
                    role="superuser",
                )
            )
        invitation = models.Invitation.__table__.insert().values(
            id=uuid.uuid4(),
            inviter_user_id=user_id,
            target_email="invitee@example.test",
            organization_id=organization_id,
            role="member",
            token_hash="hashed-token-one",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        connection.execute(invitation)
        with pytest.raises(IntegrityError):
            connection.execute(
                models.Invitation.__table__.insert().values(
                    id=uuid.uuid4(),
                    inviter_user_id=user_id,
                    target_email="invitee@example.test",
                    organization_id=organization_id,
                    role="admin",
                    token_hash="hashed-token-two",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                models.Invitation.__table__.insert().values(
                    id=uuid.uuid4(),
                    inviter_user_id=user_id,
                    target_email="other@example.test",
                    organization_id=organization_id,
                    role="reader",
                    token_hash="hashed-token-three",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )


def test_migration_upgrade_downgrade_upgrade_and_autogenerate_match(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) == _EXPECTED_TABLES | {"alembic_version"}

        migration_context = MigrationContext.configure(connection)
        assert migration_context.get_current_revision() == "a7d4d1d1f7ed"
        from alembic.autogenerate import compare_metadata

        assert compare_metadata(migration_context, Base.metadata) == []

        index_sql = {
            row.name: row.sql
            for row in connection.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type = 'index'")
            )
        }
        assert {
            "uq_users_normalized_email",
            "uq_user_profiles_username",
            "uq_organizations_slug",
            "uq_repositories_personal_slug",
            "uq_repositories_organization_slug",
            "uq_invitations_pending_organization_email",
            "uq_invitations_pending_repository_email",
        } <= index_sql.keys()
        assert "WHERE status = 'pending'" in index_sql[
            "uq_invitations_pending_organization_email"
        ]

        config = _migration_config(connection)
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == _EXPECTED_TABLES | {
            "alembic_version"
        }


def test_repository_deleted_state_migration_backfills_only_exact_tombstones(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'repository_deleted.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with engine.connect() as connection:
        command.upgrade(_migration_config(connection), "40037b3edad7")

        user_id = uuid.uuid4()
        connection.execute(
            models.User.__table__.insert().values(
                id=user_id,
                normalized_email="owner@example.test",
                password_hash="hash",
            )
        )

        exact_id = uuid.uuid4()
        ambiguous_id = uuid.uuid4()
        connection.execute(
            models.Repository.__table__.insert().values(
                id=exact_id,
                owner_user_id=user_id,
                created_by=user_id,
                slug=f"deleted~{exact_id.hex}",
                visibility="private",
                storage_key="exact-tombstone",
                lifecycle_state="deleting",
            )
        )
        connection.execute(
            models.Repository.__table__.insert().values(
                id=ambiguous_id,
                owner_user_id=user_id,
                created_by=user_id,
                slug="deleted~legacy-name",
                visibility="private",
                storage_key="ambiguous-tombstone",
                lifecycle_state="deleting",
            )
        )

        command.upgrade(_migration_config(connection), "head")
        exact_row = connection.execute(
            text(
                "SELECT lifecycle_state FROM repositories WHERE lower(replace(id, '-', '')) = :hex_id"
            ),
            {"hex_id": exact_id.hex},
        ).scalar_one()
        ambiguous_row = connection.execute(
            text(
                "SELECT lifecycle_state FROM repositories WHERE lower(replace(id, '-', '')) = :hex_id"
            ),
            {"hex_id": ambiguous_id.hex},
        ).scalar_one()
        assert exact_row == "deleted"
        assert ambiguous_row == "deleting"

        manual_deleted_id = uuid.uuid4()
        connection.execute(
            models.Repository.__table__.insert().values(
                id=manual_deleted_id,
                owner_user_id=user_id,
                created_by=user_id,
                slug="non-standard-deleted-slug",
                visibility="private",
                storage_key="manual-deleted",
                lifecycle_state="deleted",
            )
        )

        command.downgrade(_migration_config(connection), "40037b3edad7")
        downgraded_row = connection.execute(
            text(
                "SELECT lifecycle_state, slug FROM repositories WHERE lower(replace(id, '-', '')) = :hex_id"
            ),
            {"hex_id": manual_deleted_id.hex},
        ).one()
        assert downgraded_row == ("deleting", "non-standard-deleted-slug")

        command.upgrade(_migration_config(connection), "head")
        reupgraded_row = connection.execute(
            text(
                "SELECT lifecycle_state, slug FROM repositories WHERE lower(replace(id, '-', '')) = :hex_id"
            ),
            {"hex_id": manual_deleted_id.hex},
        ).one()
        assert reupgraded_row == ("deleting", "non-standard-deleted-slug")
        assert MigrationContext.configure(connection).get_current_revision() == (
            "a7d4d1d1f7ed"
        )

    engine.dispose()


def test_migration_revision_chain_is_current_and_explicit() -> None:
    package_root = Path(__file__).parents[1]
    script = ScriptDirectory.from_config(Config(str(package_root / "alembic.ini")))
    revisions = {revision.revision: revision for revision in script.walk_revisions()}

    assert set(revisions) == {"40037b3edad7", "a7d4d1d1f7ed"}
    assert revisions["40037b3edad7"].down_revision is None
    assert revisions["a7d4d1d1f7ed"].down_revision == "40037b3edad7"
