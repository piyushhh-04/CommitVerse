import os
import shutil
import subprocess

import pytest

from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.fetch import fetch_from_local
from commitverse_core.refs import compare_and_swap_ref
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import write_tree


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


def test_git_reads_fetched_objects_and_remote_tracking_ref(git_executable, tmp_path):
    remote = initialize_repository(tmp_path / "remote.git", bare=True)
    identity = CommitIdentity("Fetch", "fetch@example.test", 1_700_000_000, 0)
    commit_id = write_commit(
        remote.objects_dir,
        Commit(
            write_tree(remote.objects_dir, []),
            (),
            identity,
            identity,
            b"fetched\n",
        ),
    )
    compare_and_swap_ref(remote, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    fetch_from_local(destination, remote.root, branches=["main"])

    assert _run_git(
        git_executable,
        "--git-dir",
        str(destination.git_dir),
        "cat-file",
        "-t",
        commit_id,
    ).stdout == b"commit\n"
    assert _run_git(
        git_executable,
        "--git-dir",
        str(destination.git_dir),
        "show-ref",
        "--verify",
        "refs/remotes/origin/main",
    ).stdout.startswith(commit_id.encode())
