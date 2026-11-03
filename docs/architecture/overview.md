# CommitVerse Architecture Overview

## Status

This document describes the current implemented architecture of CommitVerse
Core and the intended future shape of the broader platform. It is a current
engineering reference, not a promise of a complete Git replacement or completed
Hub/AI product work.

## System shape

CommitVerse is organized as a modular monorepo with three product areas:

1. **CommitVerse Core** implements the Git-like version control engine and
   repository operations in Python.
2. **CommitVerse Hub** is the planned repository hosting and collaboration
   platform.
3. **CommitVerse AI** is the planned AI-powered developer assistant layer.

The implemented work is in Core. Hub and AI are future-facing architecture
plans and do not yet contain working runtime integrations.

Core is an independently installable Python package under
`packages/commitverse-core/`, with source in
`packages/commitverse-core/src/commitverse_core/` and tests in
`packages/commitverse-core/tests/{unit,integration,compatibility}/`.

## Current Core architecture

The current implementation is responsible for repository metadata, object
storage, index management, tree serialization, staging, commits, refs, history,
status diffing, safe checkout/switching, merge-base discovery, basic merging,
and the `cv` CLI surface.

### Repository and object model

- `repository.py` initializes and discovers non-bare repositories.
- `objects/format.py` defines canonical Git-compatible object serialization and
  SHA-1 hashing.
- `objects/store.py` reads and writes verified loose objects in the `.git/objects`
  directory using zlib-compressed canonical payloads.

These modules define the underlying object database and repository root layout.

### Index, tree, and staging

- `index.py` provides Git index-v2 parsing and serialization, checksum
  validation, path validation, stage handling, duplicate detection, and atomic
  replacement.
- `trees.py` serializes and parses Git tree objects and rebuilds nested tree
  structures from stage-zero index entries.
- `staging.py` stages files and directories from the working tree into the index,
  including basic `.gitignore` handling, symlink support, and safe repository
  scans.

This layer converts the working tree into a Git-like staged snapshot stored in
`.git/index`.

### Commits, refs, and history

- `commits.py` defines commit payload structure, serialization, validation, and
  parse logic.
- `refs.py` manages loose branch refs, `HEAD`, and branch validation.
- `commit_service.py` creates commits from the current index and advances HEAD.
- `history.py` traverses reachable parent history and formats commit metadata.
- `checkout.py` preflights and applies safe worktree/index/HEAD transitions.
- `merge_base.py` finds deterministic common ancestors and detects graph cycles.
- `merge.py` performs fast-forward and basic three-way merges.

This layer turns staged tree snapshots into commit objects and valid branch
state.

### Status and diff

- `status.py` compares HEAD, index, and working tree snapshots and reports
  staged, unstaged, and untracked state.
- `diff.py` generates deterministic unified diffs for staged or working-tree
  changes without mutating repository data.

This is a read-only comparison layer, not a complete Git status/diff clone.

### CLI

- `cli.py` is the `cv` command entrypoint.

Supported commands in the current implementation:

- `cv init [path]`
- `cv hash-object -w <file>`
- `cv cat-file -t <object_id>`
- `cv cat-file -s <object_id>`
- `cv cat-file -p <object_id>`
- `cv add [-A] [paths ...]`
- `cv write-tree`
- `cv ls-files`
- `cv commit -m "message"`
- `cv branch [--list] [name]`
- `cv rev-parse <revision>`
- `cv log`
- `cv status`
- `cv diff [--cached]`
- `cv switch <branch>`
- `cv checkout <HEAD|branch|full-commit-id>`
- `cv branch -d <merged-branch>`
- `cv merge <branch>`

## Communication boundaries

Hub is expected to coordinate hosting and collaboration workflows with Core
through defined repository interfaces, but no Hub API or integration is present
in this repository.

AI is a future product capability. It has no implemented data access model,
repository API, or runtime integration in the current codebase.

## Storage separation

- **Version control data:** Core owns repository objects, refs, index, and tree
  data.
- **Application metadata:** Hub owns repository hosting metadata such as users,
  permissions, and collaboration records.
- **Separation boundary:** Do not treat database metadata as a substitute for
  the repository object store.
- **AI data:** No AI persistence or retention model is implemented.

## Planned technology boundaries

- **Core:** Python standard library wherever practical.
- **Hub:** Python, FastAPI, PostgreSQL, SQLAlchemy, and Pydantic are planned.
- **Frontend:** React and Tailwind CSS are planned.
- **Infrastructure:** Docker is mandatory infrastructure for reproducible
  environments and later service composition, but the standalone Core engine
  remains usable without Docker.
- **AI:** PyTorch and Hugging Face Transformers are planned for future work only.

These technology choices are not a claim that the referenced services are
configured or running.

## Development environment and deployment

Python development uses the repository-root `.venv`, which is excluded from Git.
Core configuration lives in `packages/commitverse-core/pyproject.toml` and the
package is installed in editable mode for local development. Project packages must
not be installed globally.

Local Core development and tests work without Docker. Docker is infrastructure,
not a prerequisite for the Engine in its current form.

## Current architectural limitations

The current Core implementation is intentionally limited and does not claim full
Git compatibility.

Known limitations include:

- no conflict-resolution workflow or recursive/octopus merges
- no packed refs or reflog support
- no remote transport or repository hosting workflows
- no packfile handling
- no rename detection in status or diff
- partial `.gitignore` semantics
- no support for index extensions beyond the documented `TREE` subset
- no concurrent index lock protocol
- no complete Git ignore/status/diff compatibility
- tracked file content is buffered in memory for status/diff operations

## Future capabilities

Planned work beyond the implemented Core scope includes:

- Hub repository hosting, permissions, and collaboration flows
- database-backed application metadata and API integration
- frontend interfaces for repository management
- AI-assisted developer workflows and repository analysis
- richer Git compatibility and advanced VCS operations

These are future capabilities and are not implemented in the current repository.

## Summary

CommitVerse Core is currently a Git-like version-control engine with a working
object database, Git index, tree and staging logic, commit/ref handling, history
traversal, read-only status/diff, and a CLI. Hub and AI remain future product
layers. The Core does not claim full Git compatibility and intentionally keeps its
scope bounded to the implemented Milestones 1–4.
