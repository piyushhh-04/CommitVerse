import pytest

from commitverse_core.checkout import CheckoutError, checkout_revision, switch_branch
from commitverse_core.commit_service import create_commit
from commitverse_core.merge import MergeError, merge_branch
from commitverse_core.refs import (
    create_branch,
    current_branch,
    delete_branch,
    read_head,
    resolve_branch,
    resolve_head,
)
from commitverse_core.repository import initialize_repository
from commitverse_core.staging import add_paths


def _repository(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.git_dir / "config").write_text(
        "[core]\nrepositoryformatversion = 0\nfilemode = true\nbare = false\n"
        "[user]\nname = Test User\nemail = test@example.test\n"
    )
    return repository


def _commit(repository, content, message):
    (repository.root / "file").write_text(content)
    add_paths(repository, ["file"], cwd=repository.root)
    return create_commit(repository, message).object_id


def test_switch_and_detached_checkout_restore_worktree_and_head(tmp_path):
    repository = _repository(tmp_path)
    first = _commit(repository, "first\n", "first")
    create_branch(repository, "feature", first)
    main = _commit(repository, "main\n", "main")

    switch_branch(repository, "feature", first)
    assert (repository.root / "file").read_text() == "first\n"
    assert current_branch(repository) == "feature"

    checkout_revision(repository, main)
    assert (repository.root / "file").read_text() == "main\n"
    assert read_head(repository).object_id == main
    assert resolve_branch(repository, "feature") == first


def test_checkout_refuses_dirty_tracked_files_and_untracked_collisions(tmp_path):
    repository = _repository(tmp_path)
    first = _commit(repository, "first\n", "first")
    create_branch(repository, "feature", first)
    (repository.root / "collision").write_text("tracked\n")
    add_paths(repository, ["collision"], cwd=repository.root)
    target = create_commit(repository, "collision").object_id
    create_branch(repository, "target", target)
    switch_branch(repository, "feature", first)
    (repository.root / "file").write_text("dirty\n")
    with pytest.raises(CheckoutError, match="local changes"):
        switch_branch(repository, "feature", first)

    (repository.root / "file").write_text("first\n")
    (repository.root / "collision").write_text("untracked\n")
    with pytest.raises(CheckoutError):
        switch_branch(repository, "target", target)


def test_fast_forward_merge_updates_current_branch_without_merge_commit(tmp_path):
    repository = _repository(tmp_path)
    first = _commit(repository, "first\n", "first")
    create_branch(repository, "feature", first)
    switch_branch(repository, "feature", first)
    tip = _commit(repository, "feature\n", "feature")
    switch_branch(repository, "main", first)

    result, merged = merge_branch(repository, "feature")
    assert result == "fast-forward"
    assert merged == tip
    assert resolve_head(repository) == tip
    assert current_branch(repository) == "main"


def test_conflicting_merge_does_not_create_commit(tmp_path):
    repository = _repository(tmp_path)
    first = _commit(repository, "base\n", "base")
    create_branch(repository, "feature", first)
    _commit(repository, "main\n", "main")
    switch_branch(repository, "feature", first)
    _commit(repository, "feature\n", "feature")
    switch_branch(repository, "main", resolve_branch(repository, "main"))
    current = resolve_head(repository)

    with pytest.raises(MergeError, match="content"):
        merge_branch(repository, "feature")
    assert resolve_head(repository) == current


def test_branch_deletion_requires_merged_branch_and_preserves_objects(tmp_path):
    repository = _repository(tmp_path)
    root = _commit(repository, "root\n", "root")
    create_branch(repository, "merged", root)
    delete_branch(repository, "merged")
    assert resolve_head(repository) == root

    create_branch(repository, "current", root)
    switch_branch(repository, "current", root)
    tip = _commit(repository, "tip\n", "tip")
    create_branch(repository, "unmerged", tip)
    switch_branch(repository, "main", root)
    with pytest.raises(ValueError, match="currently checked-out|fully merged"):
        delete_branch(repository, "unmerged")
    assert resolve_branch(repository, "unmerged") == tip
