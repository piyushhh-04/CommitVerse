import shutil
import subprocess

import pytest

from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.push import push_to_local
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
    return subprocess.run(
        [git_executable, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env={"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )


def test_git_reads_commitverse_pushed_objects_and_history(git_executable, tmp_path):
    source = initialize_repository(tmp_path / "source")
    identity = CommitIdentity("Push", "push@example.test", 1_700_000_000, 0)
    commit_id = write_commit(
        source.objects_dir,
        Commit(write_tree(source.objects_dir, []), (), identity, identity, b"pushed\n"),
    )
    compare_and_swap_ref(source, "refs/heads/main", None, commit_id)
    destination = initialize_repository(tmp_path / "destination.git", bare=True)

    push_to_local(source, destination.root, source_branch="main")

    assert _run_git(
        git_executable,
        "--git-dir",
        str(destination.git_dir),
        "rev-parse",
        "refs/heads/main",
    ).stdout == f"{commit_id}\n".encode()
    assert _run_git(
        git_executable,
        "--git-dir",
        str(destination.git_dir),
        "cat-file",
        "-t",
        commit_id,
    ).stdout == b"commit\n"
