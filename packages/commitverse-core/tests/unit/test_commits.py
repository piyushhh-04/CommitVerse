import pytest

from commitverse_core.commits import (
    Commit,
    CommitError,
    CommitIdentity,
    parse_commit,
    read_commit,
    serialize_commit,
    write_commit,
)
from commitverse_core.objects import hash_object, write_object


@pytest.fixture
def identity():
    return CommitIdentity("A Name", "a@example.test", 1_700_000_000, -330)


def test_root_commit_serialization_and_parse_preserve_unicode_message(identity):
    commit = Commit(
        "1" * 40,
        (),
        identity,
        identity,
        "First line\nsecond line \N{SNOWMAN}".encode("utf-8"),
    )

    payload = serialize_commit(commit)

    assert payload == (
        b"tree " + b"1" * 40 + b"\n"
        b"author A Name <a@example.test> 1700000000 -0530\n"
        b"committer A Name <a@example.test> 1700000000 -0530\n\n"
        + commit.message
    )
    assert parse_commit(payload) == commit


def test_commit_with_parents_preserves_order_and_message_without_final_newline(identity):
    commit = Commit(
        "1" * 40,
        ("2" * 40, "3" * 40),
        identity,
        identity,
        b"merge message",
    )

    assert parse_commit(serialize_commit(commit)) == commit
    assert serialize_commit(commit).split(b"\n")[:3] == [
        b"tree " + b"1" * 40,
        b"parent " + b"2" * 40,
        b"parent " + b"3" * 40,
    ]


@pytest.mark.parametrize(
    "commit",
    [
        Commit("A" * 40, (), CommitIdentity("n", "e", 1, 0), CommitIdentity("n", "e", 1, 0), b"m"),
        Commit("1" * 40, ("x" * 40,), CommitIdentity("n", "e", 1, 0), CommitIdentity("n", "e", 1, 0), b"m"),
        Commit("1" * 40, (), CommitIdentity("", "e", 1, 0), CommitIdentity("n", "e", 1, 0), b"m"),
        Commit("1" * 40, (), CommitIdentity("n", "e", 1, 1440), CommitIdentity("n", "e", 1, 0), b"m"),
        Commit("1" * 40, (), CommitIdentity("n", "e", 1, 0), CommitIdentity("n", "e", 1, 0), "m"),
    ],
)
def test_serializer_rejects_invalid_commit_fields(commit):
    with pytest.raises(CommitError):
        serialize_commit(commit)


@pytest.mark.parametrize(
    "payload",
    [
        b"parent " + b"1" * 40 + b"\n\nm",
        b"tree bad\n\nm",
        b"tree " + b"1" * 40 + b"\nauthor n <e> 1 +0000\n\nm",
        b"tree " + b"1" * 40 + b"\nauthor n <e> 1 +0000\ncommitter n <e> 1 +2460\n\nm",
        b"tree " + b"1" * 40 + b"\ncommitter n <e> 1 +0000\nauthor n <e> 1 +0000\n\nm",
        b"tree " + b"1" * 40 + b"\nauthor n <e> 1 +0000\ncommitter n <e> 1 +0000",
        b"tree " + b"1" * 40 + b"\nauthor n <e> 1 +0000\ncommitter n <e> 1 +0000\nextra x\n\nm",
    ],
)
def test_parser_rejects_malformed_commit_payloads(payload):
    with pytest.raises(CommitError):
        parse_commit(payload)


def test_parse_rejects_non_utf8_identity_and_invalid_timezone():
    prefix = b"tree " + b"1" * 40 + b"\nauthor "
    with pytest.raises(CommitError, match="UTF-8"):
        parse_commit(
            prefix
            + b"\xff <e> 1 +0000\ncommitter n <e> 1 +0000\n\nm"
        )
    with pytest.raises(CommitError, match="timezone"):
        parse_commit(
            prefix + b"n <e> 1 +2400\ncommitter n <e> 1 +0000\n\nm"
        )


def test_write_and_read_commit_validate_referenced_object_types(tmp_path, identity):
    objects_dir = tmp_path / "objects"
    tree_id = write_object(objects_dir, "tree", b"")
    parent_tree_id = write_object(objects_dir, "tree", b"")
    commit = Commit(
        tree_id, (parent_tree_id,), identity, identity, b"message\n"
    )

    with pytest.raises(CommitError, match="not a commit"):
        write_commit(objects_dir, commit)

    root = Commit(tree_id, (), identity, identity, b"root")
    object_id = write_commit(objects_dir, root)
    assert object_id == hash_object("commit", serialize_commit(root))
    assert read_commit(objects_dir, object_id) == root

    second_parent = write_commit(
        objects_dir,
        Commit(tree_id, (object_id,), identity, identity, b"second parent"),
    )
    merge = Commit(
        tree_id, (object_id, second_parent), identity, identity, b"merge"
    )
    merge_id = write_commit(objects_dir, merge)
    assert read_commit(objects_dir, merge_id) == merge


def test_write_commit_rejects_missing_tree(tmp_path, identity):
    with pytest.raises(FileNotFoundError):
        write_commit(
            tmp_path / "objects",
            Commit("1" * 40, (), identity, identity, b"message"),
        )
