"""Persistent repository collaboration workflows backed by real Core branches."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from commitverse_core.merge import MergeError, merge_branch
from commitverse_core.refs import current_branch, resolve_branch, set_head_symbolic
from commitverse_core.repository import Repository as CoreRepository, discover_repository

from commitverse_hub.db.models import (
    BranchProtection,
    IssueComment,
    OrganizationMembership,
    PullRequest,
    PullRequestReview,
    PullRequestReviewComment,
    Repository,
    RepositoryIssue,
    RepositoryUserPermission,
    ExecutionJob,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.repositories.service import (
    RepositoryNotFoundError,
    RepositoryOperationError,
    RepositoryPermissionError,
    get_repository_for_access,
)


class CollaborationError(Exception):
    pass


class CollaborationConflictError(CollaborationError):
    pass


def _text(value: str, *, field: str, max_length: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required.")
    if len(cleaned) > max_length:
        raise ValueError(f"{field} is too long.")
    return cleaned


def _authorize_write(
    db_session: Session,
    repository: Repository,
    actor_user_id: uuid.UUID,
) -> None:
    if repository.owner_user_id == actor_user_id:
        return
    if repository.owner_organization_id is not None:
        membership = db_session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == repository.owner_organization_id,
                OrganizationMembership.user_id == actor_user_id,
            )
        )
        if membership is not None and membership.role in {"owner", "admin"}:
            return
    permission = db_session.get(RepositoryUserPermission, (repository.id, actor_user_id))
    if permission is not None and permission.role in {"writer", "admin"}:
        return
    raise RepositoryPermissionError("Repository write access is required.")


def _load_repository(factory: sessionmaker[Session], repository_id: uuid.UUID, actor_user_id: uuid.UUID) -> Repository:
    try:
        return get_repository_for_access(factory, repository_id, actor_user_id)
    except RepositoryNotFoundError:
        raise


def create_issue(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    title: str,
    body: str | None,
) -> RepositoryIssue:
    title = _text(title, field="Issue title", max_length=300)
    body = None if body is None else _text(body, field="Issue body", max_length=10000)
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None or repository.lifecycle_state != "ready":
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            number = int(db_session.scalar(
                select(func.coalesce(func.max(RepositoryIssue.number), 0)).where(
                    RepositoryIssue.repository_id == repository_id
                )
            ) or 0) + 1
            issue = RepositoryIssue(
                repository_id=repository_id,
                number=number,
                title=title,
                body=body,
                author_user_id=actor_user_id,
            )
            db_session.add(issue)
            db_session.flush()
            db_session.refresh(issue)
            return issue
    except (RepositoryNotFoundError, RepositoryPermissionError, ValueError):
        raise
    except (IntegrityError, SQLAlchemyError) as exc:
        raise RepositoryOperationError("Issue could not be created.") from exc


def list_issues(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    state: str,
    limit: int,
    offset: int,
) -> tuple[list[RepositoryIssue], int]:
    _load_repository(factory, repository_id, actor_user_id)
    if state not in {"open", "closed", "all"}:
        raise ValueError("Issue state is invalid.")
    with factory() as db_session:
        filters = [RepositoryIssue.repository_id == repository_id]
        if state != "all":
            filters.append(RepositoryIssue.state == state)
        total = db_session.scalar(select(func.count()).select_from(RepositoryIssue).where(*filters))
        items = list(db_session.scalars(
            select(RepositoryIssue).where(*filters).order_by(
                RepositoryIssue.number.desc()
            ).limit(limit).offset(offset)
        ))
        return items, int(total or 0)


def update_issue(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    issue_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    state: str,
) -> RepositoryIssue:
    if state not in {"open", "closed"}:
        raise ValueError("Issue state is invalid.")
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            issue = db_session.scalar(select(RepositoryIssue).where(
                RepositoryIssue.id == issue_id,
                RepositoryIssue.repository_id == repository_id,
            ).with_for_update())
            if issue is None:
                raise CollaborationError("Issue not found.")
            issue.state = state
            db_session.flush()
            db_session.refresh(issue)
            return issue
    except (RepositoryNotFoundError, RepositoryPermissionError, CollaborationError, ValueError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Issue could not be updated.") from exc


def create_issue_comment(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    issue_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    body: str,
) -> IssueComment:
    body = _text(body, field="Comment", max_length=10000)
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            issue = db_session.scalar(select(RepositoryIssue).where(
                RepositoryIssue.id == issue_id,
                RepositoryIssue.repository_id == repository_id,
            ))
            if issue is None:
                raise CollaborationError("Issue not found.")
            comment = IssueComment(issue_id=issue.id, author_user_id=actor_user_id, body=body)
            db_session.add(comment)
            db_session.flush()
            db_session.refresh(comment)
            return comment
    except (RepositoryNotFoundError, RepositoryPermissionError, CollaborationError, ValueError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Issue comment could not be created.") from exc


def list_issue_comments(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    issue_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> list[IssueComment]:
    _load_repository(factory, repository_id, actor_user_id)
    with factory() as db_session:
        issue = db_session.scalar(select(RepositoryIssue).where(
            RepositoryIssue.id == issue_id,
            RepositoryIssue.repository_id == repository_id,
        ))
        if issue is None:
            raise CollaborationError("Issue not found.")
        return list(db_session.scalars(
            select(IssueComment).where(IssueComment.issue_id == issue_id).order_by(IssueComment.created_at)
        ))


def create_pull_request(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    title: str,
    body: str | None,
    source_branch: str,
    target_branch: str,
    draft: bool,
    storage_path,
) -> PullRequest:
    title = _text(title, field="Pull request title", max_length=300)
    body = None if body is None else _text(body, field="Pull request body", max_length=10000)
    source_branch = _text(source_branch, field="Source branch", max_length=255)
    target_branch = _text(target_branch, field="Target branch", max_length=255)
    if source_branch == target_branch:
        raise CollaborationConflictError("Source and target branches must differ.")
    try:
        core_repository = discover_repository(storage_path)
    except Exception as exc:
        raise RepositoryOperationError("Repository storage could not be opened.") from exc
    try:
        resolve_branch(core_repository, source_branch)
        resolve_branch(core_repository, target_branch)
    except Exception as exc:
        raise CollaborationError("Source or target branch was not found.") from exc
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            number = int(db_session.scalar(
                select(func.coalesce(func.max(PullRequest.number), 0)).where(
                    PullRequest.repository_id == repository_id
                )
            ) or 0) + 1
            pull_request = PullRequest(
                repository_id=repository_id,
                number=number,
                title=title,
                body=body,
                source_branch=source_branch,
                target_branch=target_branch,
                author_user_id=actor_user_id,
                state="open",
            )
            db_session.add(pull_request)
            db_session.flush()
            db_session.refresh(pull_request)
            return pull_request
    except (RepositoryNotFoundError, RepositoryPermissionError, CollaborationError, ValueError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Pull request could not be created.") from exc


def list_pull_requests(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    state: str,
) -> list[PullRequest]:
    _load_repository(factory, repository_id, actor_user_id)
    if state not in {"open", "closed", "merged", "all"}:
        raise ValueError("Pull request state is invalid.")
    with factory() as db_session:
        filters = [PullRequest.repository_id == repository_id]
        if state != "all":
            filters.append(PullRequest.state == state)
        return list(db_session.scalars(
            select(PullRequest).where(*filters).order_by(PullRequest.number.desc())
        ))


def create_review(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    pull_request_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    state: str,
    body: str | None,
) -> PullRequestReview:
    if state not in {"approved", "changes_requested", "dismissed"}:
        raise ValueError("Review state is invalid.")
    body = None if body is None else _text(body, field="Review", max_length=10000)
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            pull_request = db_session.scalar(select(PullRequest).where(
                PullRequest.id == pull_request_id,
                PullRequest.repository_id == repository_id,
            ))
            if pull_request is None or pull_request.state != "open":
                raise CollaborationError("Pull request not found or not open.")
            review = PullRequestReview(
                pull_request_id=pull_request.id,
                reviewer_user_id=actor_user_id,
                state=state,
                body=body,
            )
            db_session.add(review)
            db_session.flush()
            db_session.refresh(review)
            return review
    except (RepositoryNotFoundError, RepositoryPermissionError, CollaborationError, ValueError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Review could not be created.") from exc


def create_review_comment(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    pull_request_id: uuid.UUID,
    review_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    path: str,
    line: int | None,
    body: str,
) -> PullRequestReviewComment:
    path = _text(path, field="Review comment path", max_length=4096)
    body = _text(body, field="Review comment", max_length=10000)
    if line is not None and line < 1:
        raise ValueError("Review comment line must be positive.")
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            review = db_session.scalar(select(PullRequestReview).where(
                PullRequestReview.id == review_id,
                PullRequestReview.pull_request_id == pull_request_id,
            ))
            pull_request = db_session.scalar(select(PullRequest).where(
                PullRequest.id == pull_request_id,
                PullRequest.repository_id == repository_id,
            ))
            if review is None or pull_request is None:
                raise CollaborationError("Review or pull request not found.")
            comment = PullRequestReviewComment(
                review_id=review.id,
                author_user_id=actor_user_id,
                path=path,
                line=line,
                body=body,
            )
            db_session.add(comment)
            db_session.flush()
            db_session.refresh(comment)
            return comment
    except (RepositoryNotFoundError, RepositoryPermissionError, CollaborationError, ValueError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Review comment could not be created.") from exc


def list_review_comments(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    pull_request_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> list[PullRequestReviewComment]:
    _load_repository(factory, repository_id, actor_user_id)
    with factory() as db_session:
        pull_request = db_session.scalar(select(PullRequest).where(
            PullRequest.id == pull_request_id,
            PullRequest.repository_id == repository_id,
        ))
        if pull_request is None:
            raise CollaborationError("Pull request not found.")
        review_ids = db_session.scalars(
            select(PullRequestReview.id).where(
                PullRequestReview.pull_request_id == pull_request_id
            )
        ).all()
        if not review_ids:
            return []
        return list(db_session.scalars(
            select(PullRequestReviewComment)
            .where(PullRequestReviewComment.review_id.in_(review_ids))
            .order_by(PullRequestReviewComment.created_at)
        ))


def merge_pull_request(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    pull_request_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    storage_path,
) -> PullRequest:
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            pull_request = db_session.scalar(select(PullRequest).where(
                PullRequest.id == pull_request_id,
                PullRequest.repository_id == repository_id,
            ).with_for_update())
            if pull_request is None or pull_request.state != "open":
                raise CollaborationError("Pull request not found or not open.")

            protection = db_session.scalar(select(BranchProtection).where(
                BranchProtection.repository_id == repository_id,
                BranchProtection.branch_name == pull_request.target_branch,
            ))
            if protection is not None and protection.required_approvals > 0:
                approvals = int(db_session.scalar(
                    select(func.count()).select_from(PullRequestReview).where(
                        PullRequestReview.pull_request_id == pull_request.id,
                        PullRequestReview.state == "approved",
                    )
                ) or 0)
                if approvals < protection.required_approvals:
                    raise CollaborationConflictError("Required pull request approvals are missing.")
            if protection is not None and protection.require_ci_success:
                core_repository = discover_repository(storage_path)
                source_commit = resolve_branch(core_repository, pull_request.source_branch)
                succeeded = db_session.scalar(
                    select(ExecutionJob.id).where(
                        ExecutionJob.repository_id == repository_id,
                        ExecutionJob.commit_id == source_commit,
                        ExecutionJob.status == "succeeded",
                    ).limit(1)
                )
                if succeeded is None:
                    raise CollaborationConflictError("A successful required CI execution is missing.")

            core_repository = discover_repository(storage_path)
            if current_branch(core_repository) != pull_request.target_branch:
                set_head_symbolic(
                    core_repository,
                    f"refs/heads/{pull_request.target_branch}",
                )
            try:
                _merge_status, merge_commit_id = merge_branch(
                    core_repository,
                    pull_request.source_branch,
                )
            except MergeError as exc:
                raise CollaborationConflictError(str(exc)) from exc

            pull_request.state = "merged"
            pull_request.merged_at = datetime.now(UTC)
            pull_request.merged_by_user_id = actor_user_id
            pull_request.merge_commit_id = merge_commit_id
            db_session.flush()
            db_session.refresh(pull_request)
            return pull_request
    except (
        RepositoryNotFoundError,
        RepositoryPermissionError,
        CollaborationError,
        CollaborationConflictError,
    ):
        raise
    except Exception as exc:
        raise RepositoryOperationError("Pull request could not be merged.") from exc


def upsert_branch_protection(
    factory: sessionmaker[Session],
    repository_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    branch_name: str,
    require_pull_request: bool,
    required_approvals: int,
    require_ci_success: bool,
) -> BranchProtection:
    branch_name = _text(branch_name, field="Branch name", max_length=255)
    if required_approvals < 0 or required_approvals > 20:
        raise ValueError("Required approvals must be between 0 and 20.")
    try:
        with transactional_session(factory) as db_session:
            repository = db_session.scalar(select(Repository).where(Repository.id == repository_id))
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            _authorize_write(db_session, repository, actor_user_id)
            protection = db_session.scalar(select(BranchProtection).where(
                BranchProtection.repository_id == repository_id,
                BranchProtection.branch_name == branch_name,
            ).with_for_update())
            if protection is None:
                protection = BranchProtection(
                    repository_id=repository_id,
                    branch_name=branch_name,
                )
                db_session.add(protection)
            protection.require_pull_request = require_pull_request
            protection.required_approvals = required_approvals
            protection.require_ci_success = require_ci_success
            db_session.flush()
            db_session.refresh(protection)
            return protection
    except (RepositoryNotFoundError, RepositoryPermissionError, ValueError):
        raise
    except SQLAlchemyError as exc:
        raise RepositoryOperationError("Branch protection could not be saved.") from exc
