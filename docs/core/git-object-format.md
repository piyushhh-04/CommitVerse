# Git Object Format

## Status and compatibility scope

This document defines CommitVerse Core's initial object-serialization and
storage target: SHA-1 loose objects containing blob, tree, and commit payloads.
Canonical serialization, hashing, loose-object storage, and envelope integrity
validation are implemented and covered by unit tests. Git-compatible tree
serialization/parsing and index version 2 encoding/decoding are also
implemented. External Git compatibility tests verify Git reads objects, trees,
and indexes written by CommitVerse; CommitVerse reads Git-written objects and
indexes; and both implementations produce the same tree IDs.

Compatibility evidence is limited to the tested loose-object, tree, and index
operations. It does not claim complete Git compatibility or a complete Git
replacement.

Object serialization is independent of the index, refs, CLI, Hub metadata, and
transport. This document covers loose objects, trees, and the separate index
file format; packfiles, alternate object databases, SHA-256 repositories, and
other Git extensions are out of scope.

## Object ID and canonical bytes

An object ID is the lowercase 40-character hexadecimal encoding of the
20-byte SHA-1 digest of the complete, **uncompressed** canonical object bytes.
For a payload of `N` bytes and type `T`, construct:

```text
ASCII(T) + b" " + ASCII(decimal N) + b"\0" + payload
```

Equivalently, the header is `<type> <size>\0` and the payload follows
immediately. The size is the number of payload bytes, not characters. Hash the
header and payload together:

```text
object_id = lowercase_hex(SHA1(canonical_object_bytes))
```

For example, the canonical bytes for a blob with payload `hello\n` are:

```text
blob 6\0hello\n
```

The NUL shown here represents one zero byte. It is not the two printable
characters `\` and `0`.

The supported initial type names are the ASCII strings `blob`, `tree`, and
`commit`. Loose-object reads require a supported type, a canonical nonnegative
decimal size, the NUL header terminator, and exactly the declared number of
payload bytes. The payload itself may contain NUL bytes. Never hash the
compressed representation or only the payload. Tree payload serialization and
parsing are implemented below. Commit payload serialization/parsing as
structured Git objects is not implemented; storage accepts and returns commit
payload bytes without interpreting them.

## Loose-object storage

Compress the complete canonical bytes with the zlib format. Given a 40-digit
object ID, place the compressed bytes at:

```text
<repository>/.git/objects/<first-two-hex-digits>/<remaining-38-hex-digits>
```

The two-character fan-out directory is created as needed. The path uses the
hexadecimal ID, while the content remains the zlib-compressed canonical bytes.
Compression level does not change the object ID; readers must decompress the
whole stream and validate the canonical content.

Writing should compute the ID from canonical bytes, write the compressed data
without exposing a partially written loose object, and avoid replacing a valid
object with different content. Reading by ID should validate the ID syntax,
read and decompress the file, parse the header, verify the payload size, and
recompute SHA-1 over the exact canonical bytes. A mismatch, invalid stream,
truncated data, invalid header, or unexpected trailing data must produce a
corruption error. A corrupt object must never be returned as valid.

The current reader materializes the compressed input and the complete
decompressed object in memory. It deliberately imposes no arbitrary object-size
limit. Before reading objects from any future untrusted remote source, assess
streaming or other resource-aware decompression and appropriate memory and CPU
protections.

## Blob serialization

A blob payload is the file's bytes without a filename, mode, path, or text
encoding conversion. Its canonical form is:

```text
blob <payload-byte-length>\0<payload-bytes>
```

Binary files and empty files are valid. Identical payload bytes produce the
same blob ID regardless of path.

## Tree serialization

A tree payload is a concatenation of entries. Each entry has this exact layout:

```text
<mode-as-ASCII> SP <filename-bytes> NUL <20 raw object-ID bytes>
```

`SP` is one ASCII space; `NUL` is one zero byte. The object ID is the raw
20-byte SHA-1 value, **not** its 40-byte hexadecimal text. The next entry, if
any, begins immediately after those 20 bytes. A tree has no entry count or
newline delimiter.

Common Git tree mode spellings in the payload are `100644` (regular file),
`100755` (executable file), `120000` (symbolic link), and `40000` (directory).
Directory entries reference tree objects; regular-file and symlink entries
reference blob objects. A gitlink mode (`160000`) references a commit and
requires explicit submodule behavior; it is not part of the initial feature
promise.

Names are byte sequences, not necessarily UTF-8. A valid tree entry name cannot
contain NUL or `/`; the containing tree gives it its directory context. Entries
must be serialized in Git tree order, including Git's directory ordering rule
(a directory name sorts as though followed by `/`). Implementations must not
sort by locale or decoded Unicode text.

The canonical tree object is the ordinary object header for type `tree` and
payload byte length followed by this exact payload. Its SHA-1 is calculated
over header plus payload. The child IDs in the payload remain raw 20-byte
values; only external displays and text fields encode IDs as hexadecimal.
The tree implementation validates supported modes, entry boundaries, unique
names, Git ordering, object IDs, and referenced object types when reading a
tree from the object database. Tree construction from index entries recursively
writes directory trees and rejects unmerged or conflicting paths. Gitlinks and
submodules are not supported.

## Index v2 file format

The index is repository metadata, not a Git object. The initial implementation
supports Git index version 2 and uses big-endian integers:

```text
"DIRC" | uint32 version (= 2) | uint32 entry count
entry[0] ... entry[n-1]
optional supported extensions
20-byte SHA-1 checksum
```

Each entry contains ten unsigned 32-bit stat fields (ctime seconds/nanoseconds,
mtime seconds/nanoseconds, device, inode, mode, uid, gid, and size), a raw
20-byte object ID, a 16-bit flags field, pathname bytes, a NUL terminator, and
zero padding so the entry size is a multiple of eight bytes. The low 12 flag
bits store pathname length (saturated at `0xFFF`); bits 12-13 store merge
stage; bit 15 is the assume-valid flag. Extended flags are rejected. Entries
are sorted by raw pathname bytes and stage; stage values 1-3 are preserved,
but tree writing rejects unmerged entries.

The final checksum is SHA-1 over all preceding index bytes. Writes use a
temporary file and atomic replacement. Existing stat metadata and entry flags
are preserved by decoding and re-encoding; staging updates metadata for
changed entries. A missing index is treated as empty.

Only the `TREE` cache-tree extension is recognized and preserved when entries
are unchanged. It is dropped when staging changes entries because cached tree
data may be stale. Other extensions (including split-index, resolve-undo,
untracked-cache, and filesystem-monitor data), extended entry flags, and index
versions other than 2 are explicitly unsupported and rejected rather than
silently rewritten.

## Commit serialization

A commit payload is a sequence of newline-terminated textual headers, one blank
line, and the message bytes. The initial supported header sequence is:

```text
tree <40-hex-root-tree-id>\n
parent <40-hex-parent-commit-id>\n     # zero or more, in parent order
author <identity> <unix-timestamp> <±HHMM-timezone>\n
committer <identity> <unix-timestamp> <±HHMM-timezone>\n
\n
<message-bytes>
```

The `tree` header is required and names the root tree. A root commit has no
`parent` line. A merge commit has multiple `parent` lines. Commit header IDs
are lowercase hexadecimal text; unlike tree entry IDs, these are not raw
binary bytes. The blank line separates headers from the message. The commit
object header wraps the entire commit payload as type `commit` with its exact
byte size.

Identity and timestamp generation/configuration, message encoding policy,
optional headers (for example encoding or signatures), and preservation of
unknown headers need explicit implementation decisions. Do not invent a
different header order or delimiter and call it Git-compatible. Parsers should
preserve payload bytes and reject malformed required fields rather than
silently manufacturing defaults.

## Reading and integrity verification

For each read by object ID:

1. Validate that the requested ID is exactly 40 hexadecimal digits for the
   initial SHA-1 format.
2. Resolve its fan-out path under this repository's object directory.
3. Read and zlib-decompress the loose object; report missing and corrupt data
   distinctly.
4. Split at the first NUL byte; parse the ASCII type and decimal size.
5. Require a supported type and require the payload byte length to equal the
   declared size.
6. Recompute SHA-1 over the original uncompressed header and payload, and
   require its hexadecimal ID to equal the requested ID.
7. Type-specific payload parsing is outside the current object-store
   implementation. A future tree parser must consume each entry's
   NUL-delimited name and exactly 20 following ID bytes; never decode those
   bytes as hexadecimal text.

An object whose path and content disagree is corruption, not an alternate
object. Integrity verification applies on reads as well as writes; the object
store must not trust a filename alone.
