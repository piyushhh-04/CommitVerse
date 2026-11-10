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
Core package foundation, Git-compatible loose objects and trees, index-v2
staging, bare and non-bare repository initialization/discovery, commit objects and
history, loose branch refs, safe branch switching/checkout, basic merging,
read-only status/diff, local advertisement, bounded fetch, fast-forward-only
push, safe local clone, and `cv` commands are implemented and tested. Hub now
provides a local-development API foundation, browser-session authentication,
and authenticated owner-only personal repository management through Core;
organizations, collaboration, repository browsing, frontend, and deployment
remain future work.

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

**Core repository, tree, staging, commit, checkout, and merge foundation.** The independently
installable Python package provides `cv init`, object writing/inspection,
`cv add [<path> ...]`, `cv add -A`, `cv write-tree`, `cv ls-files`,
`cv commit -m`, `cv branch [--list|<name>]`, `cv rev-parse <revision>`, and
`cv log`. It also provides `cv status`, `cv diff`, and `cv diff --cached`.
Core implements canonical blob/tree/commit envelopes and SHA-1 IDs, zlib
loose-object storage with integrity validation, Git-compatible trees and
index-v2 staging, commit parsing/creation, loose branch refs, symbolic and
detached `HEAD`, branch listing/creation, revision resolution, deterministic
parent-history traversal, and read-only comparison of `HEAD`, index, and
worktree state. Unit, integration, and isolated external Git compatibility
tests cover object, tree, index, commit, ref, history, checkout, merge, status,
and diff behavior.

This is a limited foundation, not a complete Git replacement. Core supports
bare repositories for object and reference operations; staging, status, diff,
checkout, switch, and worktree merge operations require a non-bare repository.
Merge conflict resolution, recursive/octopus merges, rebase, remote management,
network transport, and packfiles are not implemented. Local loose-object fetch,
fast-forward-only push to bare repositories, and temporary-directory clone are
implemented without claiming full Git compatibility. Checkout supports `HEAD`, local branch names, and full
40-character commit IDs; commit-ID checkout detaches `HEAD`. Checkout uses a
temporary, type-aware transaction backup to restore tracked files, directories,
symlinks, modes, the index, and refs after an injected or operational failure;
rollback errors are reported explicitly. Conflicting merges fail without
creating a merge commit. Merge commits resolve author and committer identities
using configured values and the documented environment overrides. Commit
creation requires configured identity and `-m`; an empty
initial commit or unchanged tree is rejected. Optional commit headers and
signatures, packed refs, index extensions other than `TREE`, advanced Git
ignore semantics, and non-v2 indexes are unsupported. Status/diff do not
detect renames; diff excludes untracked files, treats non-UTF-8 or NUL-bearing
content as binary, and buffers tracked file contents in memory. Full Git
ignore semantics, color/porcelain output, and complete Git status/diff
compatibility are not claimed. `cv init --bare <path>` initializes a bare
repository. Remote management and network transport remain planned. Hub
implementation details and limitations are tracked in its documentation. The
frontend, broader collaboration, deployment, and AI functionality remain future
work.

See [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) for the project-wide engineering
and contribution guidelines, and [the architecture overview](./docs/architecture/overview.md)
for the intended system boundaries.
