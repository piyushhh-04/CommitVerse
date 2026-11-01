import os

import pytest

from commitverse_core import status
from commitverse_core.commit_service import create_commit
from commitverse_core.diff import generate_diff
from commitverse_core.index import Index, IndexEntry, IndexStat, write_index
from commitverse_core.objects.store import write_object
from commitverse_core.repository import initialize_repository
from commitverse_core.staging import add_paths
from commitverse_core.status import StatusError, get_status


def _configure_identity(repository):
    with (repository.git_dir / "config").open("a", encoding="utf-8") as config:
        config.write("\n[user]\n\tname = Status User\n\temail = status@example.test\n")


def _commit_worktree(repository, message="snapshot"):
    add_paths(repository, all=True, cwd=repository.root)
    return create_commit(
        repository,
        message,
        environment={
            "GIT_AUTHOR_NAME": "Status User",
            "GIT_AUTHOR_EMAIL": "status@example.test",
            "GIT_COMMITTER_NAME": "Status User",
            "GIT_COMMITTER_EMAIL": "status@example.test",
        },
    )


def test_clean_and_unborn_repository_status(tmp_path):
    repository = initialize_repository(tmp_path / "repo")

    unborn = get_status(repository)

    assert unborn.unborn
    assert unborn.branch_name == "main"
    assert unborn.clean

    _configure_identity(repository)
    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)
    staged = get_status(repository)
    assert staged.unborn
    assert [(change.path, change.kind) for change in staged.staged] == [
        (b"file", "new file")
    ]

    _commit_worktree(repository)
    clean = get_status(repository)
    assert clean.clean
    assert not clean.unborn


def test_staged_add_modify_and_delete_classifications(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.root / "modified.txt").write_text("before")
    (repository.root / "deleted.txt").write_text("remove")
    _commit_worktree(repository)

    (repository.root / "modified.txt").write_text("after")
    (repository.root / "deleted.txt").unlink()
    (repository.root / "new.txt").write_text("new")
    add_paths(repository, all=True, cwd=repository.root)

    result = get_status(repository)

    assert [(change.path, change.kind) for change in result.staged] == [
        (b"deleted.txt", "deleted"),
        (b"modified.txt", "modified"),
        (b"new.txt", "new file"),
    ]
    assert result.unstaged == ()


def test_unstaged_modification_deletion_and_staged_plus_unstaged(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.root / "both.txt").write_text("base")
    (repository.root / "deleted.txt").write_text("remove")
    _commit_worktree(repository)

    (repository.root / "both.txt").write_text("staged")
    add_paths(repository, ["both.txt"], cwd=repository.root)
    (repository.root / "both.txt").write_text("working")
    (repository.root / "deleted.txt").unlink()

    result = get_status(repository)

    assert [(change.path, change.kind) for change in result.staged] == [
        (b"both.txt", "modified")
    ]
    assert [(change.path, change.kind) for change in result.unstaged] == [
        (b"both.txt", "modified"),
        (b"deleted.txt", "deleted"),
    ]


def test_untracked_files_respect_ignore_rules_but_tracked_ignored_files_remain(
    tmp_path,
):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.root / "tracked.log").write_text("tracked")
    _commit_worktree(repository)
    (repository.root / ".gitignore").write_text("*.log\nignored-dir/\n")
    (repository.root / "tracked.log").write_text("changed")
    (repository.root / "new.log").write_text("ignored")
    (repository.root / "ignored-dir").mkdir()
    (repository.root / "ignored-dir" / "secret").write_text("ignored")
    (repository.root / "nested").mkdir()
    (repository.root / "nested" / "visible.txt").write_text("visible")

    result = get_status(repository)

    assert [(change.path, change.kind) for change in result.unstaged] == [
        (b"tracked.log", "modified")
    ]
    assert result.untracked == (b".gitignore", b"nested/visible.txt")


def test_status_detects_mode_changes_and_symlink_content(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    executable = repository.root / "script"
    executable.write_text("run\n")
    link = repository.root / "link"
    link.symlink_to("script")
    _commit_worktree(repository)

    executable.chmod(0o755)
    link.unlink()
    link.symlink_to("other")
    result = get_status(repository)
    assert [(change.path, change.kind) for change in result.unstaged] == [
        (b"link", "modified"),
        (b"script", "modified"),
    ]

    add_paths(repository, ["script", "link"], cwd=repository.root)
    staged = get_status(repository)
    assert [(change.path, change.kind) for change in staged.staged] == [
        (b"link", "modified"),
        (b"script", "modified"),
    ]


def test_status_orders_paths_by_filesystem_bytes_and_ignores_nested_repositories(
    tmp_path,
):
    repository = initialize_repository(tmp_path / "repo")
    nested = repository.root / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    (nested / "hidden").write_text("nested repo")
    (repository.root / "z-file").write_text("z")
    (repository.root / "a-file").write_text("a")
    (repository.root / "folder").mkdir()
    (repository.root / "folder" / "child").write_text("child")

    result = get_status(repository)

    assert result.untracked == (b"a-file", b"folder/child", b"z-file")


def test_status_handles_deleted_and_recreated_staged_deletion(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    tracked = repository.root / "file"
    tracked.write_text("tracked")
    _commit_worktree(repository)

    tracked.unlink()
    add_paths(repository, all=True, cwd=repository.root)
    tracked.write_text("recreated")

    result = get_status(repository)
    assert [(change.path, change.kind) for change in result.staged] == [
        (b"file", "deleted")
    ]
    assert [(change.path, change.kind) for change in result.unstaged] == [
        (b"file", "new file")
    ]
    assert result.untracked == ()


def test_status_does_not_follow_tracked_parent_symlink_outside_repository(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    folder = repository.root / "folder"
    folder.mkdir()
    (folder / "file").write_text("inside")
    _commit_worktree(repository)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_text("outside")
    folder.rename(repository.root / "old-folder")
    folder.symlink_to(outside, target_is_directory=True)

    with pytest.raises(StatusError, match="cannot safely access tracked path"):
        get_status(repository)


def test_status_rejects_unmerged_index_and_missing_index_objects(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    write_index(
        repository.git_dir / "index",
        Index(
            (
                IndexEntry(
                    b"conflict",
                    "1" * 40,
                    IndexStat(mode=0o100644),
                    stage=2,
                ),
            )
        ),
    )

    with pytest.raises(StatusError, match="unmerged"):
        get_status(repository)

    write_index(
        repository.git_dir / "index",
        Index((IndexEntry(b"missing", "2" * 40, IndexStat(mode=0o100644)),)),
    )
    with pytest.raises(FileNotFoundError):
        get_status(repository)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_untracked_symlink_is_reported_without_following_target(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.write_text("outside")
    (repository.root / "link").symlink_to(outside)

    assert get_status(repository).untracked == (b"link",)


def test_status_refuses_special_files_in_tracked_paths(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    object_id = write_object(repository.objects_dir, "blob", b"")
    write_index(
        repository.git_dir / "index",
        Index((IndexEntry(b"special", object_id, IndexStat(mode=0o100644)),)),
    )
    (repository.root / "special").mkdir()

    with pytest.raises(StatusError, match="not a regular file"):
        get_status(repository)


def test_status_rejects_index_paths_inside_git_metadata(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    object_id = write_object(repository.objects_dir, "blob", b"secret")
    write_index(
        repository.git_dir / "index",
        Index((IndexEntry(b".git/config", object_id, IndexStat(mode=0o100644)),)),
    )

    with pytest.raises(StatusError, match="enters.*\\.git"):
        get_status(repository)


def test_tracked_file_change_during_read_is_reported(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    target = repository.root / "file"
    target.write_bytes(b"before" * 100)
    _commit_worktree(repository)

    original_read = os.read
    mutated = False

    def read_then_mutate(descriptor, size):
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if not mutated:
            mutated = True
            target.write_bytes(b"changed while reading")
        return chunk

    monkeypatch.setattr(status.os, "read", read_then_mutate)
    with pytest.raises(StatusError, match="changed while being read"):
        get_status(repository)


def test_status_refuses_symlinked_gitignore_without_following_it(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    outside = tmp_path / "outside-ignore"
    outside.write_text("*\n")
    (repository.root / ".gitignore").symlink_to(outside)

    with pytest.raises(StatusError, match="gitignore must be a regular file"):
        get_status(repository)


def test_status_and_diff_do_not_modify_index_objects_or_references(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    target = repository.root / "file"
    target.write_text("before\n")
    _commit_worktree(repository)
    target.write_text("after\n")

    index_before = (repository.git_dir / "index").read_bytes()
    head_before = (repository.git_dir / "refs/heads/main").read_bytes()
    objects_before = {
        path.relative_to(repository.objects_dir)
        for path in repository.objects_dir.rglob("*")
        if path.is_file()
    }

    get_status(repository)
    generate_diff(repository)

    assert (repository.git_dir / "index").read_bytes() == index_before
    assert (repository.git_dir / "refs/heads/main").read_bytes() == head_before
    assert {
        path.relative_to(repository.objects_dir)
        for path in repository.objects_dir.rglob("*")
        if path.is_file()
    } == objects_before
