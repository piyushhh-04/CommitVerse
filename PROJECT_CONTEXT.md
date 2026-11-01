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

Core has an installable Python package with canonical object serialization,
SHA-1 hashing, and zlib-compressed loose-object storage for blob, tree, and
commit payloads. These object operations have unit tests and external Git
compatibility tests. This is not a complete version control engine: repository
initialization/discovery, index and staging, tree and commit payload parsing,
refs, CLI, branching, merging, and transport remain unimplemented. Treat Hub,
AI, and other unimplemented Core functionality as plans until working
implementations and their tests exist.

## Architecture

- Keep the system modular, with clear boundaries between the version control
  engine, backend/API, frontend, and future AI capabilities.
- Place the independently installable Core package under
  `packages/commitverse-core/`, with source in
  `packages/commitverse-core/src/commitverse_core/` and tests in
  `packages/commitverse-core/tests/{unit,integration,compatibility}/`.
- Keep Git repository objects and version-control data separate from Hub
  application metadata, such as users, permissions, and collaboration records.
- Define explicit interfaces between components. Do not make one component's
  internal storage format an accidental dependency of another.
- Keep deployment and infrastructure concerns distinct from product logic.
- Docker is mandatory infrastructure for reproducible environments and
  containerized application services. Keep Docker configuration modular and
  use Docker Compose when integrating FastAPI, PostgreSQL, and frontend
  services. Docker complements local Core development; the standalone Python
  engine does not need to run in Docker during initial development.
- Record significant architectural choices in `docs/decisions/`.

The architecture overview is in `docs/architecture/overview.md`.

## Technology decisions

Planned stack:

- Backend: Python, FastAPI, PostgreSQL, SQLAlchemy, and Pydantic.
- Core engine: Python standard library wherever practical; implement Git
  internals in CommitVerse.
- Frontend: React and Tailwind CSS.
- Infrastructure and tests: Docker and Pytest. Pytest is installed in Core's
  development extra; Core's unit and external Git compatibility suites cover
  the implemented object serialization and storage behavior.
- Future AI: PyTorch and Hugging Face Transformers.

These are technology choices, not a declaration that the planned application
dependencies, services, or features are configured. Pytest is the exception:
it is installed as Core's development dependency. Do not introduce additional
technologies without a clear project need and an explicit decision.

## Development environment and workflow

- The repository-root `.venv` exists and is used for Python development.
  Never install project dependencies globally.
- Core has a package-level `pyproject.toml` at
  `packages/commitverse-core/pyproject.toml` for Core configuration and
  dependency management, keeping production dependencies separate from
  development-only dependencies. Core is installed in editable mode in the
  local development environment, and its `dev` extra includes Pytest.
- The scope of any future root-level `pyproject.toml` is undecided. It may
  configure workspace-wide tooling if needed, but must not replace the Core
  package's independently installable configuration.
- Keep `.venv/` excluded from Git.
- Core source includes its package initializer and `objects/format.py` for
  canonical serialization and hashing, plus `objects/store.py` for loose
  object storage. Unit tests cover serialization, hashing, storage, and package
  imports. Compatibility tests use external Git in isolated temporary
  repositories to validate blob, tree, and commit object storage behavior.
- Repository initialization/discovery, index and staging, type-specific tree
  and commit payload parsing, refs, CLI, branching, merging, and remote
  transport are not implemented. `tests/integration/` currently has no
  implemented integration coverage.
- Local Core development and tests must work without Docker. Docker complements
  this workflow and is mandatory infrastructure for reproducible environments
  and containerized application services.
- Use modular Docker configuration. Use Docker Compose when integrating the
  Hub's FastAPI backend, PostgreSQL, and frontend services; do not make a
  containerized Core a prerequisite for its initial development.
- Document setup and execution commands as project workflows are established.

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
  manifests exist. Core's Python dependencies belong in its package-level
  `pyproject.toml`, separated into production and development requirements.
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
