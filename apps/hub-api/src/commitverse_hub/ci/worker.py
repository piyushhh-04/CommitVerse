"""Single-process local worker for pending CommitVerse execution jobs."""

from __future__ import annotations

import shutil
import tempfile
import time
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from commitverse_core.clone import clone_from_local
from commitverse_core.repository import discover_repository
from commitverse_core.refs import list_branches

from commitverse_hub.db.models import (
    CIWorkflow,
    ExecutionJob,
    ExecutionLog,
    Repository,
)
from commitverse_hub.db.session import transactional_session

from .runtime import ContainerTimeoutError, DockerRuntime


def _claim_job(factory: sessionmaker[Session]) -> ExecutionJob | None:
    try:
        with transactional_session(factory) as db:
            job = db.scalar(
                select(ExecutionJob)
                .where(ExecutionJob.status == "pending")
                .order_by(ExecutionJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            job.status = "starting"
            db.flush()
            db.refresh(job)
            return job
    except Exception:
        return None


def _append_log(
    factory: sessionmaker[Session],
    job_id,
    sequence: int,
    stream: str,
    content: str,
) -> None:
    with transactional_session(factory) as db:
        db.add(
            ExecutionLog(
                job_id=job_id,
                sequence=sequence,
                stream=stream,
                content=content[-1_000_000:],
            )
        )


def run_pending_jobs(
    factory: sessionmaker[Session],
    repository_storage_root: Path,
    *,
    once: bool = False,
) -> None:
    runtime = DockerRuntime()
    try:
        while True:
            job = _claim_job(factory)
            if job is None:
                if once:
                    return
                time.sleep(1)
                continue

            temporary_root: Path | None = None
            try:
                ci_workspace_root = Path(
                    os.environ.get("CI_WORKSPACE_ROOT", str(repository_storage_root))
                )
                ci_workspace_root.mkdir(mode=0o777, parents=True, exist_ok=True)
                ci_workspace_root.chmod(0o777)
                with factory() as db:
                    repository = db.get(Repository, job.repository_id)
                    if repository is None:
                        raise RuntimeError("Repository metadata not found.")
                    storage_path = repository_storage_root / f"{repository.storage_key}.git"
                temporary_root = Path(
                    tempfile.mkdtemp(
                        prefix=".ci-",
                        dir=os.environ.get("CI_WORKSPACE_ROOT", repository_storage_root),
                    )
                )
                temporary_root.chmod(0o777)
                workspace = temporary_root / "workspace"
                source_repository = discover_repository(storage_path)
                matching_branch = next(
                    (
                        branch.name
                        for branch in list_branches(source_repository)
                        if branch.object_id == job.commit_id
                    ),
                    None,
                )
                clone_from_local(
                    storage_path,
                    workspace,
                    branch=matching_branch,
                )
                cloned = discover_repository(workspace)
                if cloned.bare:
                    raise RuntimeError("CI clone unexpectedly produced a bare repository.")
                for current_root, directory_names, file_names in os.walk(workspace):
                    if os.path.islink(current_root):
                        continue
                    os.chmod(current_root, 0o777)
                    for name in directory_names:
                        path = Path(current_root) / name
                        if not path.is_symlink():
                            os.chmod(path, 0o777)
                    for name in file_names:
                        path = Path(current_root) / name
                        if not path.is_symlink():
                            os.chmod(path, 0o666)

                workspace.chmod(0o777)
                with transactional_session(factory) as db:
                    current = db.get(ExecutionJob, job.id)
                    if current is not None:
                        current.status = "running"

                if job.workflow_id is None:
                    raise RuntimeError("No workflow is configured for this execution.")
                with factory() as db:
                    workflow = db.get(CIWorkflow, job.workflow_id)
                    if workflow is None:
                        raise RuntimeError("Workflow metadata not found.")
                    workflow_configuration = workflow.configuration

                sequence = 0
                overall_exit = 0
                for job_name, job_config in workflow_configuration["jobs"].items():
                    if overall_exit != 0:
                        break
                    if not isinstance(job_config, dict):
                        raise RuntimeError(f"Invalid workflow job: {job_name}")
                    image = str(job_config.get("image", "python:3.12-slim"))
                    timeout_seconds = int(job_config.get("timeout", 300))
                    memory_bytes = int(job_config.get("memory_bytes", 512 * 1024 * 1024))
                    environment = job_config.get("environment")
                    if not isinstance(environment, dict):
                        environment = {}
                    for step_index, step in enumerate(job_config["steps"]):
                        command = str(step["run"])
                        with factory() as db:
                            current_status = db.get(ExecutionJob, job.id)
                            if current_status is not None and current_status.status == "cancelled":
                                break
                        result = runtime.execute(
                            workspace=workspace,
                            volume_name=os.environ.get("CI_WORKSPACE_VOLUME"),
                            workspace_mount_root=ci_workspace_root,
                            command=command,
                            environment={str(k): str(v) for k, v in environment.items()},
                            image=image,
                            timeout_seconds=timeout_seconds,
                            memory_bytes=memory_bytes,
                        )
                        _append_log(
                            factory,
                            job.id,
                            sequence,
                            "stdout",
                            f"$ {command}\n{result.logs}",
                        )
                        sequence += 1
                        if result.exit_code != 0:
                            overall_exit = result.exit_code
                            break

                with transactional_session(factory) as db:
                    current = db.get(ExecutionJob, job.id)
                    if current is not None:
                        if current.status == "cancelled":
                            pass
                        else:
                            current.status = "succeeded" if overall_exit == 0 else "failed"
                            current.finished_at = datetime.now(UTC)
                        if overall_exit != 0 and current.status != "cancelled":
                            current.error_message = f"Command exited with status {overall_exit}"
            except ContainerTimeoutError as exc:
                _append_log(factory, job.id, 0, "stderr", str(exc))
                with transactional_session(factory) as db:
                    current = db.get(ExecutionJob, job.id)
                    if current is not None:
                        current.status = "timed_out"
                        current.finished_at = datetime.now(UTC)
                        current.error_message = str(exc)[-2000:]
            except Exception as exc:
                _append_log(factory, job.id, 0, "stderr", str(exc))
                with transactional_session(factory) as db:
                    current = db.get(ExecutionJob, job.id)
                    if current is not None:
                        current.status = "failed"
                        current.finished_at = datetime.now(UTC)
                        current.error_message = str(exc)[-2000:]
            finally:
                if temporary_root is not None:
                    shutil.rmtree(temporary_root, ignore_errors=True)
            if once:
                return
    finally:
        runtime.close()


def run_worker() -> None:
    from commitverse_hub.config import Settings
    from commitverse_hub.db.engine import build_engine
    from commitverse_hub.db.session import create_session_factory

    settings = Settings.from_environment()
    if settings.database_url is None:
        raise RuntimeError("Set HUB_DATABASE_URL before starting the CI worker.")
    engine = build_engine(settings.database_url)
    try:
        run_pending_jobs(
            create_session_factory(engine),
            settings.repository_storage_root,
        )
    finally:
        engine.dispose()
