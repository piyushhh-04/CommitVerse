import os

import pytest

from commitverse_core.clone import CloneError, clone_from_local
from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.config import read_repository_configuration
from commitverse_core.refs import (
    compare_and_swap_ref,
    read_head,
    read_ref,
)
from commitverse_core.repository import initialize_repository
from commitverse_core.status import get_status
from commitverse_core.trees import TreeEntry, serialize_tree, write_tree
from commitverse_core.objects import write_object


def _commit(repository, tree_id=None, parents=(), message=b"clone\n"):
    identity = CommitIdentity("Clone", "clone@example.test", 1_700_000_000, 0)
    if tree_id is None:
        tree_id = write_tree(repository.objects_dir, [])
    return write_commit(
        repository.objects_dir,
        Commit(tree_id, tuple(parents), identity, identity, message),
    )


def test_clone_bare_source_creates_clean_worktree_and_origin(tmp_path):
    source = initialize_repository(tmp_path / "source.git", bare=True)
    blob = write_object(source.objects_dir, "blob", b"hello\n")
    tree = write_object(
        source.objects_dir,
        "tree",
        serialize_tree([TreeEntry("100644", b"hello.txt", blob)]),
    )
    commit_id = _commit(source, tree)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    destination = tmp_path / "clone"

    result = clone_from_local(source.root, destination)
    clone = initialize_repository(destination)

    assert result.branch == "main"
    assert result.object_id == commit_id
    assert read_ref(clone, "refs/heads/main") == commit_id
    assert read_head(clone).symbolic_ref == "refs/heads/main"
    assert (destination / "hello.txt").read_bytes() == b"hello\n"
    status = get_status(clone)
    assert not status.staged and not status.unstaged and not status.untracked
    config = read_repository_configuration(clone)
    assert config.get("remote", "url", subsection="origin") == str(source.root)


def test_clone_supports_non_bare_source_and_explicit_branch(tmp_path):
    source = initialize_repository(tmp_path / "source")
    first = _commit(source, message=b"first\n")
    second = _commit(source, parents=(first,), message=b"second\n")
    compare_and_swap_ref(source, "refs/heads/main", None, first)
    compare_and_swap_ref(source, "refs/heads/feature", None, second)
    destination = tmp_path / "clone"

    result = clone_from_local(source.root, destination, branch="feature")

    assert result.branch == "feature"
    clone = initialize_repository(destination)
    assert read_ref(clone, "refs/heads/feature") == second
    assert read_head(clone).symbolic_ref == "refs/heads/feature"


def test_clone_rejects_existing_destination_without_modification(tmp_path):
    source = initialize_repository(tmp_path / "source.git", bare=True)
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "marker"
    marker.write_text("keep")

    with pytest.raises(CloneError, match="already exists"):
        clone_from_local(source.root, destination)

    assert marker.read_text() == "keep"


def test_clone_rejects_detached_or_missing_branch_without_publication(tmp_path):
    source = initialize_repository(tmp_path / "source.git", bare=True)
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    (source.git_dir / "HEAD").write_text(commit_id + "\n", encoding="ascii")

    with pytest.raises(CloneError, match="detached"):
        clone_from_local(source.root, tmp_path / "detached")

    with pytest.raises(CloneError, match="not advertised"):
        clone_from_local(source.root, tmp_path / "missing", branch="missing")


def test_clone_supports_explicit_branch_with_unborn_symbolic_head(tmp_path):
    source = initialize_repository(tmp_path / "source.git", bare=True)
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/feature", None, commit_id)
    (source.git_dir / "HEAD").write_text("ref: refs/heads/missing\n", encoding="ascii")

    result = clone_from_local(source.root, tmp_path / "clone", branch="feature")

    assert result.branch == "feature"


def test_clone_rejects_invalid_destination_parent(tmp_path):
    source = initialize_repository(tmp_path / "source.git", bare=True)
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)

    with pytest.raises(CloneError, match="destination parent"):
        clone_from_local(source.root, tmp_path / "missing" / "clone")
