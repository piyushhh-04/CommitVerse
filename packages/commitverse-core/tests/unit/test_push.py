import pytest

from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.fetch import TransferLimits
from commitverse_core.push import NonFastForwardError, PushError, push_to_local
from commitverse_core.refs import (
    ReferenceExpectationError,
    compare_and_swap_ref,
    read_head,
    read_ref,
)
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import write_tree


def _commit(repository, parents=(), message=b"commit\n"):
    identity = CommitIdentity("Push", "push@example.test", 1_700_000_000, 0)
    return write_commit(
        repository.objects_dir,
        Commit(
            write_tree(repository.objects_dir, []),
            tuple(parents),
            identity,
            identity,
            message,
        ),
    )


def test_push_creates_initial_branch_and_transfers_objects(tmp_path):
    source = initialize_repository(tmp_path / "source")
    first = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, first)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    result = push_to_local(source, destination.root, source_branch="main")

    assert result.status == "updated"
    assert result.published
    assert result.objects_transferred == 2
    assert read_ref(destination, "refs/heads/main") == first


def test_push_allows_fast_forward_and_explicit_mapping(tmp_path):
    source = initialize_repository(tmp_path / "source")
    first = _commit(source, message=b"first\n")
    second = _commit(source, parents=(first,), message=b"second\n")
    compare_and_swap_ref(source, "refs/heads/main", None, first)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    initial = push_to_local(
        source, destination.root, source_branch="main", destination_branch="release"
    )
    assert initial.destination_ref == "refs/heads/release"

    compare_and_swap_ref(source, "refs/heads/main", first, second)
    result = push_to_local(
        source, destination.root, source_branch="main", destination_branch="release"
    )
    assert result.objects_transferred == 1
    assert read_ref(destination, "refs/heads/release") == second


def test_push_rejects_non_fast_forward_without_modifying_destination(tmp_path):
    source = initialize_repository(tmp_path / "source")
    destination = initialize_repository(tmp_path / "destination.git", bare=True)
    remote_tip = _commit(destination, message=b"remote\n")
    source_tip = _commit(source, message=b"source\n")
    compare_and_swap_ref(destination, "refs/heads/main", None, remote_tip)
    compare_and_swap_ref(source, "refs/heads/main", None, source_tip)

    with pytest.raises(NonFastForwardError):
        push_to_local(source, destination.root, source_branch="main")

    assert read_ref(destination, "refs/heads/main") == remote_tip


def test_push_rejects_invalid_source_and_non_bare_destination(tmp_path):
    source = initialize_repository(tmp_path / "source")
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(PushError, match="cannot read source branch"):
        push_to_local(source, destination.root, source_branch="missing")

    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    with pytest.raises(PushError, match="destination must be a bare"):
        push_to_local(source, destination.root, source_branch="main")


def test_push_rejects_transfer_limit_before_publication(tmp_path):
    source = initialize_repository(tmp_path / "source")
    commit_id = _commit(source, message=b"limited")
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    with pytest.raises(PushError, match="cannot validate source closure"):
        push_to_local(
            source,
            destination.root,
            source_branch="main",
            limits=TransferLimits(max_objects_per_transfer=1),
        )
    assert not (destination.git_dir / "refs" / "heads" / "main").exists()


def test_push_reports_cas_conflict_without_overwriting_destination(tmp_path, monkeypatch):
    source = initialize_repository(tmp_path / "source")
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    def conflict(*args, **kwargs):
        raise ReferenceExpectationError("concurrent update")

    monkeypatch.setattr("commitverse_core.push.compare_and_swap_ref", conflict)
    result = push_to_local(source, destination.root, source_branch="main")

    assert result.status == "failed"
    assert not result.published
    assert not (destination.git_dir / "refs" / "heads" / "main").exists()


def test_push_does_not_change_source_head(tmp_path):
    source = initialize_repository(tmp_path / "source")
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)
    before = read_head(source)

    push_to_local(source, destination.root, source_branch="main")

    assert read_head(source) == before


def test_push_rejects_corrupted_source_before_destination_publication(tmp_path):
    source = initialize_repository(tmp_path / "source")
    commit_id = _commit(source)
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    object_path = source.objects_dir / commit_id[:2] / commit_id[2:]
    object_path.write_bytes(b"corrupt")
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    with pytest.raises(PushError, match="cannot validate source closure"):
        push_to_local(source, destination.root, source_branch="main")

    assert not (destination.git_dir / "refs" / "heads" / "main").exists()


def test_push_rejects_corrupted_existing_destination_history(tmp_path):
    source = initialize_repository(tmp_path / "source")
    destination = initialize_repository(tmp_path / "destination.git", bare=True)
    old_commit = _commit(source, message=b"old\n")
    compare_and_swap_ref(source, "refs/heads/main", None, old_commit)
    push_to_local(source, destination.root, source_branch="main")
    new_commit = _commit(source, parents=(old_commit,), message=b"new\n")
    compare_and_swap_ref(source, "refs/heads/main", old_commit, new_commit)
    object_path = destination.objects_dir / old_commit[:2] / old_commit[2:]
    object_path.write_bytes(b"corrupt")

    with pytest.raises(PushError, match="cannot validate destination closure"):
        push_to_local(source, destination.root, source_branch="main")
