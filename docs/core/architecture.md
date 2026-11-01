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
recognition of initialized repositories.

The object store handles the common object envelope. Tree payloads are parsed
and validated separately; commit payloads remain opaque bytes. Non-bare
repository initialization/discovery and the initial `cv` commands for object
inspection, staging, and tree writing are implemented. Commit creation and
parsing, refs as repository operations, branching, checkout, merging, and
transport are not implemented.

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
| `cli` | Implemented `cv init`, `cv hash-object -w`, `cv cat-file -t/-s/-p`, `cv add`, `cv write-tree`, and `cv ls-files`; parse arguments, map expected errors to diagnostics and exit codes, and delegate repository/object operations. |
| `commands` | Adapt each user command to application services; validate command-specific options and format output. |
| `repository` | Implemented initialization and parent-walking discovery for non-bare SHA-1 repositories; provide repository paths without depending on the CLI or Hub. |
| `objects` | Implemented canonical object-byte serialization and hashing. Typed commit payload parsing remains future work. |
| `object_store` | Implemented by `objects.store`: write, read, locate, and verify content-addressed loose objects. |
| `trees` | Implemented Git-compatible tree entry serialization, parsing, ordering, type validation, and nested tree construction from index entries. |
| `index` | Implemented Git index v2 encoding/decoding, checksum validation, entry metadata and stage preservation, and atomic replacement. |
| `staging` | Implemented path validation, file/symlink staging, recursive directory staging, `-A` updates/deletions, and the documented root `.gitignore` subset. |
| `refs` | Read/update branches and other refs, resolve symbolic or detached `HEAD`, and perform safe ref updates. |
| `worktree` | Inspect paths and file modes in the checked-out working tree; apply checkout changes safely. |
| `diff` | Compare object trees, index state, and working-tree content and represent changes independently of output formatting. |
| `merge` | Find merge bases, combine tree changes, and report conflicts without silently overwriting user data. |
| `transport` (future) | Exchange objects and refs with remotes through an explicitly selected protocol; must not shell out to Git. |
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
                index.py
                objects/
                    format.py
                    store.py
                commands/
                repository.py
                staging.py
                trees.py
                refs.py
                worktree.py
                diff.py
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
configuration and all other CLI commands remain future work.

## Repository and administrative layout

The implemented initial repository format uses the conventional `.git`
administrative directory for a non-bare worktree. Initialization creates
`objects/info`, `objects/pack`, `refs/heads`, and `refs/tags`, writes a Git
compatible SHA-1 `config`, and sets `HEAD` to `refs/heads/main`. Reinitializing
a valid repository preserves its existing data; malformed or unsupported
metadata is rejected. Discovery walks parent directories, validates the
repository structure/configuration and `HEAD`, and reports failure when no
supported repository is found. Bare repositories and linked-worktree `.git`
files are not supported.

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

Only loose object storage is implemented in the initial object-format scope.
`pack/` is created as part of the conventional layout, but packed-object
behavior is future work. The initial `config` fields follow Git's repository
format. The Git-compatible v2 index is created on the first staging update.
Bare repositories and linked-worktree `.git` files remain unsupported. Other
Git interoperability requirements remain future work. A CommitVerse-specific
extension must be explicit and must not change Git object or index formats.

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
commit payload parsing remains future work.

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

Branches are mutable refs that name commit object IDs, conventionally stored
under `.git/refs/heads/`. In a symbolic state, `.git/HEAD` contains a ref such
as `ref: refs/heads/main\n`; in detached state it contains a commit's full
hexadecimal object ID and newline. Ref contents use hexadecimal IDs; this is
distinct from the raw binary object IDs embedded in tree entries.

Ref updates should validate the target object and use safe writes so a partial
write cannot leave a truncated ref. Concurrent-update protection and locking
must be designed before concurrent writers are supported. Updating a branch
does not mutate the commit object it names.

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
nested tree objects, and print the root tree ID. Example `commit` flow:
construct and write a commit referencing the root tree and current parent, then
advance the current branch ref (or handle detached `HEAD` according to an
explicitly defined policy).

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

Status and diff compare these layers; log traverses commit parent links. Future
remote operations exchange refs and objects through a transport boundary.
These are intended flows, not implemented commands.
