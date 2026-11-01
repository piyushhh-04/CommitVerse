from datetime import datetime, timezone

import pytest

from commitverse_core.commit_service import CommitServiceError, create_commit
from commitverse_core.commits import read_commit
from commitverse_core.index import read_index
from commitverse_core.refs import resolve_head
from commitverse_core.repository import initialize_repository
from commitverse_core.staging import add_paths
from commitverse_core.trees import write_tree


def _configure_identity(repository):
    with (repository.git_dir / "config").open("a", encoding="utf-8") as config:
        config.write(
            "\n[user]\n"
            '\tname = Test User\n'
            '\temail = test@example.test\n'
        )


def test_first_commit_uses_staged_tree_and_no_parent(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.root / "file").write_bytes(b"first\x00")
    add_paths(repository, ["file"], cwd=repository.root)

    result = create_commit(
        repository,
        "first commit",
        environment={
            "GIT_AUTHOR_DATE": "@1700000000 +0530",
            "GIT_COMMITTER_DATE": "1700000001 -0400",
        },
        now=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    commit = read_commit(repository.objects_dir, result.object_id)
    assert result.parent_id is None
    assert result.branch_name == "main"
    assert result.path_count == 1
    assert commit.parent_ids == ()
    assert commit.tree_id == write_tree(
        repository.objects_dir, read_index(repository.git_dir / "index").entries
    )
    assert commit.message == b"first commit\n"
    assert commit.author.timestamp == 1_700_000_000
    assert commit.author.timezone_offset == 330
    assert commit.committer.timestamp == 1_700_000_001
    assert commit.committer.timezone_offset == -240
    assert resolve_head(repository) == result.object_id


def test_second_commit_has_parent_and_changed_tree(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    file_path = repository.root / "file"
    file_path.write_text("before")
    add_paths(repository, ["file"], cwd=repository.root)
    first = create_commit(repository, "first")

    file_path.write_text("after")
    add_paths(repository, ["file"], cwd=repository.root)
    second = create_commit(repository, "second")

    commit = read_commit(repository.objects_dir, second.object_id)
    assert commit.parent_ids == (first.object_id,)
    assert second.tree_id != first.tree_id
    assert resolve_head(repository) == second.object_id


def test_commit_rejects_empty_initial_and_unchanged_trees(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)

    with pytest.raises(CommitServiceError, match="empty initial commit"):
        create_commit(repository, "not empty")
    assert resolve_head(repository) is None

    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)
    first = create_commit(repository, "first")
    with pytest.raises(CommitServiceError, match="index matches HEAD"):
        create_commit(repository, "no change")
    assert resolve_head(repository) == first.object_id


def test_empty_index_commits_deletion_of_last_tracked_path(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    file_path = repository.root / "file"
    file_path.write_text("tracked")
    add_paths(repository, ["file"], cwd=repository.root)
    first = create_commit(repository, "add file")
    file_path.unlink()
    add_paths(repository, all=True, cwd=repository.root)

    deletion = create_commit(repository, "delete final file")
    commit = read_commit(repository.objects_dir, deletion.object_id)

    assert deletion.path_count == 0
    assert commit.parent_ids == (first.object_id,)
    assert commit.tree_id != first.tree_id
    assert resolve_head(repository) == deletion.object_id


def test_commit_rejects_missing_identity_and_empty_message(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)

    with pytest.raises(CommitServiceError, match="identity is required"):
        create_commit(repository, "message", environment={})
    with pytest.raises(CommitServiceError, match="message must not be empty"):
        create_commit(repository, " \n", environment={})
    assert resolve_head(repository) is None


def test_environment_identity_overrides_repository_config(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)

    result = create_commit(
        repository,
        "override",
        environment={
            "GIT_AUTHOR_NAME": "Author Override",
            "GIT_AUTHOR_EMAIL": "author@example.test",
            "GIT_COMMITTER_NAME": "Committer Override",
            "GIT_COMMITTER_EMAIL": "committer@example.test",
        },
        now=datetime(2024, 2, 1, 12, 30, tzinfo=timezone.utc),
    )
    commit = read_commit(repository.objects_dir, result.object_id)

    assert (commit.author.name, commit.author.email) == (
        "Author Override",
        "author@example.test",
    )
    assert (commit.committer.name, commit.committer.email) == (
        "Committer Override",
        "committer@example.test",
    )
    assert commit.author.timestamp == int(datetime(2024, 2, 1, 12, 30, tzinfo=timezone.utc).timestamp())


@pytest.mark.parametrize(
    "date_value",
    ["today", "1 +2460", "@-01 +0000", "1 0000"],
)
def test_invalid_date_environment_override_is_rejected(tmp_path, date_value):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)

    with pytest.raises(CommitServiceError, match="GIT_AUTHOR_DATE"):
        create_commit(
            repository,
            "message",
            environment={"GIT_AUTHOR_DATE": date_value},
        )
