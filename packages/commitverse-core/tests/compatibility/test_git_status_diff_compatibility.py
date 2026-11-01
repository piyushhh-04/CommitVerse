import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from commitverse_core.repository import initialize_repository
from commitverse_core.status import get_status


@pytest.fixture(scope="session")
def git_executable():
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git executable is required for external compatibility tests")
    return executable


def _git_environment(home):
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment["HOME"] = str(home)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _run_git(git_executable, repository, home, *arguments):
    return subprocess.run(
        [git_executable, "-C", str(repository), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=_git_environment(home),
    )


def _run_cv(repository, *arguments):
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    return subprocess.run(
        [str(Path(sys.executable).with_name("cv")), *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=environment,
    )


def test_status_and_diff_agree_with_git_for_staged_and_unstaged_paths(
    git_executable, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    repository = initialize_repository(tmp_path / "repository")
    _run_git(git_executable, repository.root, home, "config", "user.name", "Compat")
    _run_git(
        git_executable,
        repository.root,
        home,
        "config",
        "user.email",
        "compat@example.test",
    )
    (repository.root / "alpha.txt").write_text("alpha before\n")
    (repository.root / "beta.txt").write_text("beta before\n")
    (repository.root / "removed.txt").write_text("to remove\n")
    _run_cv(repository.root, "add", "-A")
    _run_cv(repository.root, "commit", "-m", "initial")

    (repository.root / "alpha.txt").write_text("alpha working\n")
    (repository.root / "beta.txt").write_text("beta staged\n")
    _run_cv(repository.root, "add", "beta.txt")
    (repository.root / "beta.txt").write_text("beta working\n")
    (repository.root / "removed.txt").unlink()
    (repository.root / "new.txt").write_text("untracked\n")

    monkeypatch.chdir(repository.root)
    status = get_status(repository)
    git_status = _run_git(
        git_executable,
        repository.root,
        home,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    records = [record for record in git_status.split(b"\0") if record]
    git_staged = {record[3:] for record in records if record[:1] not in (b" ", b"?")}
    git_unstaged = {
        record[3:] for record in records if record[1:2] not in (b" ", b"?")
    }
    git_untracked = {record[3:] for record in records if record.startswith(b"?? ")}

    assert {change.path for change in status.staged} == git_staged == {b"beta.txt"}
    assert {change.path for change in status.unstaged} == git_unstaged == {
        b"alpha.txt",
        b"beta.txt",
        b"removed.txt",
    }
    assert set(status.untracked) == git_untracked == {b"new.txt"}

    git_unstaged_diff = _run_git(
        git_executable, repository.root, home, "diff", "--name-only"
    ).stdout.splitlines()
    git_staged_diff = _run_git(
        git_executable, repository.root, home, "diff", "--cached", "--name-only"
    ).stdout.splitlines()
    assert git_unstaged_diff == [b"alpha.txt", b"beta.txt", b"removed.txt"]
    assert git_staged_diff == [b"beta.txt"]
    assert [change.path for change in status.unstaged] == git_unstaged_diff
    assert [change.path for change in status.staged] == git_staged_diff

    assert b"Binary files" not in _run_cv(repository.root, "diff").stdout
    assert b"diff --git" in _run_cv(repository.root, "diff", "--cached").stdout
