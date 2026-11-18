"""CI workflow and credential-free AI task API foundations."""

from __future__ import annotations

import uuid
from typing import Any, Literal
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.ai.providers import DeterministicLocalProvider, OllamaProvider
from commitverse_hub.ai.indexing import extract_python_symbols, index_bare_repository
from commitverse_hub.ai.retrieval import lexical_rank
from commitverse_hub.api.v1.auth import get_authenticated_user, require_authenticated_csrf
from commitverse_hub.ci.workflows import (
    WorkflowValidationError,
    parse_workflow_yaml,
    validate_workflow,
)
from commitverse_hub.db.models import (
    AIEngineeringTask,
    CIWorkflow,
    ExecutionJob,
    ExecutionLog,
    ExecutionArtifact,
    Repository,
    OrganizationMembership,
    RepositoryUserPermission,
    User,
)
from commitverse_hub.db.session import transactional_session
from commitverse_core.repository import discover_repository
from commitverse_core.commits import read_commit
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.repositories.service import (
    RepositoryNotFoundError,
    RepositoryOperationError,
    get_repository_for_access,
)


router = APIRouter(prefix="/repositories", tags=["ci-and-ai"])


class WorkflowCreateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    trigger: str | None = None
    jobs: dict[str, Any] | None = None
    yaml: str | None = Field(default=None, max_length=1_000_000)
    model_config = ConfigDict(extra="forbid")


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    trigger: str
    configuration: dict[str, Any]


class ExecutionCreateRequest(BaseModel):
    commit_id: str = Field(min_length=40, max_length=40)
    workflow_id: uuid.UUID | None = None
    model_config = ConfigDict(extra="forbid")


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID | None
    trigger_type: str
    commit_id: str
    status: str


class AITaskCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    query: str = Field(min_length=1, max_length=10000)
    provider: Literal["deterministic", "ollama"] = "deterministic"
    model_config = ConfigDict(extra="forbid")


class AITaskResponse(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    provider: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None


class PushEventRequest(BaseModel):
    ref_name: str = Field(min_length=1, max_length=255)
    commit_id: str = Field(min_length=40, max_length=40)
    model_config = ConfigDict(extra="forbid")


class ExecutionLogResponse(BaseModel):
    sequence: int
    stream: str
    content: str
    created_at: datetime


class ExecutionArtifactResponse(BaseModel):
    id: uuid.UUID
    name: str
    storage_path: str
    size_bytes: int
    created_at: datetime


class ExecutionDetailResponse(ExecutionResponse):
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    logs: list[ExecutionLogResponse]
    artifacts: list[ExecutionArtifactResponse]


class PushEventResponse(BaseModel):
    scheduled: list[ExecutionResponse]


class IndexStatusResponse(BaseModel):
    repository_id: uuid.UUID
    indexed_files: int
    python_files: int
    total_text_bytes: int


def _factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(503, "database_unavailable", "The Hub database is not configured.")
    return factory


def _require_write(factory: sessionmaker[Session], repository_id: uuid.UUID, user_id: uuid.UUID) -> Repository:
    repository = get_repository_for_access(factory, repository_id, user_id)
    with factory() as db:
        if repository.owner_user_id == user_id:
            return repository
        if repository.owner_organization_id is not None:
            membership = db.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == repository.owner_organization_id,
                    OrganizationMembership.user_id == user_id,
                )
            )
            if membership is not None and membership.role in {"owner", "admin"}:
                return repository
        permission = db.get(RepositoryUserPermission, (repository_id, user_id))
        if permission is not None and permission.role in {"writer", "admin"}:
            return repository
    raise HubApplicationError(
        403,
        "repository_permission_denied",
        "Repository write access is required.",
    )


@router.get("/{repository_id}/index/status", response_model=IndexStatusResponse)
def get_repository_index_status(
    repository_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_authenticated_user),
) -> IndexStatusResponse:
    factory = _factory(request)
    try:
        repository = get_repository_for_access(factory, repository_id, user.id)
        storage_path = (
            request.app.state.settings.repository_storage_root
            / f"{repository.storage_key}.git"
        )
        core_repository = discover_repository(storage_path)
        files = index_bare_repository(core_repository)
        return IndexStatusResponse(
            repository_id=repository_id,
            indexed_files=len(files),
            python_files=sum(1 for path in files if path.endswith(".py")),
            total_text_bytes=sum(len(content.encode("utf-8")) for content in files.values()),
        )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(
            404 if isinstance(exc, RepositoryNotFoundError) else 503,
            "platform_unavailable",
            str(exc),
        ) from exc
    except Exception as exc:
        raise HubApplicationError(
            503,
            "repository_index_unavailable",
            f"Repository index could not be read: {exc}",
        ) from exc


@router.post("/{repository_id}/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(repository_id: uuid.UUID, payload: WorkflowCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        if payload.yaml is not None:
            configuration = parse_workflow_yaml(payload.yaml)
        else:
            if payload.name is None or payload.trigger is None or payload.jobs is None:
                raise WorkflowValidationError("Provide workflow YAML or name, trigger, and jobs.")
            configuration = validate_workflow({
                "name": payload.name,
                "trigger": payload.trigger,
                "jobs": payload.jobs,
            })
        with transactional_session(factory) as db:
            workflow = CIWorkflow(
                repository_id=repository_id,
                name=configuration["name"],
                trigger=configuration["trigger"],
                configuration=configuration,
            )
            db.add(workflow)
            db.flush()
            db.refresh(workflow)
            return WorkflowResponse(
                id=workflow.id,
                name=workflow.name,
                trigger=workflow.trigger,
                configuration=workflow.configuration,
            )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HubApplicationError(422, "workflow_validation_error", str(exc)) from exc


@router.get("/{repository_id}/workflows", response_model=list[WorkflowResponse])
def list_workflows(repository_id: uuid.UUID, request: Request, user: User = Depends(get_authenticated_user)):
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        with factory() as db:
            items = db.scalars(select(CIWorkflow).where(CIWorkflow.repository_id == repository_id).order_by(CIWorkflow.name))
            return [
                WorkflowResponse(id=item.id, name=item.name, trigger=item.trigger, configuration=item.configuration)
                for item in items
            ]
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc


@router.get("/{repository_id}/executions", response_model=list[ExecutionResponse])
def list_executions(repository_id: uuid.UUID, request: Request, user: User = Depends(get_authenticated_user)):
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        with factory() as db:
            items = db.scalars(
                select(ExecutionJob)
                .where(ExecutionJob.repository_id == repository_id)
                .order_by(ExecutionJob.created_at.desc())
            )
            return [
                ExecutionResponse(
                    id=item.id,
                    workflow_id=item.workflow_id,
                    trigger_type=item.trigger_type,
                    commit_id=item.commit_id,
                    status=item.status,
                )
                for item in items
            ]
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc


@router.get("/{repository_id}/executions/{execution_id}", response_model=ExecutionDetailResponse)
def get_execution(repository_id: uuid.UUID, execution_id: uuid.UUID, request: Request, user: User = Depends(get_authenticated_user)):
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        with factory() as db:
            job = db.scalar(
                select(ExecutionJob).where(
                    ExecutionJob.id == execution_id,
                    ExecutionJob.repository_id == repository_id,
                )
            )
            if job is None:
                raise HubApplicationError(404, "execution_not_found", "Execution not found.")
            logs = db.scalars(
                select(ExecutionLog)
                .where(ExecutionLog.job_id == execution_id)
                .order_by(ExecutionLog.sequence)
            )
            artifacts = db.scalars(
                select(ExecutionArtifact)
                .where(ExecutionArtifact.job_id == execution_id)
                .order_by(ExecutionArtifact.created_at)
            )
            return ExecutionDetailResponse(
                id=job.id,
                workflow_id=job.workflow_id,
                trigger_type=job.trigger_type,
                commit_id=job.commit_id,
                status=job.status,
                started_at=job.started_at,
                finished_at=job.finished_at,
                error_message=job.error_message,
                logs=[
                    ExecutionLogResponse(
                        sequence=log.sequence,
                        stream=log.stream,
                        content=log.content,
                        created_at=log.created_at,
                    )
                    for log in logs
                ],
                artifacts=[
                    ExecutionArtifactResponse(
                        id=artifact.id,
                        name=artifact.name,
                        storage_path=artifact.storage_path,
                        size_bytes=artifact.size_bytes,
                        created_at=artifact.created_at,
                    )
                    for artifact in artifacts
                ],
            )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc


@router.post("/{repository_id}/push-events", response_model=PushEventResponse, status_code=status.HTTP_202_ACCEPTED)
def create_push_event(repository_id: uuid.UUID, payload: PushEventRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        repository = _require_write(factory, repository_id, user.id)
        storage_path = request.app.state.settings.repository_storage_root / f"{repository.storage_key}.git"
        core_repository = discover_repository(storage_path)
        read_commit(core_repository.objects_dir, payload.commit_id)
        if not payload.ref_name.startswith("refs/heads/"):
            raise HubApplicationError(422, "workflow_validation_error", "Push ref must be a local branch ref.")

        with transactional_session(factory) as db:
            workflows = db.scalars(
                select(CIWorkflow).where(
                    CIWorkflow.repository_id == repository_id,
                    CIWorkflow.trigger == "push",
                )
            )
            scheduled: list[ExecutionJob] = []
            for workflow in workflows:
                job = ExecutionJob(
                    repository_id=repository_id,
                    workflow_id=workflow.id,
                    trigger_type="push",
                    commit_id=payload.commit_id,
                    status="pending",
                )
                db.add(job)
                db.flush()
                db.refresh(job)
                scheduled.append(job)
            return PushEventResponse(
                scheduled=[
                    ExecutionResponse(
                        id=job.id,
                        workflow_id=job.workflow_id,
                        trigger_type=job.trigger_type,
                        commit_id=job.commit_id,
                        status=job.status,
                    )
                    for job in scheduled
                ]
            )
    except HubApplicationError:
        raise
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HubApplicationError(422, "workflow_validation_error", f"Invalid pushed commit: {exc}") from exc


@router.post("/{repository_id}/executions/{execution_id}/cancel", response_model=ExecutionResponse)
def cancel_execution(repository_id: uuid.UUID, execution_id: uuid.UUID, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        repository = _require_write(factory, repository_id, user.id)
        with transactional_session(factory) as db:
            job = db.scalar(
                select(ExecutionJob).where(
                    ExecutionJob.id == execution_id,
                    ExecutionJob.repository_id == repository.id,
                ).with_for_update()
            )
            if job is None:
                raise HubApplicationError(404, "execution_not_found", "Execution not found.")
            if job.status not in {"pending", "scheduled", "starting", "running"}:
                raise HubApplicationError(409, "execution_conflict", "Execution can no longer be cancelled.")
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)
            db.flush()
            db.refresh(job)
            return ExecutionResponse(
                id=job.id,
                workflow_id=job.workflow_id,
                trigger_type=job.trigger_type,
                commit_id=job.commit_id,
                status=job.status,
            )
    except HubApplicationError:
        raise
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc


@router.post("/{repository_id}/executions", response_model=ExecutionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_execution(repository_id: uuid.UUID, payload: ExecutionCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        with transactional_session(factory) as db:
            if payload.workflow_id is not None:
                workflow = db.get(CIWorkflow, payload.workflow_id)
                if workflow is None or workflow.repository_id != repository_id:
                    raise HubApplicationError(
                        404,
                        "workflow_not_found",
                        "Workflow not found.",
                    )
            job = ExecutionJob(
                repository_id=repository_id,
                workflow_id=payload.workflow_id,
                trigger_type="manual",
                commit_id=payload.commit_id,
                status="pending",
            )
            db.add(job)
            db.flush()
            db.refresh(job)
            return ExecutionResponse(
                id=job.id,
                workflow_id=job.workflow_id,
                trigger_type=job.trigger_type,
                commit_id=job.commit_id,
                status=job.status,
            )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc


@router.post("/{repository_id}/ai/tasks", response_model=AITaskResponse, status_code=status.HTTP_201_CREATED)
def create_ai_task(repository_id: uuid.UUID, payload: AITaskCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        provider: DeterministicLocalProvider | OllamaProvider
        if payload.provider == "ollama":
            provider = OllamaProvider()
        else:
            provider = DeterministicLocalProvider()
        with factory() as db:
            repository = db.get(Repository, repository_id)
            if repository is None:
                raise RepositoryNotFoundError("Repository not found.")
            storage_path = request.app.state.settings.repository_storage_root / f"{repository.storage_key}.git"
        try:
            core_repository = discover_repository(storage_path)
            repository_files = index_bare_repository(core_repository)
        except Exception:
            repository_files = {}
        references = lexical_rank(repository_files, payload.query)
        try:
            output = provider.analyze(repository_files, {"query": payload.query})
        except (RuntimeError, ValueError) as exc:
            raise HubApplicationError(
                503,
                "ai_provider_unavailable",
                str(exc),
            ) from exc
        if payload.provider == "deterministic":
            output["references"] = references
        with transactional_session(factory) as db:
            task = AIEngineeringTask(
                repository_id=repository_id,
                requested_by=user.id,
                kind=payload.kind,
                status="succeeded",
                provider=provider.name,
                input_data={"query": payload.query},
                output_data=output,
            )
            db.add(task)
            db.flush()
            db.refresh(task)
            return AITaskResponse(
                id=task.id,
                kind=task.kind,
                status=task.status,
                provider=task.provider,
                input_data=task.input_data,
                output_data=task.output_data,
            )
    except (RepositoryNotFoundError, RepositoryOperationError) as exc:
        raise HubApplicationError(404 if isinstance(exc, RepositoryNotFoundError) else 503, "platform_unavailable", str(exc)) from exc
