import hashlib
import struct

import pytest

from commitverse_core import index as index_module
from commitverse_core.index import (
    Index,
    IndexEntry,
    IndexFormatError,
    IndexStat,
    parse_index,
    read_index,
    serialize_index,
    write_index,
)


def _entry(path=b"file", object_id="1" * 40, *, mode=0o100644, stage=0, **kwargs):
    return IndexEntry(
        path=path,
        object_id=object_id,
        stat=IndexStat(mode=mode, **kwargs),
        stage=stage,
    )


def test_empty_index_v2_has_dirc_header_and_valid_checksum():
    encoded = serialize_index(Index())

    assert encoded[:12] == b"DIRC" + struct.pack(">II", 2, 0)
    assert encoded[-20:] == hashlib.sha1(encoded[:-20]).digest()
    assert parse_index(encoded) == Index()


def test_index_round_trip_preserves_path_metadata_flags_and_stage():
    entries = (
        _entry(
            b"directory/file with space-\xc3\xa9",
            "a" * 40,
            mode=0o100755,
            stage=2,
            ctime_seconds=3,
            ctime_nanoseconds=4,
            mtime_seconds=5,
            mtime_nanoseconds=6,
            device=7,
            inode=8,
            uid=9,
            gid=10,
            size=11,
        ),
        _entry(b"second", "b" * 40, stage=1),
    )
    index = Index(entries)

    decoded = parse_index(serialize_index(index))

    assert decoded == Index(tuple(sorted(entries, key=lambda value: (value.path, value.stage))))
    assert decoded.entries[0].stat.ctime_seconds == 3
    assert decoded.entries[0].mode == "100755"


def test_index_round_trip_handles_long_paths_and_assume_valid_flag():
    path = b"directory/" + b"x" * 4100
    entry = IndexEntry(path, "c" * 40, IndexStat(mode=0o120000), assume_valid=True)

    assert parse_index(serialize_index(Index((entry,)))) == Index((entry,))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "truncated"),
        (b"BAD!" + b"\0" * 40, "DIRC"),
        (b"DIRC" + struct.pack(">II", 3, 0) + b"\0" * 20, "version"),
    ],
)
def test_index_rejects_bad_headers(data, message):
    with pytest.raises(IndexFormatError, match=message):
        parse_index(data)


def test_index_rejects_checksum_mismatch():
    encoded = bytearray(serialize_index(Index()))
    encoded[8] = 1

    with pytest.raises(IndexFormatError, match="checksum"):
        parse_index(bytes(encoded))


def test_index_rejects_invalid_path_and_duplicate_entries():
    with pytest.raises(IndexFormatError, match="pathname"):
        serialize_index(Index((_entry(b"a/../b"),)))
    with pytest.raises(IndexFormatError, match="duplicate"):
        serialize_index(Index((_entry(b"a"), _entry(b"a"))))
    with pytest.raises(IndexFormatError, match="stage-zero"):
        serialize_index(Index((_entry(b"a"), _entry(b"a", stage=2))))


def test_index_rejects_unsupported_extensions_and_extended_flags():
    unsupported = b"DIRC" + struct.pack(">II", 2, 0) + b"UNKN" + struct.pack(">I", 0)
    unsupported += hashlib.sha1(unsupported).digest()
    with pytest.raises(IndexFormatError, match="unsupported index extension"):
        parse_index(unsupported)

    encoded = bytearray(serialize_index(Index((_entry(),))))
    encoded[72:74] = struct.pack(">H", 0x4000)
    encoded[-20:] = hashlib.sha1(encoded[:-20]).digest()
    with pytest.raises(IndexFormatError, match="extended index entry flags"):
        parse_index(bytes(encoded))


def test_missing_index_reads_as_empty_and_writes_atomically(tmp_path):
    index_path = tmp_path / ".git" / "index"

    assert read_index(index_path) == Index()
    expected = Index((_entry(b"file"),))
    write_index(index_path, expected)

    assert parse_index(index_path.read_bytes()) == expected
    assert list(index_path.parent.iterdir()) == [index_path]


def test_write_index_keeps_previous_file_if_atomic_replace_fails(tmp_path, monkeypatch):
    index_path = tmp_path / ".git" / "index"
    previous = Index((_entry(b"old"),))
    write_index(index_path, previous)
    original_contents = index_path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("replacement failed")

    monkeypatch.setattr(index_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        write_index(index_path, Index((_entry(b"new"),)))

    assert index_path.read_bytes() == original_contents
    assert list(index_path.parent.iterdir()) == [index_path]


def test_tree_cache_extension_round_trips_as_opaque_data():
    index = Index((_entry(b"cached"),), ((b"TREE", b"opaque cache data"),))

    assert parse_index(serialize_index(index)) == index


def test_index_rejects_malformed_padding_and_file_directory_modes():
    encoded = bytearray(serialize_index(Index((_entry(b"file"),))))
    encoded[79] = 1
    encoded[-20:] = hashlib.sha1(encoded[:-20]).digest()
    with pytest.raises(IndexFormatError, match="padding"):
        parse_index(bytes(encoded))

    encoded = bytearray(serialize_index(Index((_entry(b"file"),))))
    encoded[36:40] = struct.pack(">I", 0o040000)
    encoded[-20:] = hashlib.sha1(encoded[:-20]).digest()
    with pytest.raises(IndexFormatError, match="mode"):
        parse_index(bytes(encoded))
