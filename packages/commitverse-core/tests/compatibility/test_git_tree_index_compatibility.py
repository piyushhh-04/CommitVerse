import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from commitverse_core.index import read_index
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import read_tree


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


def _run_git(git_executable, repository, *arguments):
    return subprocess.run(
        [git_executable, "-C", str(repository), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=_git_environment(repository),
    )


def _initialize_repository(git_executable, repository):
    repository.mkdir()
    _run_git(
        git_executable,
        repository,
        "init",
        "--quiet",
        "--initial-branch=main",
        "--object-format=sha1",
    )


def _run_cv(repository, *arguments):
    executable = Path(sys.executable).with_name("cv")
    return subprocess.run(
        [str(executable), *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def test_git_reads_commitverse_index_and_tree(git_executable, tmp_path):
    repository = initialize_repository(tmp_path / "repository")
    (repository.root / "folder").mkdir()
    (repository.root / "folder" / "space name.txt").write_bytes(b"nested\n")
    (repository.root / "root.txt").write_bytes(b"root\x00bytes")

    _run_cv(repository.root, "add", "folder", "root.txt")
    index = read_index(repository.git_dir / "index")
    assert [entry.path for entry in index.entries] == [
        b"folder/space name.txt",
        b"root.txt",
    ]

    staged = _run_git(
        git_executable, repository.root, "ls-files", "--stage"
    ).stdout
    assert b"100644 " in staged
    assert b"\tfolder/space name.txt\n" in staged
    assert b"\troot.txt\n" in staged

    commitverse_tree = _run_cv(repository.root, "write-tree").stdout.decode().strip()
    git_tree = _run_git(git_executable, repository.root, "write-tree").stdout.decode().strip()
    assert git_tree == commitverse_tree

    root_entries = read_tree(repository.objects_dir, commitverse_tree)
    assert [entry.name for entry in root_entries] == [b"folder", b"root.txt"]
    git_listing = _run_git(
        git_executable,
        repository.root,
        "ls-tree",
        "-rz",
        commitverse_tree,
    ).stdout
    assert b"100644 blob " in git_listing
    assert b"\tfolder/space name.txt\0" in git_listing
    assert b"root.txt" in git_listing


def test_commitverse_reads_git_staged_index_and_agrees_on_tree(
    git_executable, tmp_path
):
    repository_path = tmp_path / "repository"
    _initialize_repository(git_executable, repository_path)
    _run_git(git_executable, repository_path, "config", "index.version", "2")
    (repository_path / "nested").mkdir()
    (repository_path / "nested" / "utf-8-\N{SNOWMAN}.txt").write_text(
        "Git staged content\n", encoding="utf-8"
    )
    (repository_path / "space name.txt").write_bytes(b"\x00Git\n")
    _run_git(git_executable, repository_path, "add", "--", ".")

    listed_by_commitverse = _run_cv(repository_path, "ls-files").stdout
    assert listed_by_commitverse == (
        b"nested/utf-8-\xe2\x98\x83.txt\nspace name.txt\n"
    )

    git_tree = _run_git(
        git_executable, repository_path, "write-tree"
    ).stdout.decode().strip()
    commitverse_tree = _run_cv(repository_path, "write-tree").stdout.decode().strip()
    assert commitverse_tree == git_tree
    assert [entry.name for entry in read_tree(repository_path / ".git" / "objects", git_tree)] == [
        b"nested",
        b"space name.txt",
    ]


def test_git_reads_empty_commitverse_index_tree(git_executable, tmp_path):
    repository = initialize_repository(tmp_path / "repository")

    tree_id = _run_cv(repository.root, "write-tree").stdout.decode().strip()
    assert _run_git(
        git_executable, repository.root, "cat-file", "-t", tree_id
    ).stdout == b"tree\n"
    assert _run_git(
        git_executable, repository.root, "cat-file", "-s", tree_id
    ).stdout == b"0\n"


def test_git_reads_executable_and_symlink_tree_modes(git_executable, tmp_path):
    repository = initialize_repository(tmp_path / "repository")
    executable = repository.root / "script"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    (repository.root / "link").symlink_to("script")

    _run_cv(repository.root, "add", "script", "link")
    tree_id = _run_cv(repository.root, "write-tree").stdout.decode().strip()
    git_tree_id = _run_git(
        git_executable, repository.root, "write-tree"
    ).stdout.decode().strip()

    assert tree_id == git_tree_id
    entries = read_tree(repository.objects_dir, tree_id)
    assert [(entry.mode, entry.name) for entry in entries] == [
        ("120000", b"link"),
        ("100755", b"script"),
    ]
