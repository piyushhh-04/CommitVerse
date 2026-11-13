"""Registration, login, logout, and current-user resolution routes."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from commitverse_hub.auth.cookies import clear_session_cookie, set_session_cookie
from commitverse_hub.auth.csrf import (
    generate_csrf_token,
    require_csrf_protection,
    validate_request_origin,
)
from commitverse_hub.auth.passwords import hash_password, verify_password
from commitverse_hub.auth.sessions import create_session_record, get_active_session, revoke_session
from commitverse_hub.auth.tokens import validate_session_token
from commitverse_hub.db.models import User, UserProfile
from commitverse_hub.db.session import transactional_session
from commitverse_hub.errors.handlers import HubApplicationError

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")


class AuthUserResponse(BaseModel):
    """Public account information intentionally returned to an authenticated client."""

    id: uuid.UUID
    email: str
    username: str
    display_name: str

    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    """Create a new Hub account and profile."""

    email: str
    password: str = Field(..., min_length=1, max_length=1024)
    username: str = Field(..., min_length=1, max_length=39)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("Email must be a string.")
        candidate = value.strip().lower()
        if not candidate:
            raise ValueError("Email must not be empty.")
        if " " in candidate or not _EMAIL_PATTERN.fullmatch(candidate):
            raise ValueError("Email address is invalid.")
        return candidate

    @field_validator("username", "display_name")
    @classmethod
    def trim_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class LoginRequest(BaseModel):
    """Authenticate using a normalized email and a password."""

    email: str
    password: str = Field(..., min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("Email must be a string.")
        candidate = value.strip().lower()
        if not candidate:
            raise ValueError("Email must not be empty.")
        if " " in candidate or not _EMAIL_PATTERN.fullmatch(candidate):
            raise ValueError("Email address is invalid.")
        return candidate


class AuthStatusResponse(BaseModel):
    """Generic operation result for safe session lifecycle calls."""

    status: str = "ok"


def _session_factory(request: Request):
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(
            503,
            "database_unavailable",
            "The Hub database is not configured.",
        )
    return factory


def _cookie_settings(request: Request):
    return request.app.state.settings.auth_cookie


def _allowed_origins(request: Request) -> set[str]:
    origins = getattr(request.app.state.settings, "csrf_allowed_origins", ())
    return set(origins)


def _require_origin(request: Request, *, require_csrf_for_session: str | None = None) -> None:
    origin = request.headers.get("origin")
    allowed_origins = _allowed_origins(request)
    if not validate_request_origin(origin, allowed_origins):
        raise HubApplicationError(403, "origin_not_allowed", "Origin not allowed.")
    if require_csrf_for_session is None:
        return
    csrf_token = request.headers.get("x-csrf-token")
    if not csrf_token:
        raise HubApplicationError(403, "csrf_validation_failed", "CSRF validation failed.")
    try:
        require_csrf_protection(
            require_csrf_for_session,
            csrf_token,
            origin,
            allowed_origins,
        )
    except ValueError as exc:
        raise HubApplicationError(403, "csrf_validation_failed", "CSRF validation failed.") from exc


def _normalize_username(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HubApplicationError(422, "validation_error", "Username must not be empty.")
    return normalized


def _user_payload(user: User, profile: UserProfile | None = None) -> AuthUserResponse:
    if profile is None and user.profile is not None:
        profile = user.profile
    if profile is None:
        base_username = user.normalized_email.split("@", 1)[0]
        display_name = base_username
    else:
        base_username = profile.username
        display_name = profile.display_name
    return AuthUserResponse(
        id=user.id,
        email=user.normalized_email,
        username=base_username,
        display_name=display_name,
    )


def get_authenticated_user(request: Request) -> User:
    """Resolve the current active user from the existing server-side session."""
    settings = _cookie_settings(request)
    token = request.cookies.get(settings.name)
    if not token:
        raise HubApplicationError(401, "authentication_required", "Authentication required.")
    if not validate_session_token(token):
        raise HubApplicationError(401, "authentication_failed", "Authentication failed.")

    factory = _session_factory(request)
    with factory() as db_session:
        active_session = get_active_session(db_session, token)
        if active_session is None:
            raise HubApplicationError(401, "authentication_failed", "Authentication failed.")
        user = db_session.get(User, active_session.user_id)
        if user is None or user.account_state != "active":
            raise HubApplicationError(401, "authentication_failed", "Authentication failed.")
        return user


def _has_active_session(request: Request, token: str) -> bool:
    """Check whether a well-formed cookie currently identifies an active session."""
    if not validate_session_token(token):
        return False

    factory = _session_factory(request)
    try:
        with factory() as db_session:
            return get_active_session(db_session, token) is not None
    except SQLAlchemyError as exc:
        raise HubApplicationError(
            503,
            "session_validation_failed",
            "The session could not be validated.",
        ) from exc


def require_authenticated_csrf(request: Request) -> None:
    """Require the current authenticated session's CSRF token and allow-listed origin."""
    token = request.cookies.get(_cookie_settings(request).name)
    if not token:
        raise HubApplicationError(401, "authentication_required", "Authentication required.")
    _require_origin(request, require_csrf_for_session=token)


@router.post("/register", response_model=AuthUserResponse)
async def register_account(
    payload: RegisterRequest,
    request: Request,
    response: Response,
) -> AuthUserResponse:
    """Register a new account and issue a secure opaque browser session."""
    _require_origin(request)
    factory = _session_factory(request)
    normalized_email = payload.email
    username = _normalize_username(payload.username)
    display_name = payload.display_name.strip() if payload.display_name else username

    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HubApplicationError(422, "validation_error", str(exc)) from exc

    with transactional_session(factory) as db_session:
        existing_user = db_session.scalar(
            select(User.id).where(User.normalized_email == normalized_email)
        )
        if existing_user is not None:
            raise HubApplicationError(
                409,
                "account_exists",
                "An account with this email already exists.",
            )

        username_match = db_session.scalar(
            select(UserProfile.user_id).where(
                func.lower(UserProfile.username) == username.lower()
            )
        )
        if username_match is not None:
            raise HubApplicationError(
                409,
                "username_taken",
                "This username is already taken.",
            )

        user = User(
            id=uuid.uuid4(),
            normalized_email=normalized_email,
            password_hash=password_hash,
            account_state="active",
        )
        db_session.add(user)
        try:
            db_session.flush()
        except IntegrityError as exc:
            raise HubApplicationError(
                409,
                "account_exists",
                "An account with this email already exists.",
            ) from exc

        profile = UserProfile(
            user_id=user.id,
            username=username,
            display_name=display_name,
        )
        db_session.add(profile)
        try:
            db_session.flush()
        except IntegrityError as exc:
            raise HubApplicationError(
                409,
                "username_taken",
                "This username is already taken.",
            ) from exc

        try:
            _, token = create_session_record(
                db_session,
                user.id,
                lifetime=timedelta(seconds=_cookie_settings(request).max_age_seconds),
                user_agent=request.headers.get("user-agent"),
            )
        except ValueError as exc:
            raise HubApplicationError(500, "session_creation_failed", "Session creation failed.") from exc

    set_session_cookie(response, token, _cookie_settings(request))
    response.headers["X-CSRF-Token"] = generate_csrf_token(token)
    return _user_payload(user, profile)


@router.post("/login", response_model=AuthUserResponse)
async def login_account(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> AuthUserResponse:
    """Authenticate a user and issue a secure cookie-backed session."""
    _require_origin(request)
    existing_session = request.cookies.get(_cookie_settings(request).name)
    if existing_session and _has_active_session(request, existing_session):
        _require_origin(request, require_csrf_for_session=existing_session)

    factory = _session_factory(request)
    normalized_email = payload.email
    with transactional_session(factory) as db_session:
        user = db_session.scalar(
            select(User).where(User.normalized_email == normalized_email)
        )
        if user is None or user.account_state != "active":
            raise HubApplicationError(
                401,
                "authentication_failed",
                "Invalid email or password.",
            )
        if not verify_password(user.password_hash, payload.password):
            raise HubApplicationError(
                401,
                "authentication_failed",
                "Invalid email or password.",
            )
        profile = db_session.scalar(
            select(UserProfile).where(UserProfile.user_id == user.id)
        )
        _, token = create_session_record(
            db_session,
            user.id,
            lifetime=timedelta(seconds=_cookie_settings(request).max_age_seconds),
            user_agent=request.headers.get("user-agent"),
        )

    set_session_cookie(response, token, _cookie_settings(request))
    response.headers["X-CSRF-Token"] = generate_csrf_token(token)
    return _user_payload(user, profile)


@me_router.get("/me", response_model=AuthUserResponse)
async def me(request: Request, response: Response) -> AuthUserResponse:
    """Return the authenticated user identity from the current browser session."""
    factory = _session_factory(request)
    user = get_authenticated_user(request)
    with factory() as db_session:
        profile = db_session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
        user_response = _user_payload(user, profile)

    session_token = request.cookies.get(_cookie_settings(request).name)
    if not session_token:
        raise HubApplicationError(401, "authentication_required", "Authentication required.")
    response.headers["X-CSRF-Token"] = generate_csrf_token(session_token)
    response.headers["Cache-Control"] = "no-store"
    return user_response


@router.post("/logout", response_model=AuthStatusResponse)
async def logout_account(request: Request, response: Response) -> AuthStatusResponse:
    """Revoke the current session and clear the related cookie."""
    settings = _cookie_settings(request)
    token = request.cookies.get(settings.name)
    _require_origin(request)

    if not token or not _has_active_session(request, token):
        clear_session_cookie(response, settings)
        return AuthStatusResponse()

    _require_origin(request, require_csrf_for_session=token)
    factory = _session_factory(request)
    try:
        with transactional_session(factory) as db_session:
            revoke_session(db_session, token)
    except SQLAlchemyError as exc:
        raise HubApplicationError(
            503,
            "session_revocation_failed",
            "The session could not be revoked.",
        ) from exc
    clear_session_cookie(response, settings)
    return AuthStatusResponse()
