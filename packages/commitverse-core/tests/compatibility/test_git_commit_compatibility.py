import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from commitverse_core.commits import read_commit, serialize_commit
from commitverse_core.objects import hash_object
from commitverse_core.refs import resolve_head
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import write_tree


@pytest.fixture(scope="session")
def git_executable():
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git executable is required for external compatibility tests")
    return executable


def _environment(home, *, dates=False):
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment["HOME"] = str(home)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if dates:
        environment.update(
            {
                "GIT_AUTHOR_NAME": "Compatibility Author",
                "GIT_AUTHOR_EMAIL": "author@example.test",
                "GIT_COMMITTER_NAME": "Compatibility Committer",
                "GIT_COMMITTER_EMAIL": "committer@example.test",
                "GIT_AUTHOR_DATE": "@1700000000 +0000",
                "GIT_COMMITTER_DATE": "@1700000001 +0000",
            }
        )
    return environment


def _run_git(git_executable, repository, home, *arguments, input_bytes=None, dates=False):
    return subprocess.run(
        [git_executable, "-C", str(repository), *arguments],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=_environment(home, dates=dates),
    )


def _run_cv(repository, *arguments, dates=False):
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    if dates:
        environment.update(
            {
                "GIT_AUTHOR_NAME": "Compatibility Author",
                "GIT_AUTHOR_EMAIL": "author@example.test",
                "GIT_COMMITTER_NAME": "Compatibility Committer",
                "GIT_COMMITTER_EMAIL": "committer@example.test",
                "GIT_AUTHOR_DATE": "@1700000000 +0000",
                "GIT_COMMITTER_DATE": "@1700000001 +0000",
            }
        )
    executable = Path(sys.executable).with_name("cv")
    return subprocess.run(
        [str(executable), *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=environment,
    )


def _object_id_from_output(output):
    match = re.search(rb" ([0-9a-f]{40})\]", output)
    assert match is not None
    return match.group(1).decode("ascii")


def test_git_reads_commitverse_commits_refs_head_and_history(
    git_executable, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    repository = initialize_repository(tmp_path / "repository")
    _run_git(
        git_executable,
        repository.root,
        home,
        "config",
        "user.name",
        "Compatibility Author",
    )
    _run_git(
        git_executable,
        repository.root,
        home,
        "config",
        "user.email",
        "author@example.test",
    )
    (repository.root / "file").write_bytes(b"first\x00snapshot")
    _run_cv(repository.root, "add", "file")
    first_result = _run_cv(repository.root, "commit", "-m", "first \N{SNOWMAN}", dates=True)
    first_id = _object_id_from_output(first_result.stdout)
    first_commit = read_commit(repository.objects_dir, first_id)

    raw_commit = _run_git(
        git_executable, repository.root, home, "cat-file", "-p", first_id
    ).stdout
    assert raw_commit == serialize_commit(first_commit)
    git_generated_id = _run_git(
        git_executable,
        repository.root,
        home,
        "commit-tree",
        first_commit.tree_id,
        "-m",
        "first \N{SNOWMAN}",
        dates=True,
    ).stdout.decode().strip()
    assert git_generated_id == first_id
    assert _run_git(
        git_executable, repository.root, home, "rev-parse", "HEAD"
    ).stdout == f"{first_id}\n".encode()
    assert _run_git(
        git_executable,
        repository.root,
        home,
        "show-ref",
        "--verify",
        "refs/heads/main",
    ).stdout.startswith(first_id.encode())
    assert resolve_head(repository) == first_id
    _run_cv(repository.root, "branch", "compatibility")
    assert _run_git(
        git_executable,
        repository.root,
        home,
        "show-ref",
        "--verify",
        "refs/heads/compatibility",
    ).stdout.startswith(first_id.encode())

    (repository.root / "file").write_bytes(b"second snapshot")
    _run_cv(repository.root, "add", "file")
    second_result = _run_cv(repository.root, "commit", "-m", "second", dates=True)
    second_id = _object_id_from_output(second_result.stdout)
    second_commit = read_commit(repository.objects_dir, second_id)
    assert second_commit.parent_ids == (first_id,)
    assert second_commit.tree_id != first_commit.tree_id

    git_log = _run_git(
        git_executable, repository.root, home, "log", "--format=%H%n%T%n%P%n%s"
    ).stdout.decode()
    assert git_log.startswith(
        f"{second_id}\n{second_commit.tree_id}\n{first_id}\nsecond\n"
    )
    assert _run_git(
        git_executable, repository.root, home, "log", "--format=%H"
    ).stdout.splitlines() == [second_id.encode(), first_id.encode()]


def test_commitverse_reads_git_generated_commit_history_and_refs(
    git_executable, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    repository = initialize_repository(tmp_path / "repository")
    tree_id = write_tree(repository.objects_dir, [])
    _run_git(
        git_executable,
        repository.root,
        home,
        "config",
        "user.name",
        "Git Author",
    )
    _run_git(
        git_executable,
        repository.root,
        home,
        "config",
        "user.email",
        "git@example.test",
    )
    root_id = _run_git(
        git_executable,
        repository.root,
        home,
        "commit-tree",
        tree_id,
        "-m",
        "Git root \N{SNOWMAN}",
        dates=True,
    ).stdout.decode().strip()
    _run_git(
        git_executable,
        repository.root,
        home,
        "update-ref",
        "refs/heads/main",
        root_id,
    )
    child_id = _run_git(
        git_executable,
        repository.root,
        home,
        "commit-tree",
        tree_id,
        "-p",
        root_id,
        "-m",
        "Git child",
        dates=True,
    ).stdout.decode().strip()
    _run_git(
        git_executable,
        repository.root,
        home,
        "update-ref",
        "refs/heads/main",
        child_id,
    )

    commit = read_commit(repository.objects_dir, child_id)
    assert commit.parent_ids == (root_id,)
    assert hash_object("commit", serialize_commit(commit)) == child_id
    assert resolve_head(repository) == child_id
    assert _run_cv(repository.root, "rev-parse", "HEAD").stdout == f"{child_id}\n".encode()

    output = _run_cv(repository.root, "log").stdout.decode("utf-8")
    assert output.index(f"commit {child_id}") < output.index(f"commit {root_id}")
    assert "Git child" in output
    assert "Git root \N{SNOWMAN}" in output
    assert f"Parents: {root_id}" in output
