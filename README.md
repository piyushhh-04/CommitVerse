# CommitVerse

CommitVerse is a planned version control system and developer collaboration
platform. Its long-term goal is to combine a Git-like engine built in Python,
repository hosting and collaboration, and a future AI developer assistant.

## Vision

Build a modular, understandable developer platform with its own version control
internals. Keep repository objects separate from application metadata, favor
reliable engineering over unnecessary dependencies, and be explicit about what
is planned versus what is implemented.

## Planned components

- **CommitVerse Core** — a Git-like version control engine implemented in
  Python. Git internals are to be developed in this project rather than
  delegated to GitPython or another existing Git engine.
- **CommitVerse Hub** — repository hosting and developer collaboration.
- **CommitVerse AI** — a future AI developer assistant.

These are project goals, not descriptions of working features. No application
functionality has been implemented yet.

## Technology direction

- **Backend:** Python, FastAPI, PostgreSQL, SQLAlchemy, and Pydantic.
- **Version control engine:** Python standard library wherever practical.
- **Frontend:** React and Tailwind CSS.
- **Infrastructure and testing:** Docker and Pytest.
- **Future AI:** PyTorch and Hugging Face Transformers.

These technologies are planned; dependencies and services have not yet been
set up.

## Status

**Project initialization.** The repository currently contains foundational
project documentation only. There is no application code, version control
engine, API, frontend, database integration, or AI functionality.

See [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) for the project-wide engineering
and contribution guidelines, and [the architecture overview](./docs/architecture/overview.md)
for the intended system boundaries.
