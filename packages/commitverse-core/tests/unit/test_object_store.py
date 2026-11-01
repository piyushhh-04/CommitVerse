import zlib

import pytest

from commitverse_core.objects import hash_object, read_object, serialize_object, write_object


def _object_path(objects_dir, object_id):
    return objects_dir / object_id[:2] / object_id[2:]


def _write_raw_object(objects_dir, object_id, contents):
    object_path = _object_path(objects_dir, object_id)
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(zlib.compress(contents))
    return object_path


@pytest.mark.parametrize(
    ("object_type", "payload"),
    [
        ("blob", b"hello"),
        ("blob", b""),
        ("blob", b"\x00\xff\x00"),
        ("blob", "CommitVerse \N{SNOWMAN}".encode("utf-8")),
        ("tree", b"tree payload"),
        ("commit", b"commit payload"),
    ],
)
def test_write_and_read_object_round_trip(tmp_path, object_type, payload):
    objects_dir = tmp_path / "objects"

    object_id = write_object(objects_dir, object_type, payload)

    assert object_id == hash_object(object_type, payload)
    assert read_object(objects_dir, object_id) == (object_type, payload)


def test_object_is_stored_at_sha1_fanout_path(tmp_path):
    objects_dir = tmp_path / "objects"
    payload = b"fanout"

    object_id = write_object(objects_dir, "blob", payload)

    assert _object_path(objects_dir, object_id).is_file()
    assert _object_path(objects_dir, object_id).read_bytes() == zlib.compress(
        serialize_object("blob", payload)
    )


def test_stored_data_is_zlib_compressed_canonical_object(tmp_path):
    objects_dir = tmp_path / "objects"
    payload = b"\x00binary\npayload"
    object_id = write_object(objects_dir, "blob", payload)

    assert zlib.decompress(_object_path(objects_dir, object_id).read_bytes()) == (
        b"blob 15\0\x00binary\npayload"
    )


def test_writing_same_object_twice_is_idempotent(tmp_path):
    objects_dir = tmp_path / "objects"
    payload = b"same object"

    object_id = write_object(objects_dir, "blob", payload)
    stored_data = _object_path(objects_dir, object_id).read_bytes()
    second_object_id = write_object(objects_dir, "blob", payload)

    assert second_object_id == object_id
    assert _object_path(objects_dir, object_id).read_bytes() == stored_data
    assert list(objects_dir.glob("*/*")) == [_object_path(objects_dir, object_id)]


def test_read_missing_object_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_object(tmp_path / "objects", "0" * 40)


@pytest.mark.parametrize(
    "object_id",
    ["", "0" * 39, "0" * 41, "A" * 40, "g" + "0" * 39, None],
)
def test_read_rejects_invalid_object_id(tmp_path, object_id):
    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        read_object(tmp_path / "objects", object_id)


def test_read_rejects_corrupted_zlib_data(tmp_path):
    object_id = hash_object("blob", b"expected")
    object_path = _object_path(tmp_path / "objects", object_id)
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"not zlib data")

    with pytest.raises(ValueError, match="invalid zlib"):
        read_object(tmp_path / "objects", object_id)


def test_read_rejects_truncated_zlib_data(tmp_path):
    object_id = hash_object("blob", b"expected")
    compressed = zlib.compress(serialize_object("blob", b"expected"))
    _object_path(tmp_path / "objects", object_id).parent.mkdir(parents=True)
    _object_path(tmp_path / "objects", object_id).write_bytes(compressed[:-2])

    with pytest.raises(ValueError, match="truncated zlib"):
        read_object(tmp_path / "objects", object_id)


def test_read_rejects_trailing_compressed_data(tmp_path):
    object_id = hash_object("blob", b"expected")
    object_path = _write_raw_object(
        tmp_path / "objects", object_id, serialize_object("blob", b"expected")
    )
    object_path.write_bytes(object_path.read_bytes() + b"trailing")

    with pytest.raises(ValueError, match="trailing compressed"):
        read_object(tmp_path / "objects", object_id)


@pytest.mark.parametrize(
    "contents",
    [
        b"blob 1payload",
        b"blob \0x",
        b"blob 01\0x",
        b"blob 1  \0x",
        b"\xff 1\0x",
    ],
)
def test_read_rejects_malformed_object_headers(tmp_path, contents):
    object_id = hash_object("blob", b"expected")
    _write_raw_object(tmp_path / "objects", object_id, contents)

    with pytest.raises(ValueError, match="header|size|ASCII"):
        read_object(tmp_path / "objects", object_id)


def test_read_rejects_unsupported_stored_object_type(tmp_path):
    object_id = hash_object("blob", b"expected")
    _write_raw_object(tmp_path / "objects", object_id, b"tag 1\0x")

    with pytest.raises(ValueError, match="unsupported object type"):
        read_object(tmp_path / "objects", object_id)


def test_read_rejects_incorrect_declared_payload_size(tmp_path):
    object_id = hash_object("blob", b"expected")
    _write_raw_object(tmp_path / "objects", object_id, b"blob 9\0expected")

    with pytest.raises(ValueError, match="declares 9 payload bytes"):
        read_object(tmp_path / "objects", object_id)


def test_read_rejects_hash_mismatch(tmp_path):
    requested_id = hash_object("blob", b"expected")
    _write_raw_object(
        tmp_path / "objects",
        requested_id,
        serialize_object("blob", b"different"),
    )

    with pytest.raises(ValueError, match="does not match object ID"):
        read_object(tmp_path / "objects", requested_id)
