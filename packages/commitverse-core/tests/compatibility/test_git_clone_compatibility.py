import os
import shutil
import subprocess

import pytest

from commitverse_core.clone import clone_from_local


@pytest.fixture
def git_executable():
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git executable is required for external compatibility tests")
    return executable


def _run_git(git_executable, *arguments, cwd=None):
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    return subprocess.run(
        [git_executable, *arguments],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=environment,
    )


def test_clone_git_created_non_bare_repository(git_executable, tmp_path):
    source = tmp_path / "git source"
    _run_git(git_executable, "init", "-b", "master", str(source))
    _run_git(git_executable, "config", "user.name", "Clone Test", cwd=source)
    _run_git(git_executable, "config", "user.email", "clone@example.test", cwd=source)
    (source / "readme.txt").write_text("hello\n")
    _run_git(git_executable, "add", "readme.txt", cwd=source)
    _run_git(git_executable, "commit", "-m", "initial", cwd=source)

    destination = tmp_path / "clone"
    result = clone_from_local(source, destination)

    assert result.branch == "master"
    assert _run_git(git_executable, "status", "--porcelain", cwd=destination).stdout == b""
    assert _run_git(
        git_executable, "rev-parse", "--abbrev-ref", "HEAD", cwd=destination
    ).stdout == b"master\n"
    assert (destination / "readme.txt").read_text() == "hello\n"


def test_clone_git_created_bare_repository(git_executable, tmp_path):
    source_worktree = tmp_path / "source"
    bare_source = tmp_path / "source.git"
    _run_git(git_executable, "init", "-b", "main", str(source_worktree))
    _run_git(git_executable, "config", "user.name", "Clone Test", cwd=source_worktree)
    _run_git(git_executable, "config", "user.email", "clone@example.test", cwd=source_worktree)
    (source_worktree / "file.txt").write_text("bare source\n")
    _run_git(git_executable, "add", "file.txt", cwd=source_worktree)
    _run_git(git_executable, "commit", "-m", "initial", cwd=source_worktree)
    _run_git(git_executable, "init", "--bare", str(bare_source))
    _run_git(git_executable, "push", str(bare_source), "main", cwd=source_worktree)

    destination = tmp_path / "bare-clone"
    clone_from_local(bare_source, destination, branch="main")

    assert _run_git(git_executable, "status", "--porcelain", cwd=destination).stdout == b""
    assert (destination / "file.txt").read_text() == "bare source\n"
