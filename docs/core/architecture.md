# CommitVerse Core Architecture

## Status and scope

This is the proposed architecture for CommitVerse Core. It is a design document,
not evidence of an implementation. The repository currently has no Core source
code, CLI, object database, or tests.

Core is a custom Git-like version control engine. Production implementation is
planned for Python's standard library wherever practical; Pytest is the test
framework. GitPython and subprocess calls to a system Git executable are not
part of the implementation. Git may be invoked externally by compatibility
tests. SHA-1 loose objects are the initial compatibility target; full Git
compatibility is not claimed.

## Proposed module boundaries

The names and layout below are proposals, not existing modules. Keep the
boundaries even if implementation uses a different internal naming scheme.

| Area | Responsibility |
|---|---|
| `cli` | Parse arguments, select a command, map domain errors to user-facing diagnostics and exit codes. Must not implement object serialization or repository mutations itself. |
| `commands` | Adapt each user command to application services; validate command-specific options and format output. |
| `repository` | Discover and represent a worktree and its administrative directory; provide repository-scoped services without depending on the CLI or Hub. |
| `objects` | Define typed object values and canonical blob, tree, and commit serialization/parsing. |
| `object_store` | Write, read, locate, and verify content-addressed loose objects. |
| `index` | Read and write the staging index; represent staged paths and their modes and object IDs. |
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

This is an illustrative target, not a claim about files already present:

```text
packages/
    commitverse-core/
        pyproject.toml
        src/
            commitverse_core/
                __main__.py
                cli.py
                commands/
                repository.py
                objects/
                object_store.py
                index.py
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
workflow. Never install project dependencies globally. Core's package-level
`pyproject.toml` at `packages/commitverse-core/pyproject.toml` is the source of
its Python project configuration and dependency management, with production
requirements separated from development-only requirements. The root `.venv/`
is excluded from Git.

The scope of a root-level `pyproject.toml` is undecided. If introduced, it may
hold workspace-wide configuration but must not replace Core's
independently-installable package configuration.

Docker is mandatory infrastructure for reproducible environments and
containerized application services. Keep its configuration modular. Use
Docker Compose when integrating Hub's FastAPI, PostgreSQL, and frontend
services, but do not require Core itself to run in a container during initial
development.

The repository does not yet contain the Core package's `pyproject.toml`, the
proposed package entry point, dependencies, or Docker configuration. Future
setup and execution commands are documented in the
[implementation roadmap](./implementation-roadmap.md); they are plans, not
commands verified against an existing application.

## Repository and administrative layout

The initial repository format should use the conventional `.git` administrative
directory for a non-bare worktree. A bare repository has no checked-out
worktree; support for it is a separate capability and must not be assumed.
Repository discovery should walk parent directories from the command's working
directory, recognize a valid repository marker, and fail clearly if none is
found.

The initial on-disk layout is planned to include:

```text
.git/
    HEAD
    config
    index
    objects/
        info/
        pack/
    refs/
        heads/
        tags/
```

Only loose object storage is in the initial object-format scope. `pack/` is
shown because packed objects are relevant to later remote operations; its
format and behavior are future work. Any `config` fields or index encoding
needed for Git interoperability must follow the relevant Git format rather
than an undocumented private serialization. A CommitVerse-specific extension
must be explicit and must not change the serialization of Git objects.

## Object database and object relationships

The object database is content-addressed: the object ID is the SHA-1 digest of
the canonical, uncompressed Git object bytes. The loose-object file contains
the zlib-compressed canonical bytes. The detailed byte format is specified in
[Git Object Format](./git-object-format.md).

The initial object model is:

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
success-shaped fallback.

## Index and staging

The index is the proposed boundary between a working tree and the next
committed tree. It represents the staged snapshot by repository-relative paths,
file modes, blob IDs, and the metadata needed to detect working-tree changes.
The exact index encoding, version policy, stat-cache behavior, and extension
support remain to be decided before implementation. For Git index
interoperability, use the documented Git index format; do not invent a
Git-object-compatible-looking but incompatible binary format.

`add` reads selected working-tree files, writes/reuses blobs, and updates the
index. Tree writing converts the index's staged paths into nested tree objects.
Removal and rename behavior should be explicit command behavior, not inferred
from missing files unless the user requests it.

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

Example `add` flow: select paths, validate that they are inside the worktree,
read file bytes and mode, write or reuse blobs, and update the index. Example
`commit` flow: write trees from the index, construct and write a commit
referencing the root tree and current parent, then advance the current branch
ref (or handle detached `HEAD` according to an explicitly defined policy).

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
repository operation. For multi-step mutations, define the order and recovery
behavior; use temporary files and atomic replacement where supported. Do not
claim crash consistency or concurrent-writer safety until tested.

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
