# CommitVerse Architecture Overview

## Status

This document describes the intended architecture, not a deployed or
implemented system. Core has an initial Python package scaffold, but there are
no implemented engine features, APIs, schemas, or runtime integrations.

## System shape

CommitVerse is planned as a modular monorepo with three product components:

1. **CommitVerse Core** owns the custom Git-like version control engine and
   repository operations.
2. **CommitVerse Hub** provides repository hosting and collaboration. Its
   backend is planned with Python, FastAPI, PostgreSQL, SQLAlchemy, and Pydantic;
   its frontend is planned with React and Tailwind CSS.
3. **CommitVerse AI** is a future developer assistant. PyTorch and Hugging Face
   Transformers are planned for this area, but no AI functionality exists yet.

The components should have explicit interfaces and independently understandable
responsibilities. The exact process boundaries and deployment topology remain
open until implementation requirements are known.

Core is planned as an independently installable Python package under
`packages/commitverse-core/`, with source in
`packages/commitverse-core/src/commitverse_core/` and tests in
`packages/commitverse-core/tests/{unit,integration,compatibility}/`. This
package boundary follows the modular monorepo decision. The package currently
contains only `src/commitverse_core/__init__.py`; `tests/unit/` contains two
initial package tests, and `tests/integration/` and `tests/compatibility/` are
empty. Both initial package tests have passed. No Core engine functionality
has been implemented.

## Communication

Hub is expected to coordinate user-facing hosting and collaboration workflows
with Core's repository operations through defined interfaces. The concrete
protocol, API endpoints, and execution model have not been selected.

AI is a future component. Its integration points, data access, and communication
with Core or Hub are not yet defined. Do not assume it can read repositories or
perform actions.

## Storage separation

- **Version control data:** Core owns repository objects and other data needed
  for version control. The object format and model are documented as proposed
  designs, but have not yet been implemented.
- **Application metadata:** Hub will own platform metadata such as accounts,
  access control, and collaboration records. PostgreSQL is planned for this
  metadata.
- **Separation boundary:** Do not store Git objects as Hub database metadata or
  treat database records as a replacement for the repository object store.
  Define explicit references and interfaces between them when implementation
  begins.
- **AI data:** No AI data store or retention policy has been chosen.

## Planned technology boundaries

- Python standard library wherever practical for Core; implement Git internals
  within CommitVerse rather than wrapping an existing Git engine.
- FastAPI, SQLAlchemy, Pydantic, and PostgreSQL for the planned Hub backend.
- React and Tailwind CSS for the planned frontend.
- Docker is mandatory infrastructure for reproducible environments and
  containerized application services. Pytest is installed as a Core development
  dependency.
- PyTorch and Hugging Face Transformers for future AI work only.

These choices do not indicate that the corresponding dependencies, services,
or components have been created, except for Pytest in Core's development
environment.

## Development environment and deployment

Python development uses the existing root-level `.venv`, which is excluded
from Git. Core's project configuration and dependency management are in
`packages/commitverse-core/pyproject.toml`, with production dependencies
separate from development dependencies. Core is installed in editable mode in
the local development environment. Project packages must not be installed
globally. Whether to add a root-level `pyproject.toml` for workspace-wide
configuration remains undecided; it does not replace Core's package-level
configuration.

Core must be usable and testable locally through `.venv`; Docker complements
that workflow and is not a requirement for running the standalone Core engine
during initial development. Docker remains mandatory infrastructure for
reproducible environments and containerized application services. When Hub's
FastAPI backend, PostgreSQL, and frontend are integrated, use Docker Compose.
Keep Docker configuration modular and avoid coupling container definitions to
Core's storage or product logic.

No Docker or Compose configuration or service integration is present yet. The
Python environment and Core dependency manifest are in place. Setup and
execution commands should be documented alongside the implementation they
support; see the Core workflow in [the Core roadmap](../core/implementation-roadmap.md).
