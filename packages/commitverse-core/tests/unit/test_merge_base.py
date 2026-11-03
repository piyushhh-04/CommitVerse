import pytest

from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.merge_base import MergeBaseError, find_merge_base, is_ancestor
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import write_tree


def test_find_merge_base_and_ancestor_relationships(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    identity = CommitIdentity("Test", "test@example.test", 1, 0)
    tree = write_tree(repository.objects_dir, [])

    def commit(parents, message):
        return write_commit(
            repository.objects_dir,
            Commit(tree, tuple(parents), identity, identity, message.encode()),
        )

    root = commit((), "root\n")
    left = commit((root,), "left\n")
    right = commit((root,), "right\n")
    merge = commit((left, right), "merge\n")

    assert find_merge_base(repository, left, right) == root
    assert is_ancestor(repository, root, merge)
    assert not is_ancestor(repository, left, right)


def test_find_merge_base_returns_none_for_unrelated_histories(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    identity = CommitIdentity("Test", "test@example.test", 1, 0)
    tree = write_tree(repository.objects_dir, [])

    def commit(message):
        return write_commit(
            repository.objects_dir,
            Commit(tree, (), identity, identity, message.encode()),
        )

    assert find_merge_base(repository, commit("left\n"), commit("right\n")) is None


def test_find_merge_base_detects_cycles(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    identity = CommitIdentity("Test", "test@example.test", 1, 0)
    tree = write_tree(repository.objects_dir, [])
    commit_id = write_commit(
        repository.objects_dir,
        Commit(tree, (), identity, identity, b"message\n"),
    )

    def cyclic(*_args):
        return Commit(tree, (commit_id,), identity, identity, b"cycle\n")

    monkeypatch.setattr("commitverse_core.merge_base.read_commit", cyclic)
    with pytest.raises(MergeBaseError, match="cyclic"):
        find_merge_base(repository, commit_id, commit_id)
