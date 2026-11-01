import re

import pytest

from commitverse_core.cli import main
from commitverse_core.commits import read_commit
from commitverse_core.refs import resolve_head, resolve_branch
from commitverse_core.repository import initialize_repository
from commitverse_core.staging import add_paths


@pytest.fixture(autouse=True)
def clear_git_identity_environment(monkeypatch):
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_DATE",
    ):
        monkeypatch.delenv(name, raising=False)


def _object_id_from_output(output):
    match = re.search(r" ([0-9a-f]{40})\]", output)
    assert match is not None
    return match.group(1)


def _configure_identity(repository):
    with (repository.git_dir / "config").open("a", encoding="utf-8") as config:
        config.write(
            "\n[user]\n"
            "\tname = CLI User\n"
            "\temail = cli@example.test\n"
        )


def test_commit_branch_rev_parse_and_log_commands(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    monkeypatch.chdir(repository.root)
    file_path = repository.root / "file"
    file_path.write_text("first")
    assert main(["add", "file"]) == 0

    assert main(["commit", "-m", "first \N{SNOWMAN}"]) == 0
    first_output = capsys.readouterr().out
    first_id = _object_id_from_output(first_output)
    assert len(first_id) == 40
    assert "root-commit" in first_output
    assert "1 staged path(s) committed" in first_output
    assert resolve_head(repository) == first_id

    assert main(["branch"]) == 0
    assert capsys.readouterr().out == "* main\n"
    assert main(["branch", "feature/topic"]) == 0
    assert "Created branch feature/topic" in capsys.readouterr().out
    assert resolve_branch(repository, "feature/topic") == first_id
    assert resolve_head(repository) == first_id
    assert main(["branch", "feature/topic"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["branch", "bad..name"]) == 1
    assert "invalid reference name" in capsys.readouterr().err

    assert main(["rev-parse", "HEAD"]) == 0
    assert capsys.readouterr().out == first_id + "\n"
    assert main(["rev-parse", "feature/topic"]) == 0
    assert capsys.readouterr().out == first_id + "\n"
    assert main(["rev-parse", first_id]) == 0
    assert capsys.readouterr().out == first_id + "\n"
    assert main(["rev-parse", "missing"]) == 1
    assert "reference does not exist" in capsys.readouterr().err

    file_path.write_text("second")
    assert main(["add", "file"]) == 0
    assert main(["commit", "-m", "second\nmessage"]) == 0
    second_output = capsys.readouterr().out
    second_id = _object_id_from_output(second_output)
    assert read_commit(repository.objects_dir, second_id).parent_ids == (first_id,)

    assert main(["log"]) == 0
    log = capsys.readouterr().out
    assert log.index(f"commit {second_id}") < log.index(f"commit {first_id}")
    assert "Parents: " + first_id in log
    assert "Author: CLI User <cli@example.test>" in log
    assert "second" in log
    assert "message" in log
    assert "\N{SNOWMAN}" in log


def test_cli_handles_unborn_repository_and_empty_commit(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    monkeypatch.chdir(repository.root)

    assert main(["branch", "--list"]) == 0
    assert capsys.readouterr().out == "* main\n"
    assert main(["rev-parse", "HEAD"]) == 1
    assert "unborn" in capsys.readouterr().err
    assert main(["branch", "new"]) == 1
    assert "before the first commit" in capsys.readouterr().err
    assert main(["log"]) == 0
    assert capsys.readouterr().out == "No commits yet.\n"
    assert main(["commit", "-m", "empty"]) == 1
    assert "empty initial commit" in capsys.readouterr().err
    assert main(["commit", "-m", ""]) == 1
    assert "message must not be empty" in capsys.readouterr().err
    with pytest.raises(SystemExit) as missing_message:
        main(["commit"])
    assert missing_message.value.code == 2


def test_initial_commit_uses_symbolic_branch_from_head(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    (repository.git_dir / "HEAD").write_text(
        "ref: refs/heads/trunk\n", encoding="ascii"
    )
    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)
    monkeypatch.chdir(repository.root)

    assert main(["commit", "-m", "trunk root"]) == 0
    output = capsys.readouterr().out
    commit_id = _object_id_from_output(output)

    assert "[trunk (root-commit)" in output
    assert resolve_head(repository) == commit_id
    assert (repository.git_dir / "refs/heads/trunk").read_text() == commit_id + "\n"
    assert not (repository.git_dir / "refs/heads/main").exists()


def test_detached_head_commit_updates_head_not_branch(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    monkeypatch.chdir(repository.root)
    (repository.root / "file").write_text("first")
    add_paths(repository, ["file"], cwd=repository.root)
    assert main(["commit", "-m", "first"]) == 0
    capsys.readouterr()
    first_id = resolve_head(repository)
    branch_before = (repository.git_dir / "refs/heads/main").read_bytes()
    (repository.git_dir / "HEAD").write_text(first_id + "\n", encoding="ascii")
    assert main(["branch", "detached-point"]) == 0
    capsys.readouterr()
    assert resolve_head(repository) == first_id
    assert resolve_branch(repository, "detached-point") == first_id

    (repository.root / "file").write_text("second")
    add_paths(repository, ["file"], cwd=repository.root)
    assert main(["commit", "-m", "detached"]) == 0
    output = capsys.readouterr().out
    second_id = _object_id_from_output(output)

    assert "detached HEAD" in output
    assert resolve_head(repository) == second_id
    assert (repository.git_dir / "refs/heads/main").read_bytes() == branch_before
    assert resolve_branch(repository, "detached-point") == first_id


def test_commit_cli_reports_missing_identity_and_mixed_branch_options(
    tmp_path, monkeypatch, capsys
):
    repository = initialize_repository(tmp_path / "repo")
    monkeypatch.chdir(repository.root)
    (repository.root / "file").write_text("content")
    add_paths(repository, ["file"], cwd=repository.root)

    assert main(["commit", "-m", "message"]) == 1
    assert "identity is required" in capsys.readouterr().err
    assert main(["branch", "--list", "new"]) == 1
    assert "does not accept a branch name" in capsys.readouterr().err
