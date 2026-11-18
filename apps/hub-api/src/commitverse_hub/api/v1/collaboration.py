"""REST endpoints for repository issues and pull requests."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.api.v1.auth import get_authenticated_user, require_authenticated_csrf
from commitverse_hub.collaboration.service import (
    CollaborationConflictError,
    CollaborationError,
    create_issue,
    create_issue_comment,
    create_pull_request,
    create_review,
    create_review_comment,
    list_review_comments,
    list_issue_comments,
    list_issues,
    list_pull_requests,
    merge_pull_request,
    update_issue,
    upsert_branch_protection,
)
from commitverse_hub.db.models import (
    BranchProtection,
    IssueComment,
    PullRequest,
    PullRequestReview,
    PullRequestReviewComment,
    RepositoryIssue,
    User,
)
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.repositories.service import (
    RepositoryNotFoundError,
    RepositoryOperationError,
    RepositoryPermissionError,
)


router = APIRouter(prefix="/repositories", tags=["repository-collaboration"])


class IssueCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=10000)
    model_config = ConfigDict(extra="forbid")


class IssueUpdateRequest(BaseModel):
    state: Literal["open", "closed"]
    model_config = ConfigDict(extra="forbid")


class IssueResponse(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    body: str | None
    state: Literal["open", "closed"]
    author_user_id: uuid.UUID
    assignee_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_issue(cls, issue: RepositoryIssue) -> "IssueResponse":
        return cls.model_validate(issue, from_attributes=True)


class IssueListResponse(BaseModel):
    items: list[IssueResponse]
    total: int


class CommentCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    model_config = ConfigDict(extra="forbid")


class CommentResponse(BaseModel):
    id: uuid.UUID
    issue_id: uuid.UUID
    author_user_id: uuid.UUID
    body: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_comment(cls, comment: IssueComment) -> "CommentResponse":
        return cls.model_validate(comment, from_attributes=True)


class PullRequestCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=10000)
    source_branch: str = Field(min_length=1, max_length=255)
    target_branch: str = Field(min_length=1, max_length=255)
    draft: bool = False
    model_config = ConfigDict(extra="forbid")


class PullRequestResponse(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    body: str | None
    source_branch: str
    target_branch: str
    state: Literal["open", "closed", "merged"]
    author_user_id: uuid.UUID
    merged_at: datetime | None
    merged_by_user_id: uuid.UUID | None
    merge_commit_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_pull_request(cls, pull_request: PullRequest) -> "PullRequestResponse":
        return cls.model_validate(pull_request, from_attributes=True)


class ReviewCreateRequest(BaseModel):
    state: Literal["approved", "changes_requested", "dismissed"]
    body: str | None = Field(default=None, max_length=10000)
    model_config = ConfigDict(extra="forbid")


class ReviewResponse(BaseModel):
    id: uuid.UUID
    pull_request_id: uuid.UUID
    reviewer_user_id: uuid.UUID
    state: Literal["pending", "approved", "changes_requested", "dismissed"]
    body: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_review(cls, review: PullRequestReview) -> "ReviewResponse":
        return cls.model_validate(review, from_attributes=True)


class ReviewCommentCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    line: int | None = Field(default=None, ge=1)
    body: str = Field(min_length=1, max_length=10000)
    model_config = ConfigDict(extra="forbid")


class ReviewCommentResponse(BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID
    author_user_id: uuid.UUID
    path: str
    line: int | None
    body: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_comment(cls, comment: PullRequestReviewComment) -> "ReviewCommentResponse":
        return cls.model_validate(comment, from_attributes=True)


class BranchProtectionRequest(BaseModel):
    require_pull_request: bool = True
    required_approvals: int = Field(default=0, ge=0, le=20)
    require_ci_success: bool = False
    model_config = ConfigDict(extra="forbid")


class BranchProtectionResponse(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    branch_name: str
    require_pull_request: bool
    required_approvals: int
    require_ci_success: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_protection(cls, protection: BranchProtection) -> "BranchProtectionResponse":
        return cls.model_validate(protection, from_attributes=True)


def _factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(503, "database_unavailable", "The Hub database is not configured.")
    return factory


def _storage_path(request: Request, storage_key: str):
    return request.app.state.settings.repository_storage_root / f"{storage_key}.git"


def _error(exc: Exception) -> HubApplicationError:
    if isinstance(exc, RepositoryNotFoundError):
        return HubApplicationError(404, "repository_not_found", str(exc))
    if isinstance(exc, RepositoryPermissionError):
        return HubApplicationError(403, "repository_permission_denied", str(exc))
    if isinstance(exc, CollaborationConflictError):
        return HubApplicationError(409, "collaboration_conflict", str(exc))
    if isinstance(exc, CollaborationError):
        return HubApplicationError(404, "collaboration_not_found", str(exc))
    if isinstance(exc, RepositoryOperationError):
        return HubApplicationError(503, "repository_unavailable", str(exc))
    if isinstance(exc, ValueError):
        return HubApplicationError(422, "validation_error", str(exc))
    raise TypeError("Unsupported collaboration exception.")


@router.post("/{repository_id}/issues", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
def create_repository_issue(repository_id: uuid.UUID, payload: IssueCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    try:
        issue = create_issue(_factory(request), repository_id, user.id, title=payload.title, body=payload.body)
        return IssueResponse.from_issue(issue)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/{repository_id}/issues", response_model=IssueListResponse)
def get_repository_issues(repository_id: uuid.UUID, request: Request, state: Literal["open", "closed", "all"] = "open", limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), user: User = Depends(get_authenticated_user)):
    try:
        items, total = list_issues(_factory(request), repository_id, user.id, state=state, limit=limit, offset=offset)
        return IssueListResponse(items=[IssueResponse.from_issue(item) for item in items], total=total)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, ValueError) as exc:
        raise _error(exc) from exc


@router.patch("/{repository_id}/issues/{issue_id}", response_model=IssueResponse)
def patch_repository_issue(repository_id: uuid.UUID, issue_id: uuid.UUID, payload: IssueUpdateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    try:
        issue = update_issue(_factory(request), repository_id, issue_id, user.id, state=payload.state)
        return IssueResponse.from_issue(issue)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{repository_id}/issues/{issue_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def create_repository_issue_comment(repository_id: uuid.UUID, issue_id: uuid.UUID, payload: CommentCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    try:
        comment = create_issue_comment(_factory(request), repository_id, issue_id, user.id, body=payload.body)
        return CommentResponse.from_comment(comment)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/{repository_id}/issues/{issue_id}/comments", response_model=list[CommentResponse])
def get_repository_issue_comments(repository_id: uuid.UUID, issue_id: uuid.UUID, request: Request, user: User = Depends(get_authenticated_user)):
    try:
        comments = list_issue_comments(_factory(request), repository_id, issue_id, user.id)
        return [CommentResponse.from_comment(comment) for comment in comments]
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{repository_id}/pull-requests", response_model=PullRequestResponse, status_code=status.HTTP_201_CREATED)
def create_repository_pull_request(repository_id: uuid.UUID, payload: PullRequestCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        from commitverse_hub.db.models import Repository
        with factory() as db:
            repository = db.get(Repository, repository_id)
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            storage_key = repository.storage_key
        pull_request = create_pull_request(
            factory,
            repository_id,
            user.id,
            title=payload.title,
            body=payload.body,
            source_branch=payload.source_branch,
            target_branch=payload.target_branch,
            draft=payload.draft,
            storage_path=_storage_path(request, storage_key),
        )
        return PullRequestResponse.from_pull_request(pull_request)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, CollaborationConflictError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/{repository_id}/pull-requests", response_model=list[PullRequestResponse])
def get_repository_pull_requests(repository_id: uuid.UUID, request: Request, state: Literal["open", "closed", "merged", "all"] = "open", user: User = Depends(get_authenticated_user)):
    try:
        pull_requests = list_pull_requests(_factory(request), repository_id, user.id, state=state)
        return [PullRequestResponse.from_pull_request(item) for item in pull_requests]
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{repository_id}/pull-requests/{pull_request_id}/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_repository_pull_request_review(repository_id: uuid.UUID, pull_request_id: uuid.UUID, payload: ReviewCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    try:
        review = create_review(_factory(request), repository_id, pull_request_id, user.id, state=payload.state, body=payload.body)
        return ReviewResponse.from_review(review)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.post(
    "/{repository_id}/pull-requests/{pull_request_id}/reviews/{review_id}/comments",
    response_model=ReviewCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository_review_comment(
    repository_id: uuid.UUID,
    pull_request_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: ReviewCommentCreateRequest,
    request: Request,
    user: User = Depends(get_authenticated_user),
):
    require_authenticated_csrf(request)
    try:
        comment = create_review_comment(
            _factory(request),
            repository_id,
            pull_request_id,
            review_id,
            user.id,
            path=payload.path,
            line=payload.line,
            body=payload.body,
        )
        return ReviewCommentResponse.from_comment(comment)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.get(
    "/{repository_id}/pull-requests/{pull_request_id}/review-comments",
    response_model=list[ReviewCommentResponse],
)
def get_repository_review_comments(
    repository_id: uuid.UUID,
    pull_request_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
):
    try:
        comments = list_review_comments(
            _factory(request),
            repository_id,
            pull_request_id,
            user.id,
        )
        return [ReviewCommentResponse.from_comment(comment) for comment in comments]
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{repository_id}/pull-requests/{pull_request_id}/merge", response_model=PullRequestResponse)
def merge_repository_pull_request(repository_id: uuid.UUID, pull_request_id: uuid.UUID, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        from commitverse_hub.db.models import Repository
        with factory() as db:
            repository = db.get(Repository, repository_id)
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            storage_key = repository.storage_key
        pull_request = merge_pull_request(
            factory,
            repository_id,
            pull_request_id,
            user.id,
            storage_path=_storage_path(request, storage_key),
        )
        return PullRequestResponse.from_pull_request(pull_request)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, CollaborationError, CollaborationConflictError, ValueError) as exc:
        raise _error(exc) from exc


@router.put("/{repository_id}/branches/{branch_name}/protection", response_model=BranchProtectionResponse)
def put_repository_branch_protection(repository_id: uuid.UUID, branch_name: str, payload: BranchProtectionRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    try:
        protection = upsert_branch_protection(
            _factory(request),
            repository_id,
            user.id,
            branch_name=branch_name,
            require_pull_request=payload.require_pull_request,
            required_approvals=payload.required_approvals,
            require_ci_success=payload.require_ci_success,
        )
        return BranchProtectionResponse.from_protection(protection)
    except (RepositoryNotFoundError, RepositoryPermissionError, RepositoryOperationError, ValueError) as exc:
        raise _error(exc) from exc
