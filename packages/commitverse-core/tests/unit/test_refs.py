from concurrent.futures import ThreadPoolExecutor

import pytest

from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.objects import write_object
from commitverse_core.refs import (
    ReferenceError,
    ReferenceExpectationError,
    ReferenceLockError,
    ReferenceNotFoundError,
    ReferenceUpdateError,
    compare_and_swap_ref,
    create_branch,
    current_branch,
    list_branches,
    read_head,
    read_ref,
    resolve_branch,
    resolve_head,
    update_head,
    validate_ref_name,
    write_ref,
)
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import write_tree


@pytest.fixture
def repository_with_commit(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    tree_id = write_tree(repository.objects_dir, [])
    identity = CommitIdentity("Test User", "test@example.test", 1_700_000_000, 0)
    commit_id = write_commit(
        repository.objects_dir,
        Commit(tree_id, (), identity, identity, b"initial\n"),
    )
    return repository, commit_id


@pytest.mark.parametrize(
    "name",
    [
        "heads/main",
        "refs/heads/",
        "refs/heads/../bad",
        "refs/heads/a..b",
        "refs/heads/a//b",
        "refs/heads/.hidden",
        "refs/heads/name.lock",
        "refs/heads/a@{b",
        "refs/heads/has space",
        "refs/heads/a\\b",
    ],
)
def test_invalid_ref_names_are_rejected(name):
    with pytest.raises(ReferenceError):
        validate_ref_name(name)


def test_symbolic_unborn_head_resolves_to_no_commit(tmp_path):
    repository = initialize_repository(tmp_path / "repo")

    assert read_head(repository).symbolic_ref == "refs/heads/main"
    assert current_branch(repository) == "main"
    assert resolve_head(repository) is None
    assert list_branches(repository) == ()


def test_bare_repository_supports_objects_refs_and_head(tmp_path):
    repository = initialize_repository(tmp_path / "server.git", bare=True)
    tree_id = write_tree(repository.objects_dir, [])
    identity = CommitIdentity("Test User", "test@example.test", 1_700_000_000, 0)
    commit_id = write_commit(
        repository.objects_dir,
        Commit(tree_id, (), identity, identity, b"initial\n"),
    )

    write_ref(repository, "refs/heads/main", commit_id)

    assert read_ref(repository, "refs/heads/main") == commit_id
    assert resolve_head(repository) == commit_id
    assert repository.head_path.read_text() == "ref: refs/heads/main\n"


def test_compare_and_swap_publishes_expected_update(repository_with_commit):
    repository, first_id = repository_with_commit
    identity = CommitIdentity("Second", "second@example.test", 1_700_000_001, 0)
    second_id = write_commit(
        repository.objects_dir,
        Commit(write_tree(repository.objects_dir, []), (first_id,), identity, identity, b"second\n"),
    )
    compare_and_swap_ref(repository, "refs/heads/main", None, first_id)
    compare_and_swap_ref(repository, "refs/heads/main", first_id, second_id)

    assert read_ref(repository, "refs/heads/main") == second_id
    assert not (repository.git_dir / "refs/heads/main.lock").exists()


def test_compare_and_swap_expected_mismatch_does_not_modify_ref(repository_with_commit):
    repository, first_id = repository_with_commit
    compare_and_swap_ref(repository, "refs/heads/main", None, first_id)

    with pytest.raises(ReferenceExpectationError, match="changed"):
        compare_and_swap_ref(repository, "refs/heads/main", None, first_id)

    assert read_ref(repository, "refs/heads/main") == first_id
    assert not (repository.git_dir / "refs/heads/main.lock").exists()


def test_compare_and_swap_rejects_existing_lock(repository_with_commit):
    repository, first_id = repository_with_commit
    lock_path = repository.git_dir / "refs/heads/main.lock"
    lock_path.write_text("owned\n", encoding="ascii")

    with pytest.raises(ReferenceLockError):
        compare_and_swap_ref(repository, "refs/heads/main", None, first_id)

    assert lock_path.read_text(encoding="ascii") == "owned\n"


def test_compare_and_swap_deletes_expected_ref(repository_with_commit):
    repository, first_id = repository_with_commit
    compare_and_swap_ref(repository, "refs/heads/main", None, first_id)
    compare_and_swap_ref(repository, "refs/heads/main", first_id, None)

    with pytest.raises(ReferenceNotFoundError):
        read_ref(repository, "refs/heads/main")


def test_compare_and_swap_supports_bare_repository(repository_with_commit, tmp_path):
    _, first_id = repository_with_commit
    repository = initialize_repository(tmp_path / "server.git", bare=True)
    tree_id = write_tree(repository.objects_dir, [])
    identity = CommitIdentity("Bare", "bare@example.test", 1_700_000_000, 0)
    bare_id = write_commit(
        repository.objects_dir,
        Commit(tree_id, (), identity, identity, b"bare\n"),
    )

    compare_and_swap_ref(repository, "refs/heads/main", None, bare_id)

    assert read_ref(repository, "refs/heads/main") == bare_id


def test_compare_and_swap_allows_independent_refs_concurrently(repository_with_commit):
    repository, first_id = repository_with_commit

    def update(ref_name):
        compare_and_swap_ref(repository, ref_name, None, first_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                update,
                ("refs/heads/one", "refs/heads/two"),
            )
        )

    assert read_ref(repository, "refs/heads/one") == first_id
    assert read_ref(repository, "refs/heads/two") == first_id


def test_compare_and_swap_failure_before_replacement_preserves_old_value(
    repository_with_commit, monkeypatch
):
    repository, first_id = repository_with_commit
    compare_and_swap_ref(repository, "refs/heads/main", None, first_id)
    lock_path = repository.git_dir / "refs/heads/main.lock"

    def fail_replace(source, destination):
        raise OSError("replacement failed")

    monkeypatch.setattr("commitverse_core.refs.os.replace", fail_replace)
    with pytest.raises(ReferenceUpdateError, match="before publication") as error:
        compare_and_swap_ref(repository, "refs/heads/main", first_id, first_id)

    assert not error.value.published
    assert read_ref(repository, "refs/heads/main") == first_id
    assert not lock_path.exists()


def test_compare_and_swap_reports_post_publication_durability_failure(
    repository_with_commit, monkeypatch
):
    repository, first_id = repository_with_commit
    lock_path = repository.git_dir / "refs/heads/main.lock"
    real_fsync = __import__("os").fsync
    calls = 0

    def fail_directory_fsync(file_descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory sync failed")
        real_fsync(file_descriptor)

    monkeypatch.setattr("commitverse_core.refs.os.fsync", fail_directory_fsync)
    with pytest.raises(ReferenceUpdateError) as error:
        compare_and_swap_ref(repository, "refs/heads/main", None, first_id)

    assert error.value.published
    assert read_ref(repository, "refs/heads/main") == first_id
    assert not lock_path.exists()


def test_create_read_update_and_list_branches(repository_with_commit):
    repository, commit_id = repository_with_commit
    create_branch(repository, "feature/topic", commit_id)

    assert read_ref(repository, "refs/heads/feature/topic") == commit_id
    assert resolve_branch(repository, "feature/topic") == commit_id
    assert [(branch.name, branch.object_id) for branch in list_branches(repository)] == [
        ("feature/topic", commit_id)
    ]
    assert current_branch(repository) == "main"

    with pytest.raises(ReferenceError, match="already exists"):
        create_branch(repository, "feature/topic", commit_id)


def test_write_ref_updates_atomically_and_preserves_old_value_on_failure(
    repository_with_commit, monkeypatch
):
    repository, first_id = repository_with_commit
    identity = CommitIdentity("Second", "second@example.test", 1_700_000_001, 60)
    tree_id = write_tree(repository.objects_dir, [])
    second_id = write_commit(
        repository.objects_dir,
        Commit(tree_id, (first_id,), identity, identity, b"second\n"),
    )
    write_ref(repository, "refs/heads/main", first_id)
    previous_contents = (repository.git_dir / "refs/heads/main").read_bytes()

    def fail_replace(source, destination):
        raise OSError("replacement failed")

    monkeypatch.setattr("commitverse_core.refs.os.replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        write_ref(repository, "refs/heads/main", second_id)

    assert (repository.git_dir / "refs/heads/main").read_bytes() == previous_contents
    assert list((repository.git_dir / "refs/heads").iterdir()) == [
        repository.git_dir / "refs/heads/main"
    ]


def test_detached_head_commit_update_does_not_move_branch(repository_with_commit):
    repository, first_id = repository_with_commit
    identity = CommitIdentity("Second", "second@example.test", 1_700_000_001, 0)
    second_id = write_commit(
        repository.objects_dir,
        Commit(
            write_tree(repository.objects_dir, []),
            (first_id,),
            identity,
            identity,
            b"second",
        ),
    )
    write_ref(repository, "refs/heads/main", first_id)
    head_path = repository.git_dir / "HEAD"
    head_path.write_text(first_id + "\n", encoding="ascii")

    assert read_head(repository).object_id == first_id
    assert current_branch(repository) is None
    assert resolve_head(repository) == first_id
    update_head(repository, second_id)

    assert resolve_head(repository) == second_id
    assert read_ref(repository, "refs/heads/main") == first_id
    assert head_path.read_text(encoding="ascii") == second_id + "\n"


def test_symbolic_head_update_moves_only_its_branch(repository_with_commit):
    repository, commit_id = repository_with_commit
    write_ref(repository, "refs/heads/main", commit_id)
    head_contents = (repository.git_dir / "HEAD").read_bytes()

    update_head(repository, commit_id)

    assert (repository.git_dir / "HEAD").read_bytes() == head_contents
    assert resolve_head(repository) == commit_id


def test_missing_malformed_and_unsafe_references_fail(repository_with_commit):
    repository, _ = repository_with_commit
    with pytest.raises(ReferenceNotFoundError):
        read_ref(repository, "refs/heads/missing")

    malformed_ref = repository.git_dir / "refs/heads/bad"
    malformed_ref.write_text("not-an-object-id\n", encoding="ascii")
    with pytest.raises(ReferenceError, match="malformed"):
        read_ref(repository, "refs/heads/bad")

    (repository.git_dir / "refs/heads/escape").symlink_to(
        repository.root / "outside", target_is_directory=True
    )
    with pytest.raises(ReferenceError, match="unsafe"):
        read_ref(repository, "refs/heads/escape/branch")


@pytest.mark.parametrize("head_contents", ["", "invalid\n", "ref: refs/heads/../bad\n"])
def test_malformed_head_fails_clearly(repository_with_commit, head_contents):
    repository, _ = repository_with_commit
    (repository.git_dir / "HEAD").write_text(head_contents, encoding="ascii")

    with pytest.raises(ReferenceError):
        read_head(repository)


def test_branch_creation_rejects_unborn_target(repository_with_commit):
    repository, _ = repository_with_commit

    with pytest.raises(ReferenceError, match="not a valid commit"):
        create_branch(repository, "new", "f" * 40)


def test_reference_target_must_be_a_commit(repository_with_commit):
    repository, _ = repository_with_commit
    blob_id = write_object(repository.objects_dir, "blob", b"not a commit")

    with pytest.raises(ReferenceError, match="not a valid commit"):
        write_ref(repository, "refs/heads/blob", blob_id)


def test_missing_non_branch_head_reference_is_not_treated_as_unborn(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.git_dir / "HEAD").write_text(
        "ref: refs/tags/missing\n", encoding="ascii"
    )

    with pytest.raises(ReferenceNotFoundError):
        resolve_head(repository)
