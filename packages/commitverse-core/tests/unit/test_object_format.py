import pytest

from commitverse_core.objects import hash_object, serialize_object


def test_serialize_simple_blob():
    assert serialize_object("blob", b"hello") == b"blob 5\0hello"


@pytest.mark.parametrize("object_type", ["blob", "tree", "commit"])
def test_supported_object_types_serialize(object_type):
    assert serialize_object(object_type, b"x") == f"{object_type} 1\0".encode() + b"x"


def test_empty_blob_has_known_git_object_id():
    assert serialize_object("blob", b"") == b"blob 0\0"
    assert hash_object("blob", b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_newline_blob_has_git_object_id():
    payload = b"hello world\n"

    assert serialize_object("blob", payload) == b"blob 12\0hello world\n"
    assert hash_object("blob", payload) == "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"


def test_binary_blob_preserves_null_bytes():
    payload = b"\x00\xff\x00"

    assert serialize_object("blob", payload) == b"blob 3\0\x00\xff\x00"


def test_utf8_payload_length_counts_bytes():
    payload = "é".encode("utf-8")

    assert serialize_object("blob", payload) == b"blob 2\0\xc3\xa9"


def test_unsupported_object_type_is_rejected():
    with pytest.raises(ValueError, match="unsupported object type"):
        serialize_object("tag", b"payload")


@pytest.mark.parametrize("payload", ["text", bytearray(b"bytes"), None])
def test_non_bytes_payload_is_rejected(payload):
    with pytest.raises(TypeError, match="payload must be bytes"):
        serialize_object("blob", payload)


def test_different_payloads_produce_different_hashes():
    assert hash_object("blob", b"first") != hash_object("blob", b"second")


def test_hash_is_lowercase_40_character_hex():
    object_id = hash_object("blob", b"hello")

    assert len(object_id) == 40
    assert object_id == object_id.lower()
    assert all(character in "0123456789abcdef" for character in object_id)
