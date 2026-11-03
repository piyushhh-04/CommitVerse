import os
import stat

import pytest

import commitverse_core.checkout as checkout_module
from commitverse_core.checkout import CheckoutError, checkout_revision, switch_branch
from commitverse_core.commit_service import create_commit
from commitverse_core.commits import read_commit
from commitverse_core.merge import MergeError, merge_branch
from commitverse_core.refs import (
    create_branch,
    current_branch,
    delete_branch,
    read_head,
    read_ref,
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


def test_merge_commit_uses_configured_and_environment_identities(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    base = _commit(repository, "base\n", "base")
    create_branch(repository, "feature", base)
    (repository.root / "main.txt").write_text("main\n")
    add_paths(repository, ["main.txt"], cwd=repository.root)
    create_commit(repository, "main")
    switch_branch(repository, "feature", base)
    (repository.root / "feature.txt").write_text("feature\n")
    add_paths(repository, ["feature.txt"], cwd=repository.root)
    create_commit(repository, "feature")
    switch_branch(repository, "main", resolve_branch(repository, "main"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Merge Author")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "merge-author@example.test")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "@1700000010 +0000")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Merge Committer")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "merge-committer@example.test")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "@1700000011 +0000")

    current_tip = resolve_head(repository)
    feature_tip = resolve_branch(repository, "feature")
    result, merge_id = merge_branch(repository, "feature")
    commit = read_commit(repository.objects_dir, merge_id)
    assert result == "merged"
    assert commit.parent_ids == (current_tip, feature_tip)
    assert commit.author.name == "Merge Author"
    assert commit.author.email == "merge-author@example.test"
    assert commit.author.timestamp == 1700000010
    assert commit.committer.name == "Merge Committer"
    assert commit.committer.email == "merge-committer@example.test"
    assert commit.committer.timestamp == 1700000011


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


@pytest.mark.parametrize("transition", ["file-to-directory", "directory-to-file"])
def test_checkout_rolls_back_file_directory_transitions_on_index_failure(
    tmp_path, monkeypatch, transition
):
    repository = _repository(tmp_path)
    if transition == "file-to-directory":
        (repository.root / "a").write_text("old\n")
        add_paths(repository, ["a"], cwd=repository.root)
        base = create_commit(repository, "old").object_id
        create_branch(repository, "target", base)
        switch_branch(repository, "target", base)
        (repository.root / "a").unlink()
        (repository.root / "a").mkdir()
        (repository.root / "a" / "b").write_text("new\n")
        add_paths(repository, [], all=True, cwd=repository.root)
        target = create_commit(repository, "target").object_id
        switch_branch(repository, "main", base)
        original_state = ("file", "old\n")
    else:
        (repository.root / "a").mkdir()
        (repository.root / "a" / "b").write_text("old\n")
        add_paths(repository, ["a/b"], cwd=repository.root)
        base = create_commit(repository, "old").object_id
        create_branch(repository, "target", base)
        switch_branch(repository, "target", base)
        (repository.root / "a" / "b").unlink()
        (repository.root / "a").rmdir()
        (repository.root / "a").write_text("new\n")
        add_paths(repository, [], all=True, cwd=repository.root)
        target = create_commit(repository, "target").object_id
        switch_branch(repository, "main", base)
        original_state = ("directory", (repository.root / "a" / "b").read_text())

    original_write_index = checkout_module.write_index
    monkeypatch.setattr(
        checkout_module,
        "write_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected index failure")
        ),
    )
    with pytest.raises(CheckoutError, match="injected index failure"):
        switch_branch(repository, "target", target)

    assert resolve_head(repository) == base
    if original_state[0] == "file":
        assert (repository.root / "a").is_file()
        assert (repository.root / "a").read_text() == original_state[1]
    else:
        assert (repository.root / "a").is_dir()
        assert (repository.root / "a" / "b").read_text() == original_state[1]
    assert (repository.git_dir / "index").read_bytes()
    assert read_ref(repository, "refs/heads/main") == base
    monkeypatch.setattr(checkout_module, "write_index", original_write_index)


def test_checkout_failure_during_backup_preserves_state(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    base = _commit(repository, "base\n", "base")
    create_branch(repository, "target", base)
    switch_branch(repository, "target", base)
    (repository.root / "file").write_text("target\n")
    add_paths(repository, [], all=True, cwd=repository.root)
    target = create_commit(repository, "target").object_id
    switch_branch(repository, "main", base)
    original = checkout_module._backup_path
    monkeypatch.setattr(
        checkout_module,
        "_backup_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CheckoutError("injected backup failure")
        ),
    )
    with pytest.raises(CheckoutError, match="injected backup failure"):
        switch_branch(repository, "target", target)
    assert resolve_head(repository) == base
    assert (repository.root / "file").read_text() == "base\n"
    assert read_head(repository).symbolic_ref == "refs/heads/main"
    assert read_ref(repository, "refs/heads/main") == base
    monkeypatch.setattr(checkout_module, "_backup_path", original)


def test_checkout_failure_during_worktree_write_restores_mode_and_content(
    tmp_path, monkeypatch
):
    repository = _repository(tmp_path)
    base = _commit(repository, "base\n", "base")
    create_branch(repository, "target", base)
    switch_branch(repository, "target", base)
    (repository.root / "file").write_text("target\n")
    os.chmod(repository.root / "file", 0o755)
    add_paths(repository, [], all=True, cwd=repository.root)
    target = create_commit(repository, "target").object_id
    switch_branch(repository, "main", base)
    monkeypatch.setattr(
        checkout_module,
        "_write_target",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected worktree failure")
        ),
    )
    with pytest.raises(CheckoutError, match="injected worktree failure"):
        switch_branch(repository, "target", target)
    assert (repository.root / "file").read_text() == "base\n"
    assert stat.S_IMODE((repository.root / "file").stat().st_mode) == 0o644
    assert resolve_head(repository) == base


def test_checkout_failure_during_reference_update_restores_head_and_index(
    tmp_path, monkeypatch
):
    repository = _repository(tmp_path)
    base = _commit(repository, "base\n", "base")
    create_branch(repository, "target", base)
    switch_branch(repository, "target", base)
    (repository.root / "file").write_text("target\n")
    add_paths(repository, [], all=True, cwd=repository.root)
    target = create_commit(repository, "target").object_id
    switch_branch(repository, "main", base)
    original = checkout_module.set_head_symbolic
    monkeypatch.setattr(
        checkout_module,
        "set_head_symbolic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected reference failure")
        ),
    )
    with pytest.raises(CheckoutError, match="injected reference failure"):
        switch_branch(repository, "target", target)
    assert resolve_head(repository) == base
    assert read_head(repository).symbolic_ref == "refs/heads/main"
    assert (repository.root / "file").read_text() == "base\n"
    monkeypatch.setattr(checkout_module, "set_head_symbolic", original)


def test_checkout_failure_restores_symlink_target(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    (repository.root / "target").write_text("target\n")
    (repository.root / "link").symlink_to("target")
    add_paths(repository, ["target", "link"], cwd=repository.root)
    base = create_commit(repository, "base").object_id
    create_branch(repository, "target-branch", base)
    switch_branch(repository, "target-branch", base)
    (repository.root / "replacement").write_text("replacement\n")
    add_paths(repository, ["replacement"], cwd=repository.root)
    target = create_commit(repository, "target").object_id
    switch_branch(repository, "main", base)
    monkeypatch.setattr(
        checkout_module,
        "write_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected index failure")
        ),
    )
    with pytest.raises(CheckoutError, match="injected index failure"):
        switch_branch(repository, "target-branch", target)
    assert (repository.root / "link").is_symlink()
    assert os.readlink(repository.root / "link") == "target"
    assert (repository.root / "target").read_text() == "target\n"
