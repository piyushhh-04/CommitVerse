# CommitVerse Core Implementation Roadmap

## Status

This roadmap describes the planned sequence and current progress. The Core
package foundation, canonical object serialization, SHA-1 hashing,
zlib-compressed loose-object storage with integrity validation, bare and
non-bare repository initialization/discovery, Git-compatible trees, index-v2 staging,
commit objects, loose branch refs, symbolic/detached `HEAD`, initial branch
operations, revision resolution, history traversal, and their CLI commands
are implemented. Read-only status and tracked-file diff comparisons, safe
checkout/switching, merged-only branch deletion, merge-base discovery, and
basic fast-forward/three-way merges are implemented for the documented subset.
Unit, integration, and external Git compatibility tests cover these behaviors.
Conflict resolution, recursive/octopus merges, and transport remain future
work. Milestone 6A.2 adds validated, formatting-preserving repository
configuration reads and lock-based atomic updates for bare and non-bare
repositories; remote management remains future work.
Each milestone depends on the earlier milestones listed below. Acceptance
criteria are testable gates; passing them does not by itself imply full Git
compatibility.

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

Install the package in the root virtual environment to register the `cv`
console command:

```sh
.venv/bin/python -m pip install -e "packages/commitverse-core[dev]"
.venv/bin/cv --help
```

The initial commands are:

```sh
.venv/bin/cv init [path]
.venv/bin/cv init --bare <path>
.venv/bin/cv hash-object -w <file>
.venv/bin/cv cat-file -t <object-id>
.venv/bin/cv cat-file -s <object-id>
.venv/bin/cv cat-file -p <object-id>
.venv/bin/cv add <path> [<path> ...]
.venv/bin/cv add -A
.venv/bin/cv write-tree
.venv/bin/cv ls-files
.venv/bin/cv commit -m "message"
.venv/bin/cv branch [--list|<name>]
.venv/bin/cv rev-parse <revision>
.venv/bin/cv log
.venv/bin/cv status
.venv/bin/cv diff
.venv/bin/cv diff --cached
.venv/bin/cv switch <branch>
.venv/bin/cv checkout <HEAD|branch|full-commit-id>
.venv/bin/cv branch -d <merged-branch>
.venv/bin/cv merge <branch>
```

`cat-file -p` writes payload bytes directly to standard output. Object commands
discover the repository by walking parent directories from the current working
directory.

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

These container commands are not needed for standalone Core development.

## Milestone 1 — Repository initialization and blob storage

**Status: Implemented for the initial scope.** Core initializes and discovers
non-bare SHA-1 repositories, and provides `cv init`, `cv hash-object -w`, and
`cv cat-file -t/-s/-p`. Canonical serialization, hashing, loose-object storage,
and envelope integrity checks support blob, tree, and commit payload bytes.
Unit/integration tests and external Git compatibility tests verify this scope.
Milestone 1 stored commit payloads as opaque bytes; structured commit handling
and workflow commands are covered by Milestone 3. Git tree parsing and staging
are covered by Milestone 2 below.

**Objective**

Create/discover a repository and implement validated Git-compatible SHA-1
loose blob storage.

**Modules**

- Non-bare repository discovery and initialization. **Implemented and tested.**
- Object ID and canonical object header utilities. **Implemented and tested.**
- Loose object store with zlib compression and integrity checks.
  **Implemented and tested for blob, tree, and commit payload bytes.**
- Clear repository and CLI error handling. **Implemented and tested.**
- Initial CLI adapter and commands. **Implemented and tested.**

**CLI commands**

- `cv init [path]`
- `cv hash-object -w <path>`
- `cv cat-file -t <object-id>`
- `cv cat-file -s <object-id>`
- `cv cat-file -p <object-id>`

The listed command syntax is implemented. `cat-file -p` writes payload bytes
without an implicit text decode. Staging and commit workflows are implemented
in the later milestones below.

**Tests**

- Initialization creates a Git-recognized marker/layout and preserves valid
  existing repository data on reinitialization.
- Repository discovery succeeds from nested worktree directories and fails
  clearly outside or at malformed repository metadata.
- Known blob fixtures yield expected SHA-1 IDs and loose-object paths.
- Empty, binary, and newline-containing payloads round-trip exactly.
- Missing, malformed, truncated, invalid-zlib, size-mismatched, and
  hash-mismatched objects raise explicit errors.
- External Git compatibility tests verify Git recognizes initialized
  repositories, reads CLI-written blobs, and CommitVerse reads Git-written
  blobs in isolated temporary repositories; production code must not invoke
  Git.

**Acceptance criteria**

- Hash IDs are calculated over `<type> <size>\0<payload>` before compression.
- Loose objects are readable by object ID and are integrity-verified on read.
- Repository and object-store modules do not depend on CLI presentation.
- No application behavior is claimed beyond the implemented repository,
  object, and CLI operations.

**Dependencies**

- None; this is the foundation milestone.

## Milestone 2 — Trees and staging

**Status: Implemented and externally verified for the documented subset.**
Tree entries use Git's raw 20-byte object IDs and directory-aware ordering.
The staging index reads and writes Git index v2, and the CLI supports explicit
path/directory staging, `-A`, `write-tree`, and `ls-files`. Git and CommitVerse
read each other's indexes and generate identical trees in isolated test
repositories.

**Objective**

Represent staged paths in an index, store tree objects with Git's raw binary
child IDs, and construct nested trees from staged entries.

**Modules**

- Tree serializer/parser and tree ordering. **Implemented and tested.**
- Index v2 model, validation, checksum, and atomic persistence.
  **Implemented and tested.**
- Worktree path/mode inspection. **Implemented for regular files and symlinks.**
- Staging application service and CLI adapter. **Implemented and tested.**

**CLI commands**

- `cv add <path>...`
- `cv add -A`
- `cv write-tree`
- `cv ls-files`

These command forms are implemented. `add -A` stages additions, modifications,
and deletions. A root `.gitignore` subset is documented in the architecture
guide; full Git ignore semantics are not claimed.

**Tests**

- Tree entries encode IDs as exactly 20 raw bytes, not 40 hexadecimal bytes.
- Modes, names, NUL separators, and Git tree ordering produce expected
  payloads and object IDs.
- Nested directories produce child trees and a deterministic root tree.
- Staging binary files, executable files, and paths with non-ASCII bytes
  preserves supported path and file content semantics.
- Updating and removing staged paths follows explicit `add` behavior and does
  not mutate previously written objects.
- Index reload, malformed-index errors, checksum validation, and stat-field
  preservation behave as specified.
- Git can read CommitVerse-generated trees and indexes; CommitVerse can read a
  Git-staged index, and both produce the same root tree ID.
- Index versions other than 2, unsupported extensions/extended flags, gitlinks,
  and concurrent index writers fail or remain unsupported as documented.

**Acceptance criteria**

- Writing a tree from an index produces Git-compatible tree payloads for the
  supported modes and paths.
- The index is documented, validated, and not confused with an object.
- Staging writes/reuses blobs and updates index entries without direct CLI
  storage logic.
- `ls-files` is deterministic, and `write-tree` rejects conflicts and writes an
  empty tree for an empty index.

**Dependencies**

- Milestone 1 for repository discovery, blob storage, object IDs, and object
  integrity checks.

## Milestone 3 — Commits, refs, and initial history commands

**Status: Implemented for the documented subset.** Commit payloads are
serialized, parsed, stored, and verified against referenced tree/parent object
types. `cv commit -m` derives a tree from the index, uses the current commit as
its sole parent when present, reads identity from repository configuration
with environment overrides, and atomically advances symbolic or detached
`HEAD`. Loose local branch refs can be listed and created. `rev-parse` resolves
`HEAD`, local branch names, and full commit IDs. `log` traverses all parents in
deterministic depth-first order with cycle and corruption detection. Isolated
Git compatibility tests verify commit IDs, objects, refs, `HEAD`, and history.

Empty initial commits and commits whose tree equals the current `HEAD` tree are
rejected. Removing the last tracked paths is permitted when it changes the
tree. Optional commit headers, packed refs, reflog management, ref locks, and
concurrent ref updates are unsupported. An unborn branch is listed as current;
branch creation is rejected until the first commit exists.

**Objective**

Create commit objects that reference trees and parents; resolve `HEAD` and
create/update branch refs safely.

**Modules**

- Commit serializer/parser. **Implemented and tested.**
- Ref and symbolic/detached `HEAD` resolution. **Implemented and tested.**
- Commit application service. **Implemented and tested.**
- Safe atomic loose-ref updates and typed failure handling. **Implemented;**
  concurrent writers are unsupported.

**CLI commands**

- `cv commit -m <message>`
- `cv rev-parse <revision>`
- `cv branch [--list|<name>]`
- `cv log`

These command forms are implemented. Identity is read from `.git/config`
`[user]` settings and may be overridden with the documented `GIT_AUTHOR_*` and
`GIT_COMMITTER_*` variables. Date overrides support `@<unix-seconds> ±HHMM`.
Commits in detached state advance `HEAD` without moving any branch.

**Tests**

- Commit bytes have required tree, ordered parent, author, committer, blank
  line, and message structure.
- Root and multi-parent commits reference valid objects and round-trip exactly.
- Symbolic and detached `HEAD` resolve distinctly; branch refs use hexadecimal
  IDs and newline, never tree-entry binary encoding.
- Invalid names, missing objects, malformed refs, and invalid target types fail
  explicitly.
- Ref updates do not leave partial contents. Concurrent ref writers are
  unsupported.
- Isolated Git compatibility tests inspect generated commits and refs and
  read ordinary Git-generated commits.

**Acceptance criteria**

- A commit points to the tree written from the staged index and the expected
  parent commit(s).
- A successful commit advances symbolic `HEAD` or detached `HEAD` according
  to the documented policy; failures do not report success or silently
  discard staged data.
- Ref and commit responsibilities remain independent of CLI output.

**Dependencies**

- Milestone 2 for index-to-tree construction.
- Milestone 1 for validated object storage.

## Milestone 4 — Status and diff

**Status: Implemented for the documented subset.** `cv status` compares
`HEAD`, the index, and the working tree, and classifies staged, unstaged, and
untracked paths. `cv diff` compares index to worktree; `cv diff --cached`
compares `HEAD` to index. Status/diff do not write repository state. Isolated
Git compatibility tests compare supported staged/unstaged classifications and
changed paths.

Rename detection, porcelain/color options, full Git ignore semantics,
unmerged-index presentation, and full Git status/diff compatibility are
unsupported. Diff excludes untracked files, recognizes text only as strict
UTF-8 without NUL bytes, and reports other contents as binary. Tracked
filesystem reads reject symlink traversal outside the worktree and report
concurrent file changes. Tracked file payloads are currently buffered in
memory.

**Objective**

Describe differences between working tree, index, and `HEAD`.

**Modules**

- Tree/index/worktree comparison — implemented for stage-zero entries and
  supported filesystem paths.
- Diff representation and deterministic output — implemented for staged and
  unstaged tracked-file changes.
- Status output and application service — implemented for staged, unstaged,
  untracked, clean, and unborn states.

**CLI commands**

- `cv status`
- `cv diff`
- `cv diff --cached`

These command forms are implemented. Output is deterministic and human-readable
but is not a stable porcelain interface.

**Tests**

- Status distinguishes staged, unstaged, and untracked paths.
- Diff compares the requested layers and handles add, modify, delete, mode
  changes, binary content, and missing-final-newline markers; rename detection
  is not implemented.
- Clean, partially staged, and empty repositories report accurate state.
- Output tests cover stable fields without making incidental formatting a
  storage contract.

**Acceptance criteria**

- The three states—`HEAD`, index, and working tree—are compared independently
  and correctly for supported cases.
- Unsupported cases are reported rather than silently misrepresented.

**Dependencies**

- Milestone 3 for commits, refs, and `HEAD`.
- Milestone 2 for index and tree operations.

## Milestone 5 — Branch switching, checkout, and basic merge

**Objective**

Support branch switching and a bounded, safe subset of merge behavior.
Initially, define “basic merge” as fast-forward and clean three-way merges for
supported text changes; detect conflicts and stop without silently overwriting
worktree or index data. Any narrower or broader scope must be decided before
implementation.

**Modules**

- Branch switching on the loose refs implemented in Milestone 3.
- Checkout planning and safe worktree application.
- Merge-base and three-way merge logic.
- Conflict representation and resolution boundary.

**CLI commands**

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

## Milestone 6A — Local remotes, fetch, push, and clone

**Objective**

Exchange refs and objects with local bare or non-bare repositories through a
local filesystem transport and Git-compatible SHA-1 loose objects. Repository
capability modeling and bare initialization are implemented in Milestone 6A.1;
remote management, fetch, push, and clone remain planned. Fetch may read bare
or non-bare repositories; push initially targets bare repositories only.

**Modules**

- Shared Git-directory/repository capability abstraction for bare and non-bare
  repositories; worktree operations remain unavailable for bare repositories.
- Formatting-preserving remote configuration with atomic writes and no
  credentials.
- Local filesystem transport and validated remote ref advertisement.
- Bounded iterative reachability traversal over commit, tree, and blob
  objects.
- Fetch that validates and stores all required objects before publishing
  remote-tracking refs.
- Fast-forward-only push to bare repositories using lock-based compare-and-swap
  ref updates.
- Clone through a temporary sibling directory, published only after setup and
  checkout succeed.

Single-ref updates use an exclusively created lock file, expected-old-value
checking while the lock is held, write and `fsync`, and atomic replacement.
Failures before replacement preserve the old ref; after replacement, rollback
is not claimed or guaranteed. Multi-ref fetch publication is individually
atomic, not one atomic transaction. Valid copied objects may remain
unreachable after a failed transfer.

**CLI commands**

- `cv clone <remote> [directory]`
- `cv remote add <name> <url>`
- `cv fetch [<remote>]`
- `cv push [<remote> [<branch>]]`

These are proposed command forms, not available commands. Bare repositories
support object and ref operations, remote advertisement, fetch, and push
endpoints; staging, status, diff, checkout, switch, and worktree merge
operations require a non-bare repository. A non-bare push target must be
rejected with an actionable error.

Relative local remote paths are resolved against the source repository's stable
location before clone creates its temporary sibling directory. The resolved
remote must remain valid after the temporary clone is renamed to its final
destination.

Remote removal deletes only that remote's configuration and does not silently
delete its remote-tracking refs. Remote rename preflights all source refs,
destination refs, configuration sections, and upstream references. It rejects
destination collisions before changes, then performs individually locked and
validated ref operations plus configuration updates. This is not a
multi-ref atomic transaction: if it fails after some refs move, it reports
exactly which refs moved and which did not, does not claim rollback, and never
silently discards refs or rewrites unrelated configuration.

**Tests**

- Clone creates a repository with expected objects, refs, `HEAD`, and working
  tree for the supported transport and repository cases.
- Relative local remotes are resolved correctly before temporary-sibling clone
  setup, the completed clone is published by rename, and fetching from the
  published clone still reaches the configured remote.
- Clone failure cleanup never deletes an existing destination.
- Fetch transfers required history and objects, validates received object IDs,
  and updates only the intended remote-tracking refs.
- Push sends the intended objects/ref updates and rejects non-fast-forward or
  unauthorized updates according to the selected contract; non-bare push
  targets are rejected.
- Interrupted, malformed, corrupt, and rejected transfers do not leave refs
  pointing at missing or invalid objects.
- Transport tests use controlled local fixtures; external Git compatibility
  tests may verify interoperability without making Git a production runtime
  dependency.
- Credentials do not appear in logs, command output, or committed files.
- Failure-injection tests cover ref-lock creation, expected-old mismatches,
  failures before and after ref replacement, partial remote rename progress,
  relative URL resolution, clone publication, and destination cleanup.

**Acceptance criteria**

- Clone/fetch/push behavior is specified for the chosen protocol and verified
  with integration and external compatibility tests.
- All received objects are integrity-verified before refs can point to them.
- Network failures and rejected updates are explicit and do not report
  success-shaped partial completion.
- Support claims list tested protocols and limitations; full Git compatibility
  is not inferred from passing a narrow interoperability test.
- Transfer-time limits bound decompressed object size, total bytes, object
  count, and commit traversal. Existing unrestricted local object behavior is
  not changed implicitly.

**Dependencies**

- Milestones 1–3 for objects, refs, and commits.
- Milestone 5 for branch and merge behavior relevant to push policies.

### Final phase sequence

1. **6A.1 Repository capability model and bare initialization**
2. **6A.2 Shared configuration abstraction** (implemented)
3. **6A.3 Compare-and-swap reference updates** (implemented)
4. **6A.4 Local transport and remote advertisement** (implemented)
5. **6A.5 Reachability traversal and fetch**
6. **6A.6 Fast-forward-only push to bare repositories**
7. **6A.7 Clone**
8. **6A.8 Git interoperability, documentation, and final validation**

Packfiles, packed refs, smart HTTP, SSH, Git wire protocols, remote hosting,
credentials, authentication, force push, multi-ref atomic push, shallow
history, tags, submodules, SHA-256 repositories, and cloud storage are
explicitly deferred.
