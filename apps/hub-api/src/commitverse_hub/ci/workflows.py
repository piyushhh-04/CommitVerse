"""Validated JSON workflow definitions for the local CI foundation."""

from __future__ import annotations

from typing import Any


class WorkflowValidationError(ValueError):
    pass


def validate_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name")
    trigger = payload.get("trigger")
    jobs = payload.get("jobs")
    if not isinstance(name, str) or not name.strip():
        raise WorkflowValidationError("Workflow name is required.")
    if trigger not in {"push", "pull_request", "manual"}:
        raise WorkflowValidationError("Workflow trigger is invalid.")
    if not isinstance(jobs, dict) or not jobs:
        raise WorkflowValidationError("At least one workflow job is required.")
    for job_name, job in jobs.items():
        if not isinstance(job_name, str) or not isinstance(job, dict):
            raise WorkflowValidationError("Workflow jobs must be named objects.")
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            raise WorkflowValidationError(f"Job '{job_name}' requires at least one step.")
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                raise WorkflowValidationError(f"Job '{job_name}' steps require a run command.")
    return {
        "name": name.strip(),
        "trigger": trigger,
        "jobs": jobs,
    }
