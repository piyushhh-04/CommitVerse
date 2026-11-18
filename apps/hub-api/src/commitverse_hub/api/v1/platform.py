"""CI workflow and credential-free AI task API foundations."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from commitverse_hub.ai.providers import DeterministicLocalProvider
from commitverse_hub.api.v1.auth import get_authenticated_user, require_authenticated_csrf
from commitverse_hub.ci.workflows import WorkflowValidationError, validate_workflow
from commitverse_hub.db.models import (
    AIEngineeringTask,
    CIWorkflow,
    ExecutionJob,
    Repository,
    User,
)
from commitverse_hub.db.session import transactional_session
from commitverse_hub.errors.handlers import HubApplicationError
from commitverse_hub.repositories.service import (
    RepositoryNotFoundError,
    RepositoryOperationError,
    get_repository_for_access,
)


router = APIRouter(prefix="/repositories", tags=["ci-and-ai"])


class WorkflowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    trigger: str
    jobs: dict[str, Any]
    model_config = ConfigDict(extra="forbid")


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    trigger: str
    configuration: dict[str, Any]


class ExecutionCreateRequest(BaseModel):
    commit_id: str = Field(min_length=40, max_length=40)
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
    model_config = ConfigDict(extra="forbid")


class AITaskResponse(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    provider: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None


def _factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HubApplicationError(503, "database_unavailable", "The Hub database is not configured.")
    return factory


@router.post("/{repository_id}/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(repository_id: uuid.UUID, payload: WorkflowCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
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


@router.post("/{repository_id}/executions", response_model=ExecutionResponse, status_code=status.HTTP_202_ACCEPTED)
def create_execution(repository_id: uuid.UUID, payload: ExecutionCreateRequest, request: Request, user: User = Depends(get_authenticated_user)):
    require_authenticated_csrf(request)
    factory = _factory(request)
    try:
        get_repository_for_access(factory, repository_id, user.id)
        with transactional_session(factory) as db:
            job = ExecutionJob(
                repository_id=repository_id,
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
        provider = DeterministicLocalProvider()
        output = provider.analyze({}, {"query": payload.query})
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
