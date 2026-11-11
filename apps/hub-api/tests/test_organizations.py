"""Organization and membership domain-service tests."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.auth.passwords import hash_password
from commitverse_hub.db.base import Base
from commitverse_hub.db.models import (
    AuditEvent,
    Organization,
    OrganizationMembership,
    User,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.organizations import (
    OrganizationConflictError,
    OrganizationDisabledError,
    OrganizationNotFoundError,
    OrganizationOperationError,
    OrganizationPermissionError,
    OrganizationReauthenticationError,
    OrganizationValidationError,
    add_organization_member,
    change_organization_member_role,
    create_organization,
    get_organization_for_member,
    leave_organization,
    list_organization_members,
    list_user_organizations,
    remove_organization_member,
    transfer_organization_ownership,
    update_organization,
)
from commitverse_hub.organizations import memberships as membership_service


@pytest.fixture
def organization_context(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'organizations.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    users = {
        "owner": uuid.uuid4(),
        "admin": uuid.uuid4(),
        "member": uuid.uuid4(),
        "other": uuid.uuid4(),
        "disabled": uuid.uuid4(),
    }
    with transactional_session(factory) as db_session:
        for name, user_id in users.items():
            db_session.add(
                User(
                    id=user_id,
                    normalized_email=f"{name}@example.test",
                    password_hash="test-only-placeholder-hash",
                    account_state="disabled" if name == "disabled" else "active",
                )
            )
    yield {"engine": engine, "factory": factory, "users": users}
    engine.dispose()


def _create_organization(context, *, owner: str = "owner") -> Organization:
    return create_organization(
        context["factory"],
        context["users"][owner],
        slug="sample-org",
        name="Sample Organization",
        request_id="request-create",
    )


def _membership(
    factory: sessionmaker[Session],
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership | None:
    with factory() as db_session:
        return db_session.get(
            OrganizationMembership,
            {"organization_id": organization_id, "user_id": user_id},
        )


def _audit_events(factory: sessionmaker[Session]) -> list[AuditEvent]:
    with factory() as db_session:
        return list(
            db_session.scalars(
                select(AuditEvent).order_by(AuditEvent.occurred_at, AuditEvent.id)
            )
        )


def test_create_organization_atomically_adds_owner_and_audit_event(
    organization_context,
) -> None:
    context = organization_context
    organization = create_organization(
        context["factory"],
        context["users"]["owner"],
        slug="  Sample-Org ",
        name="  Sample Organization  ",
        request_id="request-1",
    )

    membership = _membership(
        context["factory"], organization.id, context["users"]["owner"]
    )
    assert organization.slug == "sample-org"
    assert organization.name == "Sample Organization"
    assert membership is not None
    assert membership.role == "owner"
    events = _audit_events(context["factory"])
    assert [(event.action, event.event_metadata) for event in events] == [
        ("organization.created", {"slug": "sample-org"})
    ]


def test_create_organization_rejects_duplicate_slug_and_invalid_creator(
    organization_context,
) -> None:
    context = organization_context
    _create_organization(context)
    with pytest.raises(OrganizationConflictError):
        create_organization(
            context["factory"],
            context["users"]["other"],
            slug="SAMPLE-ORG",
            name="Second",
            request_id=None,
        )
    with pytest.raises(OrganizationNotFoundError):
        create_organization(
            context["factory"],
            uuid.uuid4(),
            slug="another-org",
            name="Another",
            request_id=None,
        )
    assert len(_audit_events(context["factory"])) == 1


def test_membership_results_remain_readable_with_default_expiring_sessions(
    organization_context,
) -> None:
    context = organization_context
    factory = sessionmaker(bind=context["engine"], autoflush=False)
    organization = create_organization(
        factory,
        context["users"]["owner"],
        slug="expiring-session-org",
        name="Expiring Session Organization",
        request_id=None,
    )
    membership = add_organization_member(
        factory,
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )

    assert membership.user_id == context["users"]["member"]
    assert membership.role == "member"
    assert membership.user.id == context["users"]["member"]


def test_organization_listing_and_detail_are_membership_scoped(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    items, total = list_user_organizations(
        context["factory"], context["users"]["owner"], limit=10, offset=0
    )

    assert total == 1
    assert [(item.slug, role) for item, role in items] == [("sample-org", "owner")]
    detail, role = get_organization_for_member(
        context["factory"], organization.id, context["users"]["owner"]
    )
    assert (detail.id, detail.slug, role) == (
        organization.id,
        organization.slug,
        "owner",
    )
    with pytest.raises(OrganizationNotFoundError):
        get_organization_for_member(
            context["factory"], organization.id, context["users"]["other"]
        )
    other_items, other_total = list_user_organizations(
        context["factory"], context["users"]["other"], limit=10, offset=0
    )
    assert other_items == []
    assert other_total == 0


def test_organization_metadata_updates_require_owner_or_admin(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["admin"],
        role="admin",
        request_id="request-add",
    )
    updated = update_organization(
        context["factory"],
        organization.id,
        context["users"]["admin"],
        slug="renamed-org",
        name="Renamed Organization",
        request_id="request-update",
    )
    assert (updated.slug, updated.name) == ("renamed-org", "Renamed Organization")
    with pytest.raises(OrganizationNotFoundError):
        update_organization(
            context["factory"],
            organization.id,
            context["users"]["other"],
            slug="unauthorized",
            name=None,
            request_id="request-denied",
        )
    update_event = next(
        event
        for event in _audit_events(context["factory"])
        if event.action == "organization.updated"
    )
    assert update_event.action == "organization.updated"
    assert update_event.event_metadata == {"changed_fields": ["slug", "name"]}


def test_disabled_organization_remains_readable_but_rejects_mutations(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    with transactional_session(context["factory"]) as db_session:
        stored = db_session.get(Organization, organization.id)
        assert stored is not None
        stored.state = "disabled"

    assert get_organization_for_member(
        context["factory"], organization.id, context["users"]["owner"]
    )[0].state == "disabled"
    members, total = list_organization_members(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        limit=10,
        offset=0,
    )
    assert total == 1
    assert members[0].role == "owner"
    with pytest.raises(OrganizationDisabledError):
        add_organization_member(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["member"],
            role="member",
            request_id="request-disabled",
        )
    assert len(_audit_events(context["factory"])) == 1


def test_owner_and_admin_add_members_with_role_restrictions(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    added_admin = add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["admin"],
        role="admin",
        request_id="request-add-admin",
    )
    added_member = add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["admin"],
        context["users"]["member"],
        role="member",
        request_id="request-add-member",
    )

    assert (added_admin.role, added_member.role) == ("admin", "member")
    with pytest.raises(OrganizationPermissionError):
        add_organization_member(
            context["factory"],
            organization.id,
            context["users"]["admin"],
            context["users"]["other"],
            role="admin",
            request_id=None,
        )
    with pytest.raises(OrganizationPermissionError):
        add_organization_member(
            context["factory"],
            organization.id,
            context["users"]["member"],
            context["users"]["other"],
            role="member",
            request_id=None,
        )
    with pytest.raises(OrganizationNotFoundError):
        add_organization_member(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["disabled"],
            role="member",
            request_id=None,
        )
    with pytest.raises(OrganizationConflictError):
        add_organization_member(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["member"],
            role="member",
            request_id=None,
        )
    assert sorted(event.action for event in _audit_events(context["factory"])) == [
        "organization.created",
        "organization.member_added",
        "organization.member_added",
    ]


def test_only_owner_can_change_non_owner_roles(organization_context) -> None:
    context = organization_context
    organization = _create_organization(context)
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["admin"],
        role="admin",
        request_id=None,
    )
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )

    changed = change_organization_member_role(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="admin",
        request_id="request-role-change",
    )
    assert changed.role == "admin"
    with pytest.raises(OrganizationPermissionError):
        change_organization_member_role(
            context["factory"],
            organization.id,
            context["users"]["admin"],
            context["users"]["member"],
            role="member",
            request_id=None,
        )
    with pytest.raises(OrganizationConflictError):
        change_organization_member_role(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["owner"],
            role="member",
            request_id=None,
        )
    with pytest.raises(OrganizationValidationError):
        change_organization_member_role(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["member"],
            role="owner",
            request_id=None,
        )
    assert any(
        event.action == "organization.member_role_changed"
        for event in _audit_events(context["factory"])
    )


def test_owner_and_admin_removal_policy(organization_context) -> None:
    context = organization_context
    organization = _create_organization(context)
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["admin"],
        role="admin",
        request_id=None,
    )
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )

    with pytest.raises(OrganizationPermissionError):
        remove_organization_member(
            context["factory"],
            organization.id,
            context["users"]["admin"],
            context["users"]["admin"],
            request_id=None,
        )
    remove_organization_member(
        context["factory"],
        organization.id,
        context["users"]["admin"],
        context["users"]["member"],
        request_id="request-member-removed",
    )
    remove_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["admin"],
        request_id="request-admin-removed",
    )
    with pytest.raises(OrganizationPermissionError):
        remove_organization_member(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["owner"],
            request_id=None,
        )
    assert _membership(
        context["factory"], organization.id, context["users"]["member"]
    ) is None
    assert sum(
        event.action == "organization.member_removed"
        for event in _audit_events(context["factory"])
    ) == 2


def test_member_can_leave_but_last_owner_cannot(organization_context) -> None:
    context = organization_context
    organization = _create_organization(context)
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )
    leave_organization(
        context["factory"],
        organization.id,
        context["users"]["member"],
        request_id="request-leave",
    )
    with pytest.raises(OrganizationConflictError):
        leave_organization(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            request_id="request-last-owner",
        )

    assert _membership(
        context["factory"], organization.id, context["users"]["member"]
    ) is None
    assert _membership(
        context["factory"], organization.id, context["users"]["owner"]
    ) is not None
    assert sum(
        event.action == "organization.member_left"
        for event in _audit_events(context["factory"])
    ) == 1


def test_owner_leave_succeeds_when_another_eligible_owner_remains(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    with transactional_session(context["factory"]) as db_session:
        db_session.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=context["users"]["other"],
                role="owner",
            )
        )
    leave_organization(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        request_id="request-owner-leave",
    )

    assert _membership(
        context["factory"], organization.id, context["users"]["owner"]
    ) is None
    assert _membership(
        context["factory"], organization.id, context["users"]["other"]
    ).role == "owner"
    assert any(
        event.action == "organization.member_left"
        for event in _audit_events(context["factory"])
    )


def test_ownership_transfer_reauthenticates_and_audits_without_password(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    password = "current-password-value"
    with transactional_session(context["factory"]) as db_session:
        owner = db_session.get(User, context["users"]["owner"])
        assert owner is not None
        owner.password_hash = hash_password(password)
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )

    transfer_organization_ownership(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        current_password=password,
        request_id="request-transfer",
    )

    assert _membership(
        context["factory"], organization.id, context["users"]["owner"]
    ).role == "admin"
    assert _membership(
        context["factory"], organization.id, context["users"]["member"]
    ).role == "owner"
    event = next(
        event
        for event in _audit_events(context["factory"])
        if event.action == "organization.ownership_transferred"
    )
    assert event.action == "organization.ownership_transferred"
    assert event.event_metadata == {
        "previous_owner_user_id": str(context["users"]["owner"]),
        "new_owner_user_id": str(context["users"]["member"]),
    }
    assert password not in str(event.event_metadata)


def test_failed_ownership_transfer_rolls_back_without_success_audit(
    organization_context,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    with transactional_session(context["factory"]) as db_session:
        owner = db_session.get(User, context["users"]["owner"])
        assert owner is not None
        owner.password_hash = hash_password("the-correct-password")
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )
    prior_event_count = len(_audit_events(context["factory"]))

    with pytest.raises(OrganizationReauthenticationError):
        transfer_organization_ownership(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["member"],
            current_password="incorrect-password",
            request_id="request-failed-transfer",
        )

    assert _membership(
        context["factory"], organization.id, context["users"]["owner"]
    ).role == "owner"
    assert _membership(
        context["factory"], organization.id, context["users"]["member"]
    ).role == "member"
    assert len(_audit_events(context["factory"])) == prior_event_count


def test_ownership_transfer_rolls_back_if_audit_write_fails(
    organization_context,
    monkeypatch,
) -> None:
    context = organization_context
    organization = _create_organization(context)
    with transactional_session(context["factory"]) as db_session:
        owner = db_session.get(User, context["users"]["owner"])
        assert owner is not None
        owner.password_hash = hash_password("the-correct-password")
    add_organization_member(
        context["factory"],
        organization.id,
        context["users"]["owner"],
        context["users"]["member"],
        role="member",
        request_id=None,
    )
    prior_event_count = len(_audit_events(context["factory"]))
    monkeypatch.setattr(
        membership_service,
        "_audit_event",
        lambda *_args, **_kwargs: AuditEvent(action="invalid-test-event"),
    )

    with pytest.raises(OrganizationOperationError):
        transfer_organization_ownership(
            context["factory"],
            organization.id,
            context["users"]["owner"],
            context["users"]["member"],
            current_password="the-correct-password",
            request_id="request-failed-audit",
        )

    assert _membership(
        context["factory"], organization.id, context["users"]["owner"]
    ).role == "owner"
    assert _membership(
        context["factory"], organization.id, context["users"]["member"]
    ).role == "member"
    assert len(_audit_events(context["factory"])) == prior_event_count


def test_postgresql_concurrent_owner_leaves_preserve_one_eligible_owner() -> None:
    database_url = os.environ.get("HUB_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("HUB_TEST_DATABASE_URL is not configured.")

    engine = create_engine(database_url)
    schema = f"hub_organization_test_{uuid.uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped_engine = engine.execution_options(
            schema_translate_map={None: schema}
        )
        Base.metadata.create_all(scoped_engine)
        factory = sessionmaker(
            bind=scoped_engine,
            autoflush=False,
            expire_on_commit=False,
        )
        owner_ids = (uuid.uuid4(), uuid.uuid4())
        with transactional_session(factory) as db_session:
            for index, owner_id in enumerate(owner_ids):
                db_session.add(
                    User(
                        id=owner_id,
                        normalized_email=f"concurrent-owner-{index}@example.test",
                        password_hash="test-only-placeholder-hash",
                    )
                )
        organization = create_organization(
            factory,
            owner_ids[0],
            slug="concurrent-org",
            name="Concurrent Organization",
            request_id="request-create",
        )
        with transactional_session(factory) as db_session:
            db_session.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=owner_ids[1],
                    role="owner",
                )
            )

        start = Barrier(2)

        def leave(user_id: uuid.UUID) -> bool:
            start.wait(timeout=10)
            try:
                leave_organization(
                    factory,
                    organization.id,
                    user_id,
                    request_id="request-concurrent-leave",
                )
            except OrganizationConflictError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(leave, owner_ids))

        assert sum(outcomes) == 1
        with factory() as db_session:
            remaining_owners = list(
                db_session.scalars(
                    select(OrganizationMembership.user_id).where(
                        OrganizationMembership.organization_id == organization.id,
                        OrganizationMembership.role == "owner",
                    )
                )
            )
        assert len(remaining_owners) == 1
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()
