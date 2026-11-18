"""Docker execution runtime for CommitVerse CI jobs."""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker


class ContainerRuntimeError(RuntimeError):
    pass


class ContainerTimeoutError(ContainerRuntimeError):
    pass


@dataclass(frozen=True)
class ContainerResult:
    exit_code: int
    logs: str


class DockerRuntime:
    def __init__(self) -> None:
        try:
            self.client = docker.from_env(timeout=5)
            self.client.ping()
        except Exception as exc:
            raise ContainerRuntimeError(
                "Docker is unavailable. Start Docker Desktop or the Docker daemon."
            ) from exc

    def close(self) -> None:
        self.client.close()

    def execute(
        self,
        *,
        workspace: Path,
        volume_name: str | None = None,
        workspace_mount_root: Path | None = None,
        command: str,
        environment: dict[str, str] | None = None,
        image: str = "python:3.12-slim",
        timeout_seconds: int = 300,
        memory_bytes: int = 512 * 1024 * 1024,
        cpu_quota: int = 50_000,
    ) -> ContainerResult:
        if timeout_seconds < 1 or timeout_seconds > 3600:
            raise ContainerRuntimeError("Execution timeout must be between 1 and 3600 seconds.")
        if memory_bytes < 16 * 1024 * 1024 or memory_bytes > 2 * 1024 * 1024 * 1024:
            raise ContainerRuntimeError("Memory limit is outside the supported range.")
        safe_environment = {
            key: value
            for key, value in (environment or {}).items()
            if key.isascii() and key.replace("_", "").isalnum()
        }
        container = None
        try:
            try:
                self.client.images.get(image)
            except docker.errors.ImageNotFound:
                self.client.images.pull(image)
            container = self.client.containers.create(
                image=image,
                command=["/bin/sh", "-lc", command],
                working_dir=(
                    "/workspace"
                    if volume_name is None
                    else "/workspace/"
                    + (
                        workspace.resolve().relative_to(workspace_mount_root.resolve()).as_posix()
                        if workspace_mount_root is not None
                        else ""
                    )
                ),
                volumes={
                    (
                        volume_name
                        if volume_name is not None
                        else str(workspace.resolve())
                    ): {"bind": "/workspace", "mode": "rw"}
                },
                environment=safe_environment,
                network_disabled=True,
                read_only=True,
                user="65532:65532",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit=memory_bytes,
                cpu_quota=cpu_quota,
                cpu_period=100_000,
                pids_limit=128,
            )
            container.start()
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                container.reload()
                if container.status != "running":
                    break
                time.sleep(0.1)
            else:
                container.kill()
                raise ContainerTimeoutError("Container execution timed out.")
            exit_code = int(container.attrs["State"]["ExitCode"])
            logs = container.logs(stdout=True, stderr=True, timestamps=False).decode(
                "utf-8",
                errors="replace",
            )
            return ContainerResult(exit_code=exit_code, logs=logs[-1_000_000:])
        except ContainerRuntimeError:
            raise
        except docker.errors.DockerException as exc:
            raise ContainerRuntimeError(f"Docker execution failed: {exc}") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.DockerException:
                    pass
