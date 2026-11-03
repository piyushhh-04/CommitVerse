import os
import shutil
import subprocess

import pytest

from commitverse_core.transport import LocalFilesystemTransport


@pytest.fixture
def git_executable():
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git executable is required for external compatibility tests")
    return executable


def _run_git(git_executable, *arguments):
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    return subprocess.run(
        [git_executable, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=environment,
    )


def test_advertises_git_created_bare_repository(git_executable, tmp_path):
    repository = tmp_path / "git remote.git"
    _run_git(git_executable, "init", "--bare", str(repository))

    advertisement = LocalFilesystemTransport.open(repository).advertise()

    assert advertisement.repository.bare
    assert advertisement.head_symbolic_ref == "refs/heads/master"
    assert advertisement.head_target is None


def test_advertises_git_created_non_bare_repository(git_executable, tmp_path):
    repository = tmp_path / "git remote"
    _run_git(git_executable, "init", str(repository))

    advertisement = LocalFilesystemTransport.open(repository).advertise()

    assert not advertisement.repository.bare
    assert advertisement.head_symbolic_ref == "refs/heads/master"
    assert advertisement.head_target is None
