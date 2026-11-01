"""Serialize, parse, and build Git-compatible tree objects."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from commitverse_core.index import IndexEntry
from commitverse_core.objects.store import read_object, write_object

_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_TREE_MODE_TO_TYPE = {
    "100644": "blob",
    "100755": "blob",
    "120000": "blob",
    "40000": "tree",
}


class TreeError(ValueError):
    """Raised for invalid tree entries or malformed tree objects."""


@dataclass(frozen=True)
class TreeEntry:
    """One named entry in a Git tree payload."""

    mode: str
    name: bytes
    object_id: str


def _validate_entry(entry: TreeEntry) -> None:
    if not isinstance(entry, TreeEntry):
        raise TreeError("tree entries must be TreeEntry values")
    if entry.mode not in _TREE_MODE_TO_TYPE:
        raise TreeError(f"unsupported tree mode: {entry.mode!r}")
    if not isinstance(entry.name, bytes):
        raise TreeError("tree entry names must be bytes")
    if (
        not entry.name
        or b"\0" in entry.name
        or b"/" in entry.name
        or entry.name in (b".", b"..")
    ):
        raise TreeError(f"invalid tree entry name: {entry.name!r}")
    if (
        not isinstance(entry.object_id, str)
        or _OBJECT_ID_PATTERN.fullmatch(entry.object_id) is None
    ):
        raise TreeError("tree object IDs must be 40 lowercase hexadecimal characters")


def _sort_key(entry: TreeEntry) -> bytes:
    return entry.name + (b"/" if entry.mode == "40000" else b"")


def serialize_tree(entries: Iterable[TreeEntry]) -> bytes:
    """Serialize entries in Git tree order using raw 20-byte object IDs."""
    validated = list(entries)
    for entry in validated:
        _validate_entry(entry)
    names = [entry.name for entry in validated]
    if len(set(names)) != len(names):
        raise TreeError("tree entry names must be unique")

    validated.sort(key=_sort_key)
    return b"".join(
        entry.mode.encode("ascii")
        + b" "
        + entry.name
        + b"\0"
        + bytes.fromhex(entry.object_id)
        for entry in validated
    )


def parse_tree(payload: bytes) -> tuple[TreeEntry, ...]:
    """Parse and validate a tree payload without interpreting child objects."""
    if not isinstance(payload, bytes):
        raise TypeError("tree payload must be bytes")

    entries: list[TreeEntry] = []
    offset = 0
    while offset < len(payload):
        mode_end = payload.find(b" ", offset)
        if mode_end < 0:
            raise TreeError("tree entry is missing its mode separator")
        name_end = payload.find(b"\0", mode_end + 1)
        if name_end < 0:
            raise TreeError("tree entry is missing its NUL-terminated name")
        object_id_start = name_end + 1
        object_id_end = object_id_start + 20
        if object_id_end > len(payload):
            raise TreeError("tree entry has a truncated object ID")

        try:
            mode = payload[offset:mode_end].decode("ascii")
        except UnicodeDecodeError as error:
            raise TreeError("tree entry mode must be ASCII") from error
        entry = TreeEntry(
            mode=mode,
            name=payload[mode_end + 1 : name_end],
            object_id=payload[object_id_start:object_id_end].hex(),
        )
        _validate_entry(entry)
        entries.append(entry)
        offset = object_id_end

    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        raise TreeError("tree entry names must be unique")
    if entries != sorted(entries, key=_sort_key):
        raise TreeError("tree entries are not in Git tree order")
    return tuple(entries)


def read_tree(objects_dir: Path, object_id: str) -> tuple[TreeEntry, ...]:
    """Read a tree and verify each referenced object's expected type."""
    object_type, payload = read_object(objects_dir, object_id)
    if object_type != "tree":
        raise TreeError(f"object {object_id} is {object_type}, not a tree")
    entries = parse_tree(payload)
    for entry in entries:
        expected_type = _TREE_MODE_TO_TYPE[entry.mode]
        child_type, _ = read_object(objects_dir, entry.object_id)
        if child_type != expected_type:
            raise TreeError(
                f"tree entry {entry.name!r} references {child_type}, "
                f"expected {expected_type}"
            )
    return entries


def write_tree(objects_dir: Path, entries: Iterable[IndexEntry]) -> str:
    """Build nested tree objects from stage-zero index entries."""
    root: dict[bytes, object] = {}
    seen_paths: set[bytes] = set()
    for index_entry in entries:
        path = index_entry.path
        if not isinstance(path, bytes) or not path:
            raise TreeError("index paths must be nonempty bytes")
        parts = path.split(b"/")
        if any(part in (b"", b".", b"..") or b"\0" in part for part in parts):
            raise TreeError(f"invalid index path: {path!r}")
        if path in seen_paths:
            raise TreeError(f"duplicate index path: {path!r}")
        seen_paths.add(path)
        if index_entry.stage != 0:
            raise TreeError(f"cannot write a tree with unmerged path {path!r}")
        if index_entry.mode not in ("100644", "100755", "120000"):
            raise TreeError(f"unsupported index mode: {index_entry.mode!r}")
        child_type, _ = read_object(objects_dir, index_entry.object_id)
        if child_type != "blob":
            raise TreeError(
                f"index path {path!r} references {child_type}, expected blob"
            )

        node = root
        for part in parts[:-1]:
            existing = node.get(part)
            if isinstance(existing, TreeEntry):
                raise TreeError(f"file/directory path conflict at {path!r}")
            if existing is None:
                existing = {}
                node[part] = existing
            node = existing
        leaf = parts[-1]
        if leaf in node:
            raise TreeError(f"duplicate or conflicting index path: {path!r}")
        node[leaf] = TreeEntry(index_entry.mode, leaf, index_entry.object_id)

    def store_node(node: dict[bytes, object]) -> str:
        tree_entries: list[TreeEntry] = []
        for name, child in node.items():
            if isinstance(child, TreeEntry):
                tree_entries.append(child)
            else:
                tree_entries.append(TreeEntry("40000", name, store_node(child)))
        return write_object(objects_dir, "tree", serialize_tree(tree_entries))

    return store_node(root)
