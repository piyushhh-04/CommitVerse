# CommitVerse Project Context

This document defines durable project direction and working conventions. It
does not imply that planned components or features have been implemented.

## Mission and components

CommitVerse is a planned custom version control system and developer
collaboration platform:

- **CommitVerse Core:** a Git-like engine written in Python, with Git internals
  implemented in this project.
- **CommitVerse Hub:** repository hosting and collaboration.
- **CommitVerse AI:** a future AI developer assistant.

The repository is at project initialization. Treat these components as plans
until working implementations and their tests exist.

## Architecture

- Keep the system modular, with clear boundaries between the version control
  engine, backend/API, frontend, and future AI capabilities.
- Keep Git repository objects and version-control data separate from Hub
  application metadata, such as users, permissions, and collaboration records.
- Define explicit interfaces between components. Do not make one component's
  internal storage format an accidental dependency of another.
- Keep deployment and infrastructure concerns distinct from product logic.
- Record significant architectural choices in `docs/decisions/`.

The architecture overview is in `docs/architecture/overview.md`.

## Technology decisions

Planned stack:

- Backend: Python, FastAPI, PostgreSQL, SQLAlchemy, and Pydantic.
- Core engine: Python standard library wherever practical; implement Git
  internals in CommitVerse.
- Frontend: React and Tailwind CSS.
- Infrastructure and tests: Docker and Pytest.
- Future AI: PyTorch and Hugging Face Transformers.

These are technology choices, not a declaration that dependencies, services, or
features are already configured. Do not introduce additional technologies
without a clear project need and an explicit decision.

## Engineering conventions

- Use modular architecture, clear names, and focused responsibilities.
- Follow Python best practices and add type hints to Python code.
- Prefer the standard library and existing project utilities; avoid
  unnecessary dependencies.
- Add meaningful tests for implemented behavior and run the relevant checks.
- Document behavior, limitations, and architectural decisions where useful.
- Never hardcode credentials, tokens, or other secrets. Use an appropriate
  configuration mechanism when one is introduced.
- Surface errors clearly; do not silently substitute success-shaped defaults.
- Preserve existing behavior when changing code and avoid unrelated changes.
- Keep claims in code, documentation, and user-facing output aligned with what
  has actually been implemented and verified.

## Dependency rules

- Do not add a dependency just to replace a small amount of practical standard
  library functionality.
- Do not use GitPython or another existing Git engine as a substitute for
  implementing CommitVerse Core's Git internals.
- Add dependencies only when justified by a concrete requirement; document
  significant choices and update the appropriate dependency manifest when
  manifests exist.
- Do not install or configure planned technologies before the project needs
  them.

## Copilot and contributor guidelines

- Inspect relevant files and current project conventions before editing.
- Make precise, complete changes within the requested scope; do not overwrite
  user work or create unrelated files.
- For a documentation or design task, do not invent implemented behavior,
  APIs, schemas, or deployment details.
- Distinguish current implementation from future plans in documentation.
- Prefer focused tests and validation appropriate to the change; report checks
  that were not run.
- Ask for clarification when a consequential design decision cannot be
  reasonably inferred.
- Do not initialize another Git repository or add tooling without an explicit
  project need.

## Design identity

For product UI, use warm white and charcoal foundations with muted peach and
sage accents, refined editorial typography, balanced spacing, subtle shadows,
precise borders, and responsive layouts. Use transitions intentionally. Avoid
generic AI SaaS styling, excessive gradients, neon, glow, unnecessary
animations, clutter, and oversized generic cards.
