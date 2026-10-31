# CommitVerse Architecture Overview

## Status

This document describes the intended architecture, not a deployed or
implemented system. The repository is currently at project initialization;
there are no application components, APIs, schemas, or runtime integrations.

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

## Communication

Hub is expected to coordinate user-facing hosting and collaboration workflows
with Core's repository operations through defined interfaces. The concrete
protocol, API endpoints, and execution model have not been selected.

AI is a future component. Its integration points, data access, and communication
with Core or Hub are not yet defined. Do not assume it can read repositories or
perform actions.

## Storage separation

- **Version control data:** Core owns repository objects and other data needed
  for version control. The on-disk format and object model are not yet
  implemented or specified.
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
- Docker for planned infrastructure and Pytest for Python tests.
- PyTorch and Hugging Face Transformers for future AI work only.

These choices do not indicate that the corresponding dependencies, services, or
components have been created.
