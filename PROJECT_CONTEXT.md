# CommitVerse Project Context

This document defines durable project direction and working conventions. It
does not imply that planned components or features have been implemented.

## Mission and components

CommitVerse is a planned custom version control system and developer
collaboration platform:

- **CommitVerse Core:** a Git-like engine written in Python, with Git internals
  implemented in this project.
- **CommitVerse Hub:** architecture-planned repository hosting and
  collaboration, not yet implemented. Its accepted initial architecture is a
  Python/FastAPI modular monolith with a React/Tailwind frontend, PostgreSQL
  metadata, SQLAlchemy, Alembic, REST under `/api/v1`, opaque server-side
  browser sessions, a filesystem repository store during development, and a
  dedicated Core adapter.
- **CommitVerse AI:** a future AI developer assistant.

Core has an installable Python package with canonical object serialization,
SHA-1 hashing, zlib-compressed loose-object storage, bare and non-bare repository
initialization/discovery, Git-compatible tree serialization/parsing, a
version-2 Git index, staging, commit object parsing/creation, loose branch
references, symbolic and detached `HEAD`, branch listing/creation, revision
resolution, initial commit history traversal, safe checkout/switching, merged-only branch
deletion, merge-base discovery, basic three-way merging, and read-only
status/diff comparison. The `cv` CLI exposes these tested operations. Unit, integration,
and isolated external Git compatibility tests cover the implemented scope.
This is not a complete version control engine: conflict resolution,
recursive/octopus merge, remote management, network Git transport, packfiles,
rename detection, and full Git compatibility remain unimplemented. Local
filesystem advertisement, bounded loose-object fetch, fast-forward-only push
to bare repositories, and safe local clone are implemented as library
operations, not `cv` CLI commands. Git-over-HTTP, Git-over-SSH, and ordinary
network-based Git client interoperability are not implemented. Treat Hub, AI,
and other unimplemented functionality as plans until working implementations
and their tests exist.

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
- Hub's accepted initial architecture is a modular monolith, not microservices;
  its proposed architecture, data model, security boundaries, and roadmap are
  documented under `docs/hub/`.
- CommitVerse follows the permanent strict zero-cost policy in
  `docs/infrastructure/zero-cost-policy.md`: it must not require or incur
  payment. Approved planned services are Cloudflare Pages Free, Cloudflare
  Workers Free for lightweight endpoints only, and Neon PostgreSQL Free.
  Core repository data remains on the local filesystem during development.
  AWS, Render, Fly.io, Railway, Supabase, and paid or quota-overrun usage are
  excluded. Free-quota exhaustion must pause, degrade, or migrate a feature
  without incurring charges.
- Hub development remains local: there is no verified, approved zero-cost host
  for the complete Python FastAPI application plus filesystem-backed Core
  repository storage. Cloudflare Pages Free, suitable lightweight Workers Free
  endpoints, and Neon PostgreSQL Free are planned only; they are not provisioned.
  Workers must not run the Python Git engine. Deployment requires separate
  verification of a compliant Python runtime and repository-storage solution.
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
  development extra; Core's unit, integration, and external Git compatibility
  suites cover the implemented object, tree, index, commit, ref, status, diff,
  and CLI behavior.
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
- Core source includes `repository.py` for repository initialization and
  discovery, `trees.py` for Git tree payloads, `index.py` for index-v2
  persistence, `staging.py` for worktree staging, `commits.py` for commit
  payloads, `refs.py` for loose refs and `HEAD`, `commit_service.py` for commit
  creation, `history.py` for parent traversal, `status.py` for read-only
  snapshot comparison, `diff.py` for unified text diffs, and `cli.py` for the
  `cv` entry point. `objects/format.py` and `objects/store.py` provide
  canonical object bytes, hashing, and verified loose-object storage. Repository
  capability modeling supports bare repositories for object and reference
  operations; worktree operations require a non-bare repository. Local
  filesystem transport, bounded fetch, push, and clone library operations are
  implemented; network Git transport is not.
  Compatibility tests invoke Git only in isolated temporary repositories.
  `checkout.py`, `merge_base.py`, and `merge.py` provide type-aware rollback
  for checkout transitions, iterative ancestry, and basic merges; network
  transport is not implemented. Checkout rollback covers tracked filesystem
  entries, the index, and refs, while reporting rollback failures rather than
  suppressing them.
- Local Core development and tests must work without Docker. Docker complements
  this workflow and is mandatory infrastructure for reproducible environments
  and containerized application services.
- Use modular Docker configuration. Use Docker Compose when integrating the
  Hub's FastAPI backend, PostgreSQL, and frontend services; do not make a
  containerized Core a prerequisite for its initial development.
- Document setup and execution commands as project workflows are established.
- Hosting, deployment, database provisioning, and cloud storage remain
  deliberately deferred until their appropriate development stage. Planned
  infrastructure is not implemented infrastructure.

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
