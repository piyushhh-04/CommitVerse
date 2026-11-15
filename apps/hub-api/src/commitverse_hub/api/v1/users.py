"""Authenticated privacy-preserving user discovery routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from commitverse_hub.api.v1.auth import get_authenticated_user
from commitverse_hub.db.models import User
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.users import UserDirectoryError, search_users

router = APIRouter(prefix="/users", tags=["users"])


class UserSearchResult(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str


class UserSearchResponse(BaseModel):
    items: list[UserSearchResult]
    query: str
    limit: int


@router.get("/search", response_model=UserSearchResponse)
def search_users_route(
    request: Request,
    query: Annotated[str, Query(min_length=2, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
    user: User = Depends(get_authenticated_user),
) -> UserSearchResponse:
    del user
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(503, "database_unavailable", "The Hub database is not configured.")
    try:
        users = search_users(factory, query, limit=limit)
    except ValueError as exc:
        raise HubApplicationError(422, "validation_error", str(exc)) from exc
    except UserDirectoryError as exc:
        raise HubApplicationError(503, "user_directory_unavailable", str(exc)) from exc
    return UserSearchResponse(
        items=[
            UserSearchResult(
                id=directory_user.id,
                username=directory_user.profile.username,
                display_name=directory_user.profile.display_name,
            )
            for directory_user in users
            if directory_user.profile is not None
        ],
        query=query.strip(),
        limit=limit,
    )
