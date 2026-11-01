# CommitVerse Core Implementation Roadmap

## Status

This roadmap describes the planned sequence and current progress. The Core
package foundation, canonical object serialization, SHA-1 hashing, and
zlib-compressed loose-object storage with integrity validation are implemented.
Unit tests and external Git compatibility tests cover those object operations.
Milestone 1 is partial: repository initialization/discovery, CLI commands, and
repository-level workflows have not been implemented. Type-specific tree and
commit payload parsing, index/staging, refs, branching, merging, and transport
also remain future work. Each milestone depends on the earlier milestones
listed below. Acceptance criteria are testable gates; passing them does not by
itself imply full Git compatibility.

Use Python's standard library in production wherever practical and Pytest for
tests. Do not use GitPython or subprocess calls to system Git in production
implementation. External Git may be used only by compatibility tests.

## Development environment and commands

Use the existing repository-root `.venv` for local Core development. Never
install project dependencies globally. Core is an independently installable
package at `packages/commitverse-core/`, with its own
`packages/commitverse-core/pyproject.toml`, and is installed in editable mode
in the local development environment. Production requirements belong in
`dependencies` under `[project]`, and development-only requirements belong in
`dev` under `[project.optional-dependencies]`; the `dev` extra includes
Pytest. `.venv/` must remain excluded from Git. Whether a root-level
`pyproject.toml` is needed for workspace-wide configuration remains undecided
and does not replace the Core package configuration.

The local package setup and test workflow is:

```sh
python3 -m venv .venv
source .venv/bin/activate
cd packages/commitverse-core
python -m pip install -e ".[dev]"
python -m pytest
```

After the CLI package entry point has been implemented, the planned local
execution form is:

```sh
python -m commitverse_core --help
```

The module name and command availability are contingent on implementation; no
such entry point exists yet. Run the package commands from
`packages/commitverse-core/`. The package setup and focused unit tests have
been run; the engine command has not been implemented or verified.

Docker is mandatory infrastructure for reproducible environments and
containerized application services, and complements local Core development.
Do not require the standalone Python engine to run in Docker during initial
development. Keep Docker configuration modular. When integrated application
services are available, use Docker Compose for the FastAPI, PostgreSQL, and
frontend services. Run these planned commands from the directory containing
the Compose project file once that configuration exists:

```sh
docker compose up --build
docker compose down
```

Do not run these commands or install dependencies as part of this documentation
work.

## Milestone 1 — Repository initialization and blob storage

**Status: Partial.** Canonical object serialization, SHA-1 object IDs,
zlib-compressed loose-object writes/reads, and envelope integrity checks are
implemented for blob, tree, and commit payloads. Unit tests and external Git
compatibility tests cover these operations. Repository initialization and
discovery, CLI commands, and repository-level workflows remain unimplemented.

**Objective**

Create/discover a repository and implement validated Git-compatible SHA-1
loose blob storage.

**Modules**

- Repository discovery and initialization.
- Object ID and canonical object header utilities. **Implemented and tested.**
- Loose object store with zlib compression and integrity checks.
  **Implemented and tested for blob, tree, and commit payload bytes.**
- Typed storage and repository errors.
- CLI adapter and focused tests.

**CLI commands**

- `cv init [path]`
- `cv hash-object -w <path>`
- `cv cat-file -t <object-id>`
- `cv cat-file -s <object-id>`
- `cv cat-file -p <object-id>`

The exact command syntax and output should be finalized before implementation;
the names above are proposed. `cat-file -p` for a blob writes payload bytes
without an implicit text decode.

**Tests**

- Initialization creates a valid marker/layout and does not overwrite an
  existing repository's data.
- Repository discovery succeeds from nested worktree directories and fails
  clearly outside a repository.
- Known blob fixtures yield expected SHA-1 IDs and loose-object paths.
- Empty, binary, and newline-containing payloads round-trip exactly.
- Missing, malformed, truncated, invalid-zlib, size-mismatched, and
  hash-mismatched objects raise explicit errors.
- External Git compatibility tests compare blob IDs and exercise object
  read/write behavior in isolated temporary repositories; production code must
  not invoke Git.

**Acceptance criteria**

- Hash IDs are calculated over `<type> <size>\0<payload>` before compression.
- Loose objects are readable by object ID and are integrity-verified on read.
- Repository and object-store modules do not depend on CLI presentation.
- No application behavior is claimed beyond these tested object operations.
- Repository initialization/discovery and CLI operations remain incomplete.

**Dependencies**

- None; this is the foundation milestone.

## Milestone 2 — Trees and staging

**Objective**

Represent staged paths in an index, store tree objects with Git's raw binary
child IDs, and construct nested trees from staged entries.

**Modules**

- Tree serializer/parser and tree ordering.
- Index model and persistence.
- Worktree path/mode inspection.
- Staging application service and CLI adapter.

**CLI commands**

- `cv add <path>...`
- `cv add -A`
- `cv write-tree`
- `cv ls-files`

These are proposed command forms. Index file format and compatibility scope
must be decided before its persistence implementation.

**Tests**

- Tree entries encode IDs as exactly 20 raw bytes, not 40 hexadecimal bytes.
- Modes, names, NUL separators, and Git tree ordering produce expected
  payloads and object IDs.
- Nested directories produce child trees and a deterministic root tree.
- Staging binary files, executable files, and paths with non-ASCII bytes
  preserves supported path and file content semantics.
- Updating and removing staged paths follows explicit `add` behavior and does
  not mutate previously written objects.
- Index reload, malformed-index errors, and staged-vs-worktree comparisons
  behave as specified.

**Acceptance criteria**

- Writing a tree from an index produces Git-compatible tree payloads for the
  supported modes and paths.
- The index is documented, validated, and not confused with an object.
- Staging writes/reuses blobs and updates index entries without direct CLI
  storage logic.

**Dependencies**

- Milestone 1 for repository discovery, blob storage, object IDs, and object
  integrity checks.

## Milestone 3 — Commits and refs

**Objective**

Create commit objects that reference trees and parents; resolve `HEAD` and
create/update branch refs safely.

**Modules**

- Commit serializer/parser.
- Ref and symbolic `HEAD` resolution.
- Commit application service.
- Safe ref update and typed failure handling.

**CLI commands**

- `cv commit -m <message>`
- `cv rev-parse HEAD`
- `cv branch [<name>]`
- `cv branch --list`

These forms are proposed. Identity configuration and behavior when `HEAD` is
detached must be decided before implementation.

**Tests**

- Commit bytes have required tree, ordered parent, author, committer, blank
  line, and message structure.
- Root and multi-parent commits reference valid objects and round-trip exactly.
- Symbolic and detached `HEAD` resolve distinctly; branch refs use hexadecimal
  IDs and newline, never tree-entry binary encoding.
- Invalid names, missing objects, malformed refs, and invalid target types fail
  explicitly.
- Ref updates do not leave partial contents; concurrent update policy is
  tested before concurrent writers are claimed as supported.
- A Git compatibility test may inspect generated commits and refs externally.

**Acceptance criteria**

- A commit points to the tree written from the staged index and the expected
  parent commit(s).
- A successful commit advances the current branch according to the documented
  policy; failures do not report success or silently discard staged data.
- Ref and commit responsibilities remain independent of CLI output.

**Dependencies**

- Milestone 2 for index-to-tree construction.
- Milestone 1 for validated object storage.

## Milestone 4 — Status, diff, and log

**Objective**

Describe differences between working tree, index, and `HEAD`, and traverse
commit history.

**Modules**

- Tree/index/worktree comparison.
- Diff representation and output formatting.
- Commit graph traversal and log formatting.
- Status and diff application services.

**CLI commands**

- `cv status`
- `cv diff`
- `cv diff --cached`
- `cv log`

Proposed output formats should be documented before they are treated as stable.

**Tests**

- Status distinguishes staged, unstaged, and untracked paths.
- Diff compares the requested layers and handles add, modify, delete, mode
  change, binary content, and rename behavior according to documented scope.
- Log follows parent links, handles root and merge commits, and detects
  malformed or missing referenced objects.
- Clean, partially staged, and empty repositories report accurate state.
- Output tests cover stable fields without making incidental formatting a
  storage contract.

**Acceptance criteria**

- The three states—`HEAD`, index, and working tree—are compared independently
  and correctly for supported cases.
- Log output reflects commit parent relationships and does not mutate refs or
  objects.
- Unsupported cases are reported rather than silently misrepresented.

**Dependencies**

- Milestone 3 for commits, refs, and `HEAD`.
- Milestone 2 for index and tree operations.

## Milestone 5 — Branches, checkout, and basic merge

**Objective**

Support branch switching and a bounded, safe subset of merge behavior.
Initially, define “basic merge” as fast-forward and clean three-way merges for
supported text changes; detect conflicts and stop without silently overwriting
worktree or index data. Any narrower or broader scope must be decided before
implementation.

**Modules**

- Branch/ref operations.
- Checkout planning and safe worktree application.
- Merge-base and three-way merge logic.
- Conflict representation and resolution boundary.

**CLI commands**

- `cv branch <name>`
- `cv switch <branch>`
- `cv checkout <branch>`
- `cv merge <branch>`

The user-facing distinction between `switch` and `checkout` is to be defined;
the forms are proposed.

**Tests**

- Branch creation and switching update `HEAD` and working-tree/index state
  consistently.
- Checkout refuses or preserves uncommitted changes according to an explicit
  policy; paths outside the worktree are never modified.
- Fast-forward merge updates the target ref and checkout correctly.
- Clean three-way merge yields the expected tree and parent relationships.
- Conflicting changes are reported with reproducible conflict state and do not
  silently discard either side or unrelated local modifications.
- Merge tests cover missing bases, divergent histories, and merge commits for
  the declared scope.

**Acceptance criteria**

- Branch and checkout operations preserve committed objects and validate ref
  targets.
- Supported clean merges produce correct trees and history.
- Conflicts and unsafe checkout conditions are explicit and recoverable under
  documented behavior; unsupported merge cases are not claimed as supported.

**Dependencies**

- Milestone 3 for refs and commits.
- Milestone 4's comparison/diff model is recommended for safe change analysis.

## Milestone 6 — Remotes, fetch, push, and clone

**Objective**

Exchange refs and objects with remote repositories through a defined
Git-compatible transport and support clone, fetch, and push without invoking a
system Git executable.

**Modules**

- Remote configuration and validation.
- Transport/protocol implementation.
- Packfile creation, parsing, and object transfer as required by the selected
  protocol.
- Ref negotiation/update and clone repository initialization.
- Authentication boundary, with credentials supplied by a safe external
  configuration mechanism when selected.

The transport protocol, supported schemes, authentication approach, packfile
scope, and server-side push behavior are unresolved design decisions. Select
and document them before implementation; do not imply loose-object copying
alone is Git remote compatibility.

**CLI commands**

- `cv clone <remote> [directory]`
- `cv remote add <name> <url>`
- `cv fetch [<remote>]`
- `cv push [<remote> [<branch>]]`

These are proposed command forms, not available commands.

**Tests**

- Clone creates a repository with expected objects, refs, `HEAD`, and working
  tree for the supported transport and repository cases.
- Fetch transfers required history and objects, validates received object IDs,
  and updates only the intended remote-tracking refs.
- Push sends the intended objects/ref updates and rejects non-fast-forward or
  unauthorized updates according to the selected contract.
- Interrupted, malformed, corrupt, and rejected transfers do not leave refs
  pointing at missing or invalid objects.
- Transport tests use controlled local fixtures; external Git compatibility
  tests may verify interoperability without making Git a production runtime
  dependency.
- Credentials do not appear in logs, command output, or committed files.

**Acceptance criteria**

- Clone/fetch/push behavior is specified for the chosen protocol and verified
  with integration and external compatibility tests.
- All received objects are integrity-verified before refs can point to them.
- Network failures and rejected updates are explicit and do not report
  success-shaped partial completion.
- Support claims list tested protocols and limitations; full Git compatibility
  is not inferred from passing a narrow interoperability test.

**Dependencies**

- Milestones 1–3 for objects, refs, and commits.
- Milestone 5 for the planned branch and merge behavior relevant to push
  policies; fetch/clone may be implemented earlier only if dependency scope is
  documented.
