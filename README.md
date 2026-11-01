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
  delegated to GitPython or another existing Git engine. Its planned package
  location is `packages/commitverse-core/`.
- **CommitVerse Hub** — repository hosting and developer collaboration.
- **CommitVerse AI** — a future AI developer assistant.

These are project goals, not descriptions of complete working products. The
Core package foundation and initial Git-compatible object operations are
implemented and tested. Core now also supports local non-bare repository
initialization and discovery, plus initial `cv` commands for writing and
inspecting loose objects.

## Technology direction

- **Backend:** Python, FastAPI, PostgreSQL, SQLAlchemy, and Pydantic.
- **Version control engine:** Python standard library wherever practical.
- **Frontend:** React and Tailwind CSS.
- **Infrastructure and testing:** Docker is mandatory infrastructure; Pytest is
  used for Core's Python tests.
- **Future AI:** PyTorch and Hugging Face Transformers.

These technologies are planned; aside from Pytest in Core's development
dependencies, application dependencies and services have not yet been set up.

## Development environment

Python development uses the repository-root `.venv`; project dependencies must
not be installed globally. Core has an independently installable package with
its own `pyproject.toml` under `packages/commitverse-core/`, with production and
development dependencies separated. Core is installed in editable mode in the
local development environment. The `dev` extra includes Pytest. Whether the
monorepo needs a root-level `pyproject.toml` for workspace-wide configuration
remains undecided; it would not replace Core's package-level configuration.
Docker complements local development and provides reproducible environments
and containerized application services; the standalone Core engine does not
initially need to run in Docker.

## Status

**Core repository and loose-object foundation.** The independently installable
Python package provides `cv init`, parent-walking repository discovery,
`cv hash-object -w`, and `cv cat-file -t`, `-s`, and `-p`. Core implements
canonical serialization for blob, tree, and commit object bytes; SHA-1 object
IDs; and zlib-compressed loose-object writes and reads with header, size, type,
and hash validation. Unit, integration, and external Git compatibility tests
cover these operations, including Git recognizing initialized repositories and
reading blobs written through the CLI.

This is a limited foundation, not a complete Git replacement. Index and
staging, tree and commit payload parsing, commits and refs as repository
operations, branching, merging, and transport are not implemented. Hub,
frontend, database integration, and AI functionality are also future work.

See [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) for the project-wide engineering
and contribution guidelines, and [the architecture overview](./docs/architecture/overview.md)
for the intended system boundaries.
