# CommitVerse Core Architecture

## Status and scope

This document describes the intended architecture and distinguishes it from
implemented behavior. Core currently has an installable Python package,
canonical object serialization and SHA-1 hashing in `objects/format.py`, and
zlib-compressed loose-object storage with integrity validation in
`objects/store.py`. `trees.py` serializes and parses supported Git tree entries;
`index.py` reads and writes Git index version 2; and `staging.py` stages
worktree paths and writes trees. Unit and integration tests cover these
operations. External Git compatibility tests verify object interoperability,
index interoperability in both directions, matching tree IDs, and Git
recognition of initialized repositories. `commits.py` serializes and parses
the supported commit headers; `refs.py` manages loose branch refs and symbolic
or detached `HEAD`; `commit_service.py` creates commits from the index; and
`history.py` traverses parent commits. The CLI provides commit, branch,
revision-resolution, and log commands, with isolated Git tests covering commit
and ref interoperability. `status.py` compares the committed tree, index, and
working tree without writing repository data; `diff.py` renders staged or
unstaged tracked-file changes as unified diffs.

The object store handles the common object envelope. Tree payloads are parsed
and validated separately; supported commit payloads are parsed and validated
separately. Bare and non-bare repository initialization/discovery and the `cv`
commands for object inspection, staging, tree writing, commits, local branch
listing/creation, revision resolution, history display, status, and diff are
implemented. Safe checkout/switching, merged-only branch deletion, merge-base
discovery, and basic merging are also implemented. Conflict resolution,
recursive/octopus merges, clone, and network transport are not implemented.
Read-only local transport, bounded local fetch, and local fast-forward-only
push are implemented as described below.

Core is a custom Git-like version control engine. Production implementation is
planned for Python's standard library wherever practical; Pytest is the test
framework. GitPython and subprocess calls to a system Git executable are not
part of the implementation. Git may be invoked externally by compatibility
tests. SHA-1 loose objects are the initial compatibility target; full Git
compatibility is not claimed.

## Proposed module boundaries

The module names below mix existing implementation and proposed work. Keep the
boundaries even if implementation uses a different internal naming scheme.

| Area | Responsibility |
|---|---|
| `cli` | Implemented repository/object, staging/tree, commit, branch, revision-resolution, history, status, and diff commands; parse arguments, map expected errors to diagnostics and exit codes, and delegate repository/object operations. |
| `commands` | Adapt each user command to application services; validate command-specific options and format output. |
| `repository` | Implemented initialization and parent-walking discovery for bare and non-bare SHA-1 repositories; provide shared Git-directory paths and capabilities without depending on the CLI or Hub. |
| `config` | Implemented validated, line-preserving repository configuration reads and locked atomic mutations for bare and non-bare Git directories. Remote management and URL resolution are future work. |
| `objects` | Implemented canonical object-byte serialization and hashing. |
| `object_store` | Implemented by `objects.store`: write, read, locate, and verify content-addressed loose objects. |
| `trees` | Implemented Git-compatible tree entry serialization, parsing, ordering, type validation, and nested tree construction from index entries. |
| `index` | Implemented Git index v2 encoding/decoding, checksum validation, entry metadata and stage preservation, and atomic replacement. |
| `staging` | Implemented path validation, file/symlink staging, recursive directory staging, `-A` updates/deletions, and the documented root `.gitignore` subset. |
| `commits` | Implemented serialization, parsing, and loose-object storage for supported tree/parent/author/committer/message fields. Optional commit headers and signatures are unsupported. |
| `refs` | Implemented loose branch refs, ref-name validation, safe atomic writes, symbolic/detached `HEAD`, and unborn-branch handling. |
| `commit_service` | Implemented identity lookup/overrides, tree/index coordination, no-op detection, commit writing, and current-HEAD advancement. |
| `history` | Implemented deterministic depth-first traversal of all parents with cycle/error detection and date/message formatting. |
| `status` | Implemented read-only comparison of commit trees, index entries, and filesystem state; reports staged, unstaged, and untracked paths. |
| `diff` | Implemented deterministic unified text diffs for staged or unstaged tracked-file changes, with binary and mode-change reporting. |
| `checkout` | Implemented preflighted worktree/index transitions for local branches, HEAD, and full commit IDs, with detached HEAD support. Mutations use type-aware temporary backups for tracked files, directories, symlinks, and modes; index, HEAD, and applicable branch refs are restored on failure, and rollback failures are surfaced. |
| `merge_base` | Implemented deterministic iterative common-ancestor traversal with malformed/cyclic graph detection; selection retains the distance-based heuristic and is not full Git merge-base dominance. |
| `merge` | Implemented fast-forward and basic three-way merges with content, add/add, modify/delete, and mode conflict reporting. Merge commits resolve author and committer identities using repository configuration and environment overrides. |
| `worktree` | Inspect paths and file modes in the checked-out working tree; apply checkout changes safely. |
| `merge` | Find merge bases, combine tree changes, and report conflicts without silently overwriting user data. |
| `transport` | Implemented read-only local filesystem advertisement and bounded local fetch; network protocols remain future work. |
| `errors` | Provide typed, actionable domain errors shared by application services and translated at the CLI boundary. |

Tests should be organized around public behavior and storage invariants, not
private CLI internals. Core's storage and domain modules must not import Hub,
FastAPI, SQLAlchemy, frontend, AI, or CLI presentation code.

## Proposed repository layout

This layout combines implemented modules with proposed future engine modules:

```text
packages/
    commitverse-core/
        pyproject.toml
        src/
            commitverse_core/
                cli.py
                commit_service.py
                commits.py
                diff.py
                history.py
                index.py
                objects/
                    format.py
                    store.py
                commands/
                repository.py
                refs.py
                staging.py
                status.py
                trees.py
                worktree.py
                merge.py
                errors.py
        tests/
            unit/
            integration/
            compatibility/
```

Tests must use temporary repositories and isolated working directories. External
Git invocations, if used, belong only in compatibility tests and must not be a
runtime dependency of Core.

## Local development environment

Core development and tests must run locally using the repository-root `.venv`;
Docker complements, but does not replace or gate, this initial standalone
workflow. The root `.venv/` exists and is excluded from Git. Never install
project dependencies globally. Core's package-level `pyproject.toml` at
`packages/commitverse-core/pyproject.toml` is the source of its Python project
configuration and dependency management, with production requirements
separated from development-only requirements. Core is installed in editable
mode in the local development environment, and Pytest is installed in its
development extra.

The scope of a root-level `pyproject.toml` is undecided. If introduced, it may
hold workspace-wide configuration but must not replace Core's
independently-installable package configuration.

Docker is mandatory infrastructure for reproducible environments and
containerized application services. Keep its configuration modular. Use
Docker Compose when integrating Hub's FastAPI, PostgreSQL, and frontend
services, but do not require Core itself to run in a container during initial
development.

The package's `pyproject.toml`, development dependency, and `cv` console entry
point are present. The entry point provides the implemented commands described
in the [implementation roadmap](./implementation-roadmap.md). Docker
configuration and commands not listed as implemented there remain future work.

## Repository and administrative layout

The implemented initial repository format supports both the conventional `.git`
administrative directory for a non-bare worktree and a Git-compatible bare
repository directory. Initialization creates
`objects/info`, `objects/pack`, `refs/heads`, and `refs/tags`, writes a Git
compatible SHA-1 `config`, and sets `HEAD` to `refs/heads/main`. Reinitializing
a valid repository preserves its existing data; malformed or unsupported
metadata is rejected. Discovery walks parent directories, validates the
repository structure/configuration and `HEAD`, and reports failure when no
supported repository is found. Bare repositories expose object and reference
operations without a working tree; staging, status, diff, checkout, switch,
and worktree merge operations explicitly require a non-bare repository.
Linked-worktree `.git` files are not supported.

The initialized repository contains:

```text
.git/
    HEAD
    config
    objects/
        info/
        pack/
    refs/
        heads/
        tags/
```

A bare repository uses the same administrative contents directly at its root:

```text
repository.git/
    HEAD
    config
    objects/
    refs/
```

Only loose object storage is implemented in the initial object-format scope.
`pack/` is created as part of the conventional layout, but packed-object
behavior is future work. The initial `config` fields follow Git's repository
format. The Git-compatible v2 index is created on the first staging update.
Milestone 6A.1 implements the shared Git-directory capability model and bare
initialization. Remote management, fetch, push, and clone remain planned:
fetch may read either kind, but push targets must be bare and non-bare push
targets must be rejected with an actionable error. Other Git interoperability
requirements remain future work. A CommitVerse-specific
extension must be explicit and must not change Git object or index formats.

Repository configuration is handled by `config.py`. It supports section
headers, quoted subsections, comments, blank lines, scalar keys, and repeated
keys, while retaining unrelated line formatting and ordering. Mutations use
an exclusively-created `config.lock`, validate the complete resulting
document, fsync the lock contents, atomically replace the config, and fsync
the parent directory. Unsupported syntax, malformed UTF-8, existing locks,
and durability failures are reported; stale locks are never removed
automatically. Remote management, credential handling, and relative URL
resolution are not implemented.

## Object database and object relationships

The object database is content-addressed: the object ID is the SHA-1 digest of
the canonical, uncompressed Git object bytes. The loose-object file contains
the zlib-compressed canonical bytes. The detailed byte format is specified in
[Git Object Format](./git-object-format.md).

The planned object model is:

- **Blob:** stores file content bytes. It has no filename or directory
  information; the same content can be referenced from multiple paths.
- **Tree:** stores named entries with modes and object IDs. File entries
  reference blobs; directory entries reference other trees. A root tree
  describes the complete tracked snapshot.
- **Commit:** references one root tree and zero or more parent commits, plus
  author, committer, and message metadata. A root commit has no parent.

Objects are immutable once written. Updating a file creates or reuses its blob,
then new trees along the changed path; a new commit points at the resulting root
tree. Unchanged objects can be shared by ID. Refs, the index, and the worktree
are not Git objects.

Loose-object reads must validate decompression, object header, declared payload
size, object type, and the SHA-1 ID against the canonical bytes before exposing
the object. Corrupt or mismatched data is an error, not a cache miss or a
success-shaped fallback. The object storage layer performs envelope and
integrity checks. The tree layer parses and validates supported tree entries;
the commit layer parses and validates the documented commit header subset.

## Index and staging

The index is the boundary between the working tree and the next committed
tree. The current implementation reads and writes Git index version 2 with
`DIRC`, ten stat fields, object IDs, path/stage flags, NUL-terminated paths,
eight-byte entry padding, and a trailing SHA-1 checksum. It preserves stage
and stat fields, validates pathname ordering and the checksum, and atomically
replaces the index file. A missing index reads as empty.

The only supported index extension is `TREE`, stored opaquely and discarded
when an entry change invalidates cached tree data. Other extensions, extended
entry flags, and index versions other than 2 are rejected explicitly.
Concurrent index writers and Git's lock-file protocol are not supported.

`add <path>...` stages files and recursively visits directories, preserving
regular/executable/symlink modes and filesystem path bytes where supported.
`add -A` stages visible additions and modifications and removes deleted tracked
paths. Neither form stages the repository's `.git` directory. Paths that
resolve outside the worktree are rejected. Nested repositories are skipped
during `-A` traversal and cannot be explicitly staged; gitlinks are not
implemented. Empty directories are not staged.
`write-tree` turns stage-zero index entries into nested Git tree objects and
rejects unmerged or conflicting paths. `ls-files` lists each staged path once
in deterministic order.

Ignore handling reads only the worktree-root `.gitignore`, which must be a
regular file. The implemented subset supports blank/comment lines, simple
`fnmatch` patterns, leading `/`, trailing `/`, and `!` negation in rule order.
It does not implement nested
ignore files, Git's full wildmatch/escape rules, global excludes, or all parent
directory negation rules. Ignored untracked paths are not staged; already
tracked paths remain tracked and are refreshed by `add -A`.

## Refs and `HEAD`

Loose local branches are mutable refs under `.git/refs/heads/`. Each supported
ref contains one full lowercase 40-character commit ID followed by a newline.
`HEAD` is either a symbolic `ref: refs/heads/<name>` line or a detached full
commit ID. Ref contents use hexadecimal IDs, distinct from raw binary IDs
embedded in tree entries. Ref names are checked against Git's common
`check-ref-format` restrictions; packed refs, reflogs as a managed feature,
symbolic refs other than `HEAD`, and ref transactions are unsupported.

Ref reads validate file contents and referenced commit objects. Writes use a
same-directory temporary file and atomic replacement; branch creation uses an
atomic create-if-absent operation and refuses duplicates. Locks and concurrent
writer protection are not implemented. A missing symbolic `refs/heads/*`
target is an unborn branch: `branch` lists it as current, while `rev-parse
HEAD` reports that it does not yet resolve to a commit. Detached commits update
`HEAD` directly and never move a branch ref. Creating a branch requires an
existing commit and is rejected while the current repository is unborn.

Commit identity comes from `[user] name` and `[user] email` in `.git/config`.
`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, and
`GIT_COMMITTER_EMAIL` override those values. The corresponding
`GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` accept the documented
`@<unix-seconds> ±HHMM` form (the leading `@` is optional). Without date
overrides, the local clock and timezone are used.

## Command execution and data flow

Commands should be thin adapters over Core application services. A normal
command follows this flow:

1. Parse arguments and resolve the current directory and repository.
2. Validate command options and discover repository state.
3. Call a typed application service, which coordinates worktree, index, object
   store, tree, commit, and ref operations as required.
4. Persist changes through storage modules with validation and safe writes.
5. Return a result for the CLI to format; translate expected domain errors to
   concise diagnostics and meaningful nonzero exit codes.

Implemented `add` flow: select paths, validate that they are inside the
worktree, read file bytes and mode, write or reuse blobs, and update the index.
Implemented `write-tree` flow: validate stage-zero index entries, construct
nested tree objects, and print the root tree ID. Implemented `commit` flow:
write a commit referencing the index-derived tree and current parent, then
advance symbolic or detached `HEAD`. An empty initial commit and an unchanged
tree are rejected; deleting the final tracked paths is allowed when it changes
the current tree. `log` traverses all reachable parents deterministically.

Storage code returns typed values or raises typed errors; it does not print to
the terminal. The CLI handles arguments, output, and process exit status; it
does not parse loose objects. The object database is independent of the CLI,
Hub database metadata, and web/API layers.

## Error handling and safety

Use specific errors for conditions such as not-a-repository, invalid path,
missing object, corrupt object, malformed index, invalid ref, merge conflict,
and concurrent ref update. Include the relevant path or object ID in diagnostics
where safe. Do not catch broad exceptions merely to continue or report success;
unexpected failures should retain their cause and be observable.

Validate paths against repository boundaries and handle symlinks deliberately.
Never follow a user-controlled path outside the worktree as an implicit
repository operation. Index replacement uses a temporary file and atomic
rename; object creation is content-addressed. Concurrent-writer locking,
crash consistency across object and index updates, and resource limits for
untrusted input are not claimed.

## Separation of concerns

- **Core object storage** owns repository objects and refs/index/worktree state.
- **Hub** may later call Core through an explicit interface; it must not store
  Git objects in PostgreSQL or depend on undocumented Core internals.
- **CLI** is one interface to Core, not the owner of its logic or storage.
- **AI** is a future component with no assumed access to repositories.
- **Tests** can invoke external Git for compatibility evidence but production
  Core cannot invoke Git or delegate version-control behavior to another
  engine.

## Data flow summary

```text
working tree
    -> blob objects
    -> index (staged path/mode/object-ID records)
    -> nested tree objects
    -> commit object
    -> branch ref / HEAD
```

The object, index, tree, commit, ref, history, status, and diff flows are
implemented for the documented subset. Local loose-object fetch validates and
stores objects before publishing remote-tracking refs. Local push is limited to
bare repositories and is fast-forward-only, using individually locked
compare-and-swap ref updates; clone, remote management, and network push remain
future work.

Loose reference compare-and-swap is implemented in `refs.py` for bare and
non-bare repositories. It validates ref names and commit targets, creates the
exact `<ref>.lock` path exclusively, re-reads the current value while holding
the lock, checks the expected object ID or absence, fsyncs the lock contents,
and atomically publishes the new value. Deletion uses the same lock and
validation protocol. Failures before replacement preserve the old ref and
remove only the operation's lock; after replacement, callers receive a
publication-state-bearing error if parent-directory fsync fails. This
guarantees no lost updates among cooperating CommitVerse processes for one
loose ref, but does not provide multi-ref atomicity, stale-lock recovery,
packed-ref concurrency, or rollback after publication.

Milestone 6A.4 adds a read-only local filesystem transport under
`transport/`. `LocalFilesystemTransport.open(path, base=...)` opens a bare or
non-bare repository at the supplied root; relative paths require the explicit
base directory. Its advertisement validates loose local branches, supported
loose tags, symbolic or detached `HEAD`, object IDs, and referenced objects,
then returns deterministic branch/tag records without creating locks or
modifying the remote. Packed refs, clone, remote configuration, and network
transports remain unsupported by this local transport.

Milestone 6A.5 adds bounded local fetch in `fetch.py`. The iterative
reachability walker validates commit, tree, and blob closures without Python
recursion, detects cycles and malformed or missing objects, and enforces a
64 MiB compressed-object limit, 64 MiB decompressed-object limit, 1 GiB
decompressed missing-object transfer limit, 1,000,000 object limit, and
1,000,000 commit traversal limit. Fetch validates and stores the complete
closure before publishing deterministic remote-tracking refs through
compare-and-swap. A failed publication can leave earlier refs published and
validated objects unreachable; local branches, `HEAD`, index, and worktree
are not modified.

Milestone 6A.6 adds `push_to_local()` in `push.py`. It requires an explicit
non-bare source branch and a valid bare destination, supports initial branch
creation and explicit destination branch mapping, and proves fast-forward
status from the commit parent graph using iterative closure validation. Missing
objects are transferred and revalidated before the destination ref is
published through compare-and-swap with the observed old value. Transfer
failures publish no ref; a concurrent CAS conflict leaves the destination ref
unchanged but may leave validated unreachable objects. Push does not modify
source branches, `HEAD`, index, worktree, destination `HEAD`, or unrelated
branches. Force push, tags, packed refs, clone, multi-ref atomicity, and
network transports remain unsupported.

## Status and diff

`status.py` compares three independent snapshots: the current commit tree
(empty for an unborn branch), stage-zero index entries, and the filesystem
contents/modes for paths present in either tracked snapshot. The `HEAD` to
index comparison yields staged additions, modifications, and deletions. The
index to working-tree comparison yields unstaged changes, including a working
copy that differs from an already-staged version. Paths tracked by either
`HEAD` or the index remain tracked even if they become ignored. Untracked
regular files and symlinks are listed separately, subject to the implemented
root `.gitignore` subset; `.git`, nested repositories, and ignored paths are
excluded. Unmerged index entries and tracked special filesystem objects are
reported as errors. Rename detection is not implemented.

`cv diff` compares the index to the working tree; `cv diff --cached` compares
`HEAD` to the index. Neither includes untracked files. Output is deterministic
and uses unified hunks for valid UTF-8 text without NUL bytes. Other content is
reported as binary rather than decoded with replacement characters. Missing
final newlines are marked explicitly, and supported executable/symlink mode
changes are shown. Status and diff are read-only: they do not write objects,
the index, or references.

Filesystem inspection uses descriptor-relative, no-follow access for tracked
files and does not traverse symlink directories. It rejects a tracked path
that enters `.git`, a file that changes while it is being read, and unsafe or
unsupported filesystem cases. Tracked file bytes are currently buffered in
memory for hashing and diff generation; there is no large-file resource limit
or streaming diff implementation.
