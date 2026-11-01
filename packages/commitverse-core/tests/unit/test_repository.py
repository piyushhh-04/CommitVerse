import pytest

from commitverse_core.repository import (
    RepositoryError,
    RepositoryNotFoundError,
    discover_repository,
    initialize_repository,
)


def test_initialize_repository_creates_git_compatible_structure(tmp_path):
    repository = initialize_repository(tmp_path / "project")

    assert repository.created
    assert repository.root == (tmp_path / "project").resolve()
    assert repository.git_dir.is_dir()
    assert repository.objects_dir.is_dir()
    assert (repository.objects_dir / "info").is_dir()
    assert (repository.objects_dir / "pack").is_dir()
    assert (repository.git_dir / "refs" / "heads").is_dir()
    assert (repository.git_dir / "refs" / "tags").is_dir()
    assert (repository.git_dir / "HEAD").read_text() == "ref: refs/heads/main\n"
    assert "[core]" in (repository.git_dir / "config").read_text()
    assert "repositoryformatversion = 0" in (repository.git_dir / "config").read_text()
    assert "bare = false" in (repository.git_dir / "config").read_text()


def test_reinitializing_repository_preserves_existing_metadata(tmp_path):
    repository = initialize_repository(tmp_path / "project")
    head_before = (repository.git_dir / "HEAD").read_bytes()
    config_before = (repository.git_dir / "config").read_bytes()
    marker = repository.git_dir / "custom-data"
    marker.write_bytes(b"preserve me")

    existing_repository = initialize_repository(repository.root)

    assert not existing_repository.created
    assert (repository.git_dir / "HEAD").read_bytes() == head_before
    assert (repository.git_dir / "config").read_bytes() == config_before
    assert marker.read_bytes() == b"preserve me"


def test_initialize_repository_rejects_file_path(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("file")

    with pytest.raises(RepositoryError, match="not a directory"):
        initialize_repository(path)


def test_initialize_repository_rejects_invalid_existing_git_directory(tmp_path):
    repository_path = tmp_path / "project"
    invalid_git_dir = repository_path / ".git"
    invalid_git_dir.mkdir(parents=True)
    (invalid_git_dir / "user-data").write_text("preserve")

    with pytest.raises(RepositoryError, match="existing .git"):
        initialize_repository(repository_path)

    assert (invalid_git_dir / "user-data").read_text() == "preserve"


def test_discover_repository_from_root_and_nested_directory(tmp_path):
    repository = initialize_repository(tmp_path / "project")
    nested = repository.root / "one" / "two"
    nested.mkdir(parents=True)

    assert discover_repository(repository.root).root == repository.root
    discovered = discover_repository(nested)
    assert discovered.root == repository.root
    assert discovered.git_dir == repository.git_dir
    assert discovered.objects_dir == repository.objects_dir


def test_discover_repository_from_file_path(tmp_path):
    repository = initialize_repository(tmp_path / "project")
    file_path = repository.root / "file.txt"
    file_path.write_text("content")

    assert discover_repository(file_path).root == repository.root


def test_discover_repository_rejects_arbitrary_git_directory(tmp_path):
    invalid_git_dir = tmp_path / "project" / ".git"
    invalid_git_dir.mkdir(parents=True)
    (invalid_git_dir / "HEAD").write_text("ref: refs/heads/main\n")

    with pytest.raises(RepositoryError, match="invalid or unsupported"):
        discover_repository(invalid_git_dir.parent)


def test_discover_repository_reports_missing_repository(tmp_path):
    with pytest.raises(RepositoryNotFoundError, match="no valid CommitVerse repository"):
        discover_repository(tmp_path)


def test_discover_repository_reports_missing_start_path(tmp_path):
    with pytest.raises(RepositoryError, match="cannot access repository search path"):
        discover_repository(tmp_path / "missing")
