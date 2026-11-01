import pytest

from commitverse_core.objects import hash_object, write_object
from commitverse_core.trees import TreeEntry, TreeError, parse_tree, read_tree, serialize_tree, write_tree


def test_empty_tree_has_git_object_id():
    assert serialize_tree([]) == b""
    assert hash_object("tree", b"") == "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    assert parse_tree(b"") == ()


def test_tree_serialization_uses_raw_object_ids_and_git_sort_order():
    file_id = "1" * 40
    directory_id = "2" * 40
    entries = [
        TreeEntry("40000", b"foo", directory_id),
        TreeEntry("100644", b"foo.bar", file_id),
        TreeEntry("100755", b"run", file_id),
    ]

    payload = serialize_tree(entries)

    assert payload == (
        b"100644 foo.bar\0"
        + bytes.fromhex(file_id)
        + b"40000 foo\0"
        + bytes.fromhex(directory_id)
        + b"100755 run\0"
        + bytes.fromhex(file_id)
    )
    assert parse_tree(payload) == (
        TreeEntry("100644", b"foo.bar", file_id),
        TreeEntry("40000", b"foo", directory_id),
        TreeEntry("100755", b"run", file_id),
    )


@pytest.mark.parametrize(
    "entry",
    [
        TreeEntry("100664", b"file", "1" * 40),
        TreeEntry("100644", b"", "1" * 40),
        TreeEntry("100644", b"bad/name", "1" * 40),
        TreeEntry("100644", b"bad\0name", "1" * 40),
        TreeEntry("100644", b"file", "A" * 40),
    ],
)
def test_tree_serializer_rejects_invalid_entries(entry):
    with pytest.raises(TreeError):
        serialize_tree([entry])


@pytest.mark.parametrize(
    "payload",
    [
        b"100644-file\0" + b"\x00" * 20,
        b"100644 file",
        b"100644 file\0short",
        b"100664 file\0" + b"\x00" * 20,
        b"100644 bad/name\0" + b"\x00" * 20,
    ],
)
def test_tree_parser_rejects_malformed_entries(payload):
    with pytest.raises(TreeError):
        parse_tree(payload)


def test_tree_parser_rejects_unsorted_and_duplicate_entries():
    first = TreeEntry("100644", b"z", "1" * 40)
    second = TreeEntry("100644", b"a", "2" * 40)
    with pytest.raises(TreeError, match="order"):
        parse_tree(
            b"100644 z\0" + bytes.fromhex(first.object_id)
            + b"100644 a\0" + bytes.fromhex(second.object_id)
        )
    with pytest.raises(TreeError, match="unique"):
        serialize_tree([first, first])


def test_read_tree_validates_referenced_object_types(tmp_path):
    objects_dir = tmp_path / "objects"
    blob_id = write_object(objects_dir, "blob", b"content")
    tree_id = write_object(
        objects_dir, "tree", serialize_tree([TreeEntry("100644", b"file", blob_id)])
    )

    assert read_tree(objects_dir, tree_id) == (
        TreeEntry("100644", b"file", blob_id),
    )
    bad_tree = write_object(
        objects_dir, "tree", serialize_tree([TreeEntry("40000", b"sub", blob_id)])
    )
    with pytest.raises(TreeError, match="expected tree"):
        read_tree(objects_dir, bad_tree)


def test_write_tree_builds_nested_directories_and_empty_tree(tmp_path):
    objects_dir = tmp_path / "objects"
    file_id = write_object(objects_dir, "blob", b"file")
    nested_id = write_object(objects_dir, "blob", b"nested")
    entries = [
        _index_entry(b"dir/nested.txt", nested_id),
        _index_entry(b"root.txt", file_id, "100755"),
    ]

    root_id = write_tree(objects_dir, entries)
    root_entries = read_tree(objects_dir, root_id)

    assert root_entries == (
        TreeEntry("40000", b"dir", hash_object(
            "tree",
            serialize_tree([TreeEntry("100644", b"nested.txt", nested_id)]),
        )),
        TreeEntry("100755", b"root.txt", file_id),
    )
    assert read_tree(objects_dir, root_entries[0].object_id) == (
        TreeEntry("100644", b"nested.txt", nested_id),
    )
    assert write_tree(objects_dir, []) == hash_object("tree", b"")


def test_write_tree_rejects_conflicting_paths_and_unmerged_entries(tmp_path):
    objects_dir = tmp_path / "objects"
    blob_id = write_object(objects_dir, "blob", b"x")

    with pytest.raises(TreeError, match="conflict"):
        write_tree(objects_dir, [_index_entry(b"a", blob_id), _index_entry(b"a/b", blob_id)])
    with pytest.raises(TreeError, match="unmerged"):
        write_tree(objects_dir, [_index_entry(b"a", blob_id, stage=2)])


def test_tree_names_are_raw_bytes(tmp_path):
    objects_dir = tmp_path / "objects"
    blob_id = write_object(objects_dir, "blob", b"binary name")
    name = b"invalid-\xff-name"
    tree_id = write_tree(objects_dir, [_index_entry(name, blob_id)])

    assert read_tree(objects_dir, tree_id) == (
        TreeEntry("100644", name, blob_id),
    )


def _index_entry(path, object_id, mode="100644", stage=0):
    from commitverse_core.index import IndexEntry, IndexStat

    return IndexEntry(
        path=path,
        object_id=object_id,
        stat=IndexStat(mode=int(mode, 8)),
        stage=stage,
    )
