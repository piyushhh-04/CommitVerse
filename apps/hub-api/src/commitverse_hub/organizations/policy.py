"""Organization naming, role policy, and domain errors."""

from __future__ import annotations

import re
from typing import Literal

AssignableOrganizationRole = Literal["admin", "member"]

_ORGANIZATION_SLUG_PATTERN = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class OrganizationNotFoundError(Exception):
    """Raised when an organization or membership is not visible to the caller."""


class OrganizationConflictError(Exception):
    """Raised when an organization or membership operation conflicts with state."""


class OrganizationDisabledError(OrganizationConflictError):
    """Raised when a mutation targets a disabled organization."""


class OrganizationPermissionError(Exception):
    """Raised when the caller's organization role does not permit an operation."""


class OrganizationReauthenticationError(OrganizationPermissionError):
    """Raised when ownership transfer password reauthentication fails."""


class OrganizationOperationError(Exception):
    """Raised when an organization database operation fails."""


class OrganizationValidationError(ValueError):
    """Raised when organization or membership input is invalid."""


def normalize_organization_slug(value: str) -> str:
    """Normalize and validate a URL-safe organization slug."""
    slug = value.strip().lower()
    if not _ORGANIZATION_SLUG_PATTERN.fullmatch(slug):
        raise OrganizationValidationError("Organization slug is invalid.")
    return slug


def normalize_organization_name(value: str) -> str:
    """Normalize a non-empty organization name."""
    name = value.strip()
    if not name or len(name) > 120:
        raise OrganizationValidationError(
            "Organization name must contain 1 to 120 characters."
        )
    return name


def validate_member_role(value: str) -> AssignableOrganizationRole:
    if value == "admin":
        return "admin"
    if value == "member":
        return "member"
    raise OrganizationValidationError("Organization member role is invalid.")


def can_add_member(actor_role: str, requested_role: str) -> bool:
    return actor_role == "owner" or (
        actor_role == "admin" and requested_role == "member"
    )


def can_remove_member(actor_role: str, target_role: str) -> bool:
    if target_role == "owner":
        return False
    return actor_role == "owner" or (
        actor_role == "admin" and target_role == "member"
    )
