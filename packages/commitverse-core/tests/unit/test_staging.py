import os

import pytest

from commitverse_core.index import Index, IndexEntry, IndexStat, read_index, write_index
from commitverse_core.objects import read_object, write_object
from commitverse_core.repository import initialize_repository
from commitverse_core.staging import StagingError, add_paths
from commitverse_core.trees import read_tree, write_tree


def test_add_stages_files_recursively_with_modes_and_binary_bytes(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "folder").mkdir()
    (repository.root / "folder" / "space name.txt").write_bytes(b"first\x00\n")
    executable = repository.root / "run"
    executable.write_bytes(b"#!/bin/sh\n")
    executable.chmod(0o755)

    add_paths(repository, ["folder", "run"], cwd=repository.root)
    index = read_index(repository.git_dir / "index")
    assert [entry.path for entry in index.entries] == [
        b"folder/space name.txt",
        b"run",
    ]
    assert [entry.mode for entry in index.entries] == ["100644", "100755"]
    assert read_object(repository.objects_dir, index.entries[0].object_id) == (
        "blob",
        b"first\x00\n",
    )


def test_binary_filename_is_preserved_when_supported(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    binary_path = os.fsencode(repository.root) + b"/binary-\xff-name"
    try:
        descriptor = os.open(binary_path, os.O_CREAT | os.O_WRONLY, 0o644)
    except OSError as error:
        if error.errno in (22, 92):
            pytest.skip("filesystem does not support non-UTF-8 filenames")
        raise
    with os.fdopen(descriptor, "wb") as file:
        file.write(b"binary")

    add_paths(repository, [os.fsdecode(binary_path)], cwd=repository.root)

    assert read_index(repository.git_dir / "index").entries[0].path == b"binary-\xff-name"


def test_unicode_filename_is_preserved(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    filename = "snowman-\N{SNOWMAN}.txt"
    (repository.root / filename).write_text("unicode")

    add_paths(repository, [filename], cwd=repository.root)

    assert read_index(repository.git_dir / "index").entries[0].path == filename.encode()


def test_add_stages_symbolic_links_without_following_them(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    target = repository.root / "target"
    target.write_bytes(b"target content")
    link = repository.root / "link"
    link.symlink_to("target")

    add_paths(repository, ["link"], cwd=repository.root)

    entry = read_index(repository.git_dir / "index").entries[0]
    assert entry.path == b"link"
    assert entry.mode == "120000"
    assert read_object(repository.objects_dir, entry.object_id) == ("blob", b"target")


def test_add_all_stages_directory_symlinks_without_traversing_targets(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("outside")
    (repository.root / "external").symlink_to(outside, target_is_directory=True)

    add_paths(repository, all=True, cwd=repository.root)

    entries = read_index(repository.git_dir / "index").entries
    assert [entry.path for entry in entries] == [b"external"]
    assert entries[0].mode == "120000"
    assert read_object(repository.objects_dir, entries[0].object_id) == (
        "blob",
        os.fsencode(outside),
    )


def test_add_rejects_symlinked_root_gitignore(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    outside_ignore = tmp_path / "outside-ignore"
    outside_ignore.write_text("*.secret\n")
    (repository.root / ".gitignore").symlink_to(outside_ignore)

    with pytest.raises(StagingError, match="must be a regular file"):
        add_paths(repository, all=True, cwd=repository.root)


def test_add_all_stages_additions_modifications_and_deletions(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "modified.txt").write_bytes(b"before")
    (repository.root / "deleted.txt").write_bytes(b"remove")
    add_paths(repository, ["."], cwd=repository.root)
    (repository.root / "modified.txt").write_bytes(b"after")
    (repository.root / "deleted.txt").unlink()
    (repository.root / "new.txt").write_bytes(b"new")

    add_paths(repository, all=True, cwd=repository.root)
    entries = {entry.path: entry for entry in read_index(repository.git_dir / "index").entries}

    assert set(entries) == {b"modified.txt", b"new.txt"}
    assert read_object(repository.objects_dir, entries[b"modified.txt"].object_id) == (
        "blob",
        b"after",
    )
    assert read_object(repository.objects_dir, entries[b"new.txt"].object_id) == (
        "blob",
        b"new",
    )


def test_add_all_respects_root_gitignore_subset_and_negation(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / ".gitignore").write_text(
        ".venv/\n*.log\n.env.*\n!.env.example\n"
    )
    (repository.root / ".venv").mkdir()
    (repository.root / ".venv" / "package").write_text("ignored")
    (repository.root / "debug.log").write_text("ignored")
    (repository.root / ".env.secret").write_text("ignored")
    (repository.root / ".env.example").write_text("included")
    (repository.root / "source.py").write_text("included")

    add_paths(repository, all=True, cwd=repository.root)

    assert [entry.path for entry in read_index(repository.git_dir / "index").entries] == [
        b".env.example",
        b".gitignore",
        b"source.py",
    ]


def test_add_all_keeps_existing_tracked_path_even_if_now_ignored(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    tracked = repository.root / "generated.txt"
    tracked.write_text("tracked")
    add_paths(repository, ["generated.txt"], cwd=repository.root)
    (repository.root / ".gitignore").write_text("generated.txt\n")
    tracked.write_text("updated")

    add_paths(repository, all=True, cwd=repository.root)

    entry = next(
        item
        for item in read_index(repository.git_dir / "index").entries
        if item.path == b"generated.txt"
    )
    assert read_object(repository.objects_dir, entry.object_id) == ("blob", b"updated")


def test_add_removes_deleted_selected_path_and_rejects_missing_untracked_path(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "folder").mkdir()
    (repository.root / "folder" / "file").write_text("content")
    add_paths(repository, ["folder"], cwd=repository.root)
    (repository.root / "folder" / "file").unlink()

    add_paths(repository, ["folder"], cwd=repository.root)
    assert read_index(repository.git_dir / "index").entries == ()

    with pytest.raises(StagingError, match="does not exist"):
        add_paths(repository, ["missing"], cwd=repository.root)


def test_add_rejects_paths_outside_repository_and_git_directory(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.write_text("no")

    with pytest.raises(StagingError, match="outside"):
        add_paths(repository, [outside], cwd=repository.root)
    with pytest.raises(StagingError, match=".git"):
        add_paths(repository, [".git/config"], cwd=repository.root)


def test_add_rejects_paths_that_escape_through_parent_symlink(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_text("no")
    (repository.root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(StagingError, match="outside"):
        add_paths(repository, ["escape/file"], cwd=repository.root)


def test_selected_file_does_not_remove_other_staged_descendants(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "node").mkdir()
    (repository.root / "node" / "child").write_text("child")
    (repository.root / "node.txt").write_text("node")
    add_paths(repository, ["."], cwd=repository.root)

    add_paths(repository, ["node.txt"], cwd=repository.root)

    assert [entry.path for entry in read_index(repository.git_dir / "index").entries] == [
        b"node.txt",
        b"node/child",
    ]


def test_nested_repositories_are_not_recursively_staged(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    nested = initialize_repository(repository.root / "nested")
    (nested.root / "nested-file").write_text("content")
    (repository.root / "ordinary-file").write_text("ordinary")

    add_paths(repository, all=True, cwd=repository.root)

    assert [entry.path for entry in read_index(repository.git_dir / "index").entries] == [
        b"ordinary-file"
    ]
    with pytest.raises(StagingError, match="nested repositories"):
        add_paths(repository, ["nested"], cwd=repository.root)


def test_staging_changes_invalidate_tree_cache_extension(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    blob_id = write_object(repository.objects_dir, "blob", b"existing")
    write_index(
        repository.git_dir / "index",
        Index(
            (
                IndexEntry(b"existing", blob_id, IndexStat(mode=0o100644)),
            ),
            ((b"TREE", b"stale cache"),),
        ),
    )
    (repository.root / "new").write_text("new")

    add_paths(repository, ["new"], cwd=repository.root)

    assert read_index(repository.git_dir / "index").extensions == ()


def test_empty_directories_are_not_staged_and_unchanged_metadata_is_preserved(
    tmp_path,
):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "empty").mkdir()
    file_path = repository.root / "file"
    file_path.write_text("content")

    add_paths(repository, ["."], cwd=repository.root)
    first_index = read_index(repository.git_dir / "index")
    first_entry = first_index.entries[0]
    add_paths(repository, all=True, cwd=repository.root)
    second_entry = read_index(repository.git_dir / "index").entries[0]

    assert [entry.path for entry in first_index.entries] == [b"file"]
    assert second_entry == first_entry


def test_write_tree_from_staged_nested_paths_is_readable(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "nested").mkdir()
    (repository.root / "nested" / "file").write_bytes(b"payload")
    add_paths(repository, ["nested"], cwd=repository.root)

    root_id = write_tree(repository.objects_dir, read_index(repository.git_dir / "index").entries)

    assert read_tree(repository.objects_dir, root_id)[0].name == b"nested"
