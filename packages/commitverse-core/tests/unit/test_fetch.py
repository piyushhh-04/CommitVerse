import pytest

from commitverse_core.commits import (
    Commit,
    CommitIdentity,
    serialize_commit,
    write_commit,
)
from commitverse_core.fetch import FetchError, TransferLimits, fetch_from_local
from commitverse_core.objects import write_object
from commitverse_core.refs import (
    ReferenceExpectationError,
    ReferenceNotFoundError,
    compare_and_swap_ref,
    read_ref,
)
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import TreeEntry, serialize_tree, write_tree


def _commit(repository, parents=(), message=b"commit\n"):
    identity = CommitIdentity("Fetch", "fetch@example.test", 1_700_000_000, 0)
    return write_commit(
        repository.objects_dir,
        Commit(write_tree(repository.objects_dir, []), tuple(parents), identity, identity, message),
    )


def test_fetch_branch_transfers_closure_and_remote_tracking_ref(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    first = _commit(remote, message=b"first\n")
    second = _commit(remote, parents=(first,), message=b"second\n")
    compare_and_swap_ref(remote, "refs/heads/main", None, second)
    destination = initialize_repository(tmp_path / "destination")

    result = fetch_from_local(destination, remote.root, branches=["main"])

    assert result.objects_transferred == 3
    assert result.references[0].destination_ref == "refs/remotes/origin/main"
    assert read_ref(destination, "refs/remotes/origin/main") == second


def test_fetch_multiple_branches_is_deterministic_and_idempotent(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(remote)
    compare_and_swap_ref(remote, "refs/heads/zeta", None, commit_id)
    compare_and_swap_ref(remote, "refs/heads/alpha", None, commit_id)
    destination = initialize_repository(tmp_path / "destination", bare=True)

    first = fetch_from_local(destination, remote.root, all_branches=True)
    second = fetch_from_local(destination, remote.root, all_branches=True)

    assert [item.source_ref for item in first.references] == [
        "refs/heads/alpha",
        "refs/heads/zeta",
    ]
    assert second.objects_transferred == 0


def test_fetch_supports_explicit_mapping_and_non_bare_remote(tmp_path):
    remote = initialize_repository(tmp_path / "remote")
    commit_id = _commit(remote)
    compare_and_swap_ref(remote, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination", bare=True)

    result = fetch_from_local(
        destination,
        remote.root,
        ref_mapping={"refs/heads/main": "refs/heads/imported"},
    )

    assert result.references[0].destination_ref == "refs/heads/imported"
    assert read_ref(destination, "refs/heads/imported") == commit_id


def test_fetch_transfers_nested_tree_and_blob_closure(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    blob_id = write_object(remote.objects_dir, "blob", b"nested content")
    nested_id = write_object(
        remote.objects_dir,
        "tree",
        serialize_tree([TreeEntry("100644", b"file.txt", blob_id)]),
    )
    root_id = write_object(
        remote.objects_dir,
        "tree",
        serialize_tree([TreeEntry("40000", b"nested", nested_id)]),
    )
    identity = CommitIdentity("Fetch", "fetch@example.test", 1_700_000_000, 0)
    commit_id = write_commit(
        remote.objects_dir,
        Commit(root_id, (), identity, identity, b"nested\n"),
    )
    compare_and_swap_ref(remote, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination")

    result = fetch_from_local(destination, remote.root, branches=["main"])

    assert result.objects_transferred == 4
    assert read_ref(destination, "refs/remotes/origin/main") == commit_id


def test_fetch_rejects_missing_parent_before_publication(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    identity = CommitIdentity("Fetch", "fetch@example.test", 1_700_000_000, 0)
    tree_id = write_tree(remote.objects_dir, [])
    missing_parent = "f" * 40
    commit_id = write_object(
        remote.objects_dir,
        "commit",
        serialize_commit(
            Commit(tree_id, (missing_parent,), identity, identity, b"broken\n")
        ),
    )
    (remote.git_dir / "refs" / "heads" / "main").write_text(
        commit_id + "\n", encoding="ascii"
    )
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(FetchError, match="invalid remote HEAD"):
        fetch_from_local(destination, remote.root, branches=["main"])

    assert not (destination.git_dir / "refs" / "remotes").exists()


def test_fetch_rejects_missing_branch_without_mutation(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(FetchError, match="not advertised"):
        fetch_from_local(destination, remote.root, branches=["missing"])

    assert not (destination.git_dir / "refs" / "remotes").exists()


def test_fetch_enforces_commit_limit_before_ref_publication(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    first = _commit(remote)
    second = _commit(remote, parents=(first,))
    compare_and_swap_ref(remote, "refs/heads/main", None, second)
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(FetchError, match="commit traversal"):
        fetch_from_local(
            destination,
            remote.root,
            branches=["main"],
            limits=TransferLimits(max_commit_traversal=1),
        )

    assert not (destination.git_dir / "refs" / "remotes").exists()


def test_fetch_rejects_corrupt_remote_object(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(remote)
    compare_and_swap_ref(remote, "refs/heads/main", None, commit_id)
    object_path = remote.objects_dir / commit_id[:2] / commit_id[2:]
    object_path.write_bytes(b"corrupt")
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(FetchError, match="invalid remote reference"):
        fetch_from_local(destination, remote.root, branches=["main"])

    assert not (destination.git_dir / "refs" / "remotes").exists()


def test_fetch_rejects_object_count_limit(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(remote)
    compare_and_swap_ref(remote, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(FetchError, match="object transfer count"):
        fetch_from_local(
            destination,
            remote.root,
            branches=["main"],
            limits=TransferLimits(max_objects_per_transfer=1),
        )

    assert not (destination.git_dir / "refs" / "remotes").exists()


def test_fetch_enforces_object_and_total_size_limits(tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(remote, message=b"large enough")
    compare_and_swap_ref(remote, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination")

    with pytest.raises(FetchError, match="cannot read remote object"):
        fetch_from_local(
            destination,
            remote.root,
            branches=["main"],
            limits=TransferLimits(max_decompressed_object_size=1),
        )
    with pytest.raises(FetchError, match="transfer exceeds"):
        fetch_from_local(
            destination,
            remote.root,
            branches=["main"],
            limits=TransferLimits(max_total_decompressed_transfer=1),
        )


def test_fetch_reports_partial_reference_publication(tmp_path, monkeypatch):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(remote)
    compare_and_swap_ref(remote, "refs/heads/alpha", None, commit_id)
    compare_and_swap_ref(remote, "refs/heads/beta", None, commit_id)
    destination = initialize_repository(tmp_path / "destination")
    real_cas = compare_and_swap_ref
    calls = 0

    def fail_second(repository, ref_name, expected_old, new_object_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ReferenceExpectationError("injected CAS conflict")
        real_cas(repository, ref_name, expected_old, new_object_id)

    monkeypatch.setattr("commitverse_core.fetch.compare_and_swap_ref", fail_second)
    result = fetch_from_local(destination, remote.root, all_branches=True)

    assert [item.status for item in result.references] == ["updated", "failed"]
    assert read_ref(destination, "refs/remotes/origin/alpha") == commit_id
    with pytest.raises(ReferenceNotFoundError):
        read_ref(destination, "refs/remotes/origin/beta")
