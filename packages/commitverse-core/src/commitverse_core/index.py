"""Read and write Git index version 2 files."""

import hashlib
import os
import re
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

_HEADER = b"DIRC"
_VERSION = 2
_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_TREE_EXTENSION = b"TREE"
_SUPPORTED_EXTENSIONS = {_TREE_EXTENSION}
_UINT32_MAX = (1 << 32) - 1
_PATH_LENGTH_MASK = 0x0FFF
_STAGE_MASK = 0x3000
_EXTENDED_FLAG = 0x4000
_ASSUME_VALID_FLAG = 0x8000


class IndexFormatError(ValueError):
    """Raised when an index is malformed or uses unsupported features."""


@dataclass(frozen=True)
class IndexStat:
    """The ten unsigned 32-bit stat fields stored in a v2 index entry."""

    ctime_seconds: int = 0
    ctime_nanoseconds: int = 0
    mtime_seconds: int = 0
    mtime_nanoseconds: int = 0
    device: int = 0
    inode: int = 0
    mode: int = 0
    uid: int = 0
    gid: int = 0
    size: int = 0

    def fields(self) -> tuple[int, ...]:
        return (
            self.ctime_seconds,
            self.ctime_nanoseconds,
            self.mtime_seconds,
            self.mtime_nanoseconds,
            self.device,
            self.inode,
            self.mode,
            self.uid,
            self.gid,
            self.size,
        )


@dataclass(frozen=True)
class IndexEntry:
    """A staged path, its cached filesystem metadata, and its object ID."""

    path: bytes
    object_id: str
    stat: IndexStat = IndexStat()
    stage: int = 0
    assume_valid: bool = False

    @property
    def mode(self) -> str:
        return f"{self.stat.mode:o}"


@dataclass(frozen=True)
class Index:
    """An ordered collection of entries and supported opaque extensions."""

    entries: tuple[IndexEntry, ...] = ()
    extensions: tuple[tuple[bytes, bytes], ...] = ()


def _validate_path(path: bytes) -> None:
    if (
        not isinstance(path, bytes)
        or not path
        or b"\0" in path
        or path.startswith(b"/")
        or any(part in (b"", b".", b"..") for part in path.split(b"/"))
    ):
        raise IndexFormatError(f"invalid index pathname: {path!r}")


def _entry_key(entry: IndexEntry) -> tuple[bytes, int]:
    return entry.path, entry.stage


def _validate_entry(entry: IndexEntry) -> None:
    _validate_path(entry.path)
    if (
        not isinstance(entry.object_id, str)
        or _OBJECT_ID_PATTERN.fullmatch(entry.object_id) is None
    ):
        raise IndexFormatError("index object IDs must be 40 lowercase hexadecimal characters")
    if type(entry.stage) is not int or entry.stage not in (0, 1, 2, 3):
        raise IndexFormatError(f"invalid index stage: {entry.stage!r}")
    if entry.mode not in ("100644", "100755", "120000"):
        raise IndexFormatError(f"unsupported index mode: {entry.mode!r}")
    if len(entry.stat.fields()) != 10 or any(
        type(value) is not int or value < 0 or value > _UINT32_MAX
        for value in entry.stat.fields()
    ):
        raise IndexFormatError("index stat fields must be unsigned 32-bit integers")


def _validate_stage_groups(entries: tuple[IndexEntry, ...]) -> None:
    stages_by_path: dict[bytes, set[int]] = {}
    for entry in entries:
        stages_by_path.setdefault(entry.path, set()).add(entry.stage)
    if any(0 in stages and len(stages) > 1 for stages in stages_by_path.values()):
        raise IndexFormatError("stage-zero and unmerged entries cannot share a pathname")


def serialize_index(index: Index) -> bytes:
    """Encode an index v2 payload and append its SHA-1 checksum."""
    entries = tuple(sorted(index.entries, key=_entry_key))
    for entry in entries:
        _validate_entry(entry)
    keys = [_entry_key(entry) for entry in entries]
    if len(set(keys)) != len(keys):
        raise IndexFormatError("duplicate index path and stage")
    _validate_stage_groups(entries)
    if len(entries) > _UINT32_MAX:
        raise IndexFormatError("index contains too many entries")

    body = bytearray(_HEADER + struct.pack(">II", _VERSION, len(entries)))
    for entry in entries:
        flags = min(len(entry.path), _PATH_LENGTH_MASK) | (entry.stage << 12)
        if entry.assume_valid:
            flags |= _ASSUME_VALID_FLAG
        start = len(body)
        body.extend(struct.pack(">10I", *entry.stat.fields()))
        body.extend(bytes.fromhex(entry.object_id))
        body.extend(struct.pack(">H", flags))
        body.extend(entry.path)
        body.append(0)
        body.extend(b"\0" * ((-(len(body) - start)) % 8))

    seen_extensions: set[bytes] = set()
    for signature, extension_data in index.extensions:
        if signature not in _SUPPORTED_EXTENSIONS:
            raise IndexFormatError(f"unsupported index extension {signature!r}")
        if signature in seen_extensions:
            raise IndexFormatError(f"duplicate index extension {signature!r}")
        if len(signature) != 4 or len(extension_data) > _UINT32_MAX:
            raise IndexFormatError("invalid index extension")
        seen_extensions.add(signature)
        body.extend(signature)
        body.extend(struct.pack(">I", len(extension_data)))
        body.extend(extension_data)

    return bytes(body) + hashlib.sha1(body).digest()


def parse_index(data: bytes) -> Index:
    """Validate and decode an index v2 file, including its checksum."""
    if not isinstance(data, bytes):
        raise TypeError("index contents must be bytes")
    if len(data) < 32:
        raise IndexFormatError("index is truncated")
    if data[:4] != _HEADER:
        raise IndexFormatError("index signature must be DIRC")
    version, entry_count = struct.unpack_from(">II", data, 4)
    if version != _VERSION:
        raise IndexFormatError(f"unsupported index version: {version}")
    if hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise IndexFormatError("index checksum mismatch")

    end = len(data) - 20
    offset = 12
    entries: list[IndexEntry] = []
    for _ in range(entry_count):
        start = offset
        if offset + 62 > end:
            raise IndexFormatError("index entry is truncated")
        stat_fields = struct.unpack_from(">10I", data, offset)
        offset += 40
        object_id = data[offset : offset + 20].hex()
        offset += 20
        flags = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        if flags & _EXTENDED_FLAG:
            raise IndexFormatError("extended index entry flags are unsupported in version 2")
        name_length = flags & _PATH_LENGTH_MASK
        terminator = data.find(b"\0", offset, end)
        if terminator < 0:
            raise IndexFormatError("index pathname is missing its NUL terminator")
        path = data[offset:terminator]
        if name_length < _PATH_LENGTH_MASK and len(path) != name_length:
            raise IndexFormatError("index pathname length does not match entry flags")
        entry_end = terminator + 1
        offset = start + ((entry_end - start + 7) & ~7)
        if offset > end or any(data[entry_end:offset]):
            raise IndexFormatError("index entry has invalid padding")

        entry = IndexEntry(
            path=path,
            object_id=object_id,
            stat=IndexStat(*stat_fields),
            stage=(flags & _STAGE_MASK) >> 12,
            assume_valid=bool(flags & _ASSUME_VALID_FLAG),
        )
        _validate_entry(entry)
        entries.append(entry)

    if entries != sorted(entries, key=_entry_key):
        raise IndexFormatError("index entries are not in Git pathname order")
    if len({_entry_key(entry) for entry in entries}) != len(entries):
        raise IndexFormatError("index contains duplicate path and stage entries")
    _validate_stage_groups(tuple(entries))

    extensions: list[tuple[bytes, bytes]] = []
    while offset < end:
        if offset + 8 > end:
            raise IndexFormatError("index extension header is truncated")
        signature = data[offset : offset + 4]
        extension_length = struct.unpack_from(">I", data, offset + 4)[0]
        offset += 8
        extension_end = offset + extension_length
        if extension_end > end:
            raise IndexFormatError(f"index extension {signature!r} is truncated")
        if signature not in _SUPPORTED_EXTENSIONS:
            raise IndexFormatError(f"unsupported index extension {signature!r}")
        if any(existing == signature for existing, _ in extensions):
            raise IndexFormatError(f"duplicate index extension {signature!r}")
        extensions.append((signature, data[offset:extension_end]))
        offset = extension_end

    return Index(tuple(entries), tuple(extensions))


def read_index(index_path: Path | str) -> Index:
    """Read an index, treating a missing file as an empty index."""
    path = Path(index_path)
    try:
        return parse_index(path.read_bytes())
    except FileNotFoundError:
        return Index()


def write_index(index_path: Path | str, index: Index) -> None:
    """Atomically replace an index file with a checksummed v2 encoding."""
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = serialize_index(index)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".index-", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
