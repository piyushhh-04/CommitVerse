import pytest

from commitverse_core import history
from commitverse_core.commits import Commit, CommitIdentity, read_commit, write_commit
from commitverse_core.history import HistoryError, format_commit_date, walk_history
from commitverse_core.repository import initialize_repository
from commitverse_core.refs import write_ref
from commitverse_core.trees import write_tree


@pytest.fixture
def history_graph(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    tree_id = write_tree(repository.objects_dir, [])
    identity = CommitIdentity("History User", "history@example.test", 1_700_000_000, 330)
    root = write_commit(
        repository.objects_dir,
        Commit(tree_id, (), identity, identity, "root \N{SNOWMAN}\n".encode()),
    )
    first = write_commit(
        repository.objects_dir,
        Commit(tree_id, (root,), identity, identity, b"first\n"),
    )
    second = write_commit(
        repository.objects_dir,
        Commit(tree_id, (root,), identity, identity, b"second\n"),
    )
    merge = write_commit(
        repository.objects_dir,
        Commit(tree_id, (first, second), identity, identity, b"merge\n"),
    )
    write_ref(repository, "refs/heads/main", merge)
    return repository, root, first, second, merge


def test_history_walks_all_parents_in_order_and_deduplicates_ancestors(history_graph):
    repository, root, first, second, merge = history_graph

    results = list(walk_history(repository))

    assert [object_id for object_id, _ in results] == [
        merge,
        first,
        root,
        second,
    ]
    assert results[0][1].parent_ids == (first, second)
    assert format_commit_date(results[0][1]) == "2023-11-15 03:43:20 +0530"


def test_history_is_empty_for_unborn_head(tmp_path):
    repository = initialize_repository(tmp_path / "repo")

    assert list(walk_history(repository)) == []


def test_history_reports_cycles(history_graph, monkeypatch):
    repository, _, _, _, merge = history_graph
    identity = read_commit(repository.objects_dir, merge).author
    cyclic = Commit("1" * 40, (merge,), identity, identity, b"cycle")
    monkeypatch.setattr(history, "read_commit", lambda _objects, _oid: cyclic)

    with pytest.raises(HistoryError, match="cyclic"):
        list(walk_history(repository))


def test_history_reports_missing_or_invalid_commit_objects(history_graph, monkeypatch):
    repository, _, _, _, _ = history_graph
    monkeypatch.setattr(
        history,
        "read_commit",
        lambda *_args: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    with pytest.raises(HistoryError, match="cannot read commit"):
        list(walk_history(repository))


def test_format_commit_date_rejects_unrepresentable_timestamp():
    identity = CommitIdentity("n", "e", 10**30, 0)
    commit = Commit("1" * 40, (), identity, identity, b"")

    with pytest.raises(HistoryError, match="outside the supported"):
        format_commit_date(commit)
