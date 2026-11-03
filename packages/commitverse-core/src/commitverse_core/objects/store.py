"""Read and write Git-compatible zlib-compressed loose objects."""

import os
import re
import stat
import tempfile
import zlib
from pathlib import Path

from commitverse_core.objects.format import hash_object, serialize_object

_SUPPORTED_OBJECT_TYPES = ("blob", "tree", "commit")
_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


class ObjectResourceLimitError(ValueError):
    """Raised when bounded object reading exceeds a configured limit."""


def write_object(objects_dir: Path, object_type: str, payload: bytes) -> str:
    """Write a canonical object atomically and return its SHA-1 object ID."""
    canonical = serialize_object(object_type, payload)
    object_id = hash_object(object_type, payload)
    destination = objects_dir / object_id[:2] / object_id[2:]
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".tmp-", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(zlib.compress(canonical))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            existing_type, existing_payload = read_object(objects_dir, object_id)
            if (existing_type, existing_payload) != (object_type, payload):
                raise ValueError(f"existing object {object_id} has different content")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return object_id


def read_object(objects_dir: Path, object_id: str) -> tuple[str, bytes]:
    """Read and verify a loose object by its lowercase SHA-1 ID."""
    if not isinstance(object_id, str) or _OBJECT_ID_PATTERN.fullmatch(object_id) is None:
        raise ValueError("object ID must be 40 lowercase hexadecimal characters")

    object_path = objects_dir / object_id[:2] / object_id[2:]
    compressed = object_path.read_bytes()
    decompressor = zlib.decompressobj()
    try:
        canonical = decompressor.decompress(compressed) + decompressor.flush()
    except zlib.error as error:
        raise ValueError("object contains invalid zlib data") from error

    if not decompressor.eof:
        raise ValueError("object contains truncated zlib data")
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("object contains trailing compressed data")

    header, separator, payload = canonical.partition(b"\0")
    if not separator:
        raise ValueError("object header is missing its NUL terminator")

    header_parts = header.split(b" ")
    if len(header_parts) != 2:
        raise ValueError("object header must contain a type and decimal size")

    object_type_bytes, size_bytes = header_parts
    try:
        object_type = object_type_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("object type must be ASCII") from error

    if object_type not in _SUPPORTED_OBJECT_TYPES:
        raise ValueError(f"unsupported object type: {object_type!r}")
    if (
        not size_bytes
        or any(byte < ord("0") or byte > ord("9") for byte in size_bytes)
        or (len(size_bytes) > 1 and size_bytes.startswith(b"0"))
    ):
        raise ValueError("object size must be a canonical nonnegative decimal")

    declared_size = int(size_bytes)
    if len(payload) != declared_size:
        raise ValueError(
            f"object declares {declared_size} payload bytes but contains {len(payload)}"
        )
    if hash_object(object_type, payload) != object_id:
        raise ValueError(f"object content does not match object ID {object_id}")

    return object_type, payload


def read_object_bounded(
    objects_dir: Path,
    object_id: str,
    *,
    max_compressed_size: int,
    max_decompressed_size: int,
) -> tuple[str, bytes, int]:
    """Read and verify a loose object while bounding compressed and cleartext data."""
    if not isinstance(object_id, str) or _OBJECT_ID_PATTERN.fullmatch(object_id) is None:
        raise ValueError("object ID must be 40 lowercase hexadecimal characters")
    if max_compressed_size < 0 or max_decompressed_size < 0:
        raise ValueError("object resource limits must be nonnegative")
    object_path = objects_dir / object_id[:2] / object_id[2:]
    try:
        metadata = object_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"object path is not a regular file: {object_id}")
        compressed_size = object_path.stat().st_size
        if compressed_size > max_compressed_size:
            raise ObjectResourceLimitError(
                f"compressed object exceeds {max_compressed_size} bytes: {object_id}"
            )
        compressed = object_path.read_bytes()
    except ObjectResourceLimitError:
        raise
    except OSError:
        raise

    decompressor = zlib.decompressobj()
    try:
        canonical = decompressor.decompress(compressed, max_decompressed_size + 1)
        if len(canonical) > max_decompressed_size:
            raise ObjectResourceLimitError(
                f"decompressed object exceeds {max_decompressed_size} bytes: {object_id}"
            )
        remaining = max_decompressed_size - len(canonical)
        canonical += decompressor.flush(remaining + 1)
        if len(canonical) > max_decompressed_size:
            raise ObjectResourceLimitError(
                f"decompressed object exceeds {max_decompressed_size} bytes: {object_id}"
            )
    except zlib.error as error:
        raise ValueError("object contains invalid zlib data") from error

    if not decompressor.eof:
        raise ValueError("object contains truncated zlib data")
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("object contains trailing compressed data")

    header, separator, payload = canonical.partition(b"\0")
    if not separator:
        raise ValueError("object header is missing its NUL terminator")
    header_parts = header.split(b" ")
    if len(header_parts) != 2:
        raise ValueError("object header must contain a type and decimal size")
    object_type_bytes, size_bytes = header_parts
    try:
        object_type = object_type_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("object type must be ASCII") from error
    if object_type not in _SUPPORTED_OBJECT_TYPES:
        raise ValueError(f"unsupported object type: {object_type!r}")
    if (
        not size_bytes
        or any(byte < ord("0") or byte > ord("9") for byte in size_bytes)
        or (len(size_bytes) > 1 and size_bytes.startswith(b"0"))
    ):
        raise ValueError("object size must be a canonical nonnegative decimal")
    declared_size = int(size_bytes)
    if len(payload) != declared_size:
        raise ValueError(
            f"object declares {declared_size} payload bytes but contains {len(payload)}"
        )
    if hash_object(object_type, payload) != object_id:
        raise ValueError(f"object content does not match object ID {object_id}")
    return object_type, payload, compressed_size
