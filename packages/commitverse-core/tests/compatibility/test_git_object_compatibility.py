import os
import shutil
import subprocess

import pytest

from commitverse_core.objects import hash_object, read_object, write_object


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


def _run_git(git_executable, repository, *arguments, input=None):
    return subprocess.run(
        [git_executable, "-C", str(repository), *arguments],
        input=input,
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
    return repository / ".git" / "objects"


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"CommitVerse compatibility\n",
        b"\x00\xffbinary\x00payload",
        "CommitVerse \N{SNOWMAN}".encode("utf-8"),
    ],
    ids=["empty", "text-with-newline", "binary", "utf8"],
)
def test_commitverse_writes_objects_git_can_read(git_executable, tmp_path, payload):
    repository = tmp_path / "repository"
    objects_dir = _initialize_repository(git_executable, repository)

    object_id = write_object(objects_dir, "blob", payload)

    _assert_git_reads_object(git_executable, repository, object_id, "blob", payload)


@pytest.mark.parametrize("object_type", ["tree", "commit"])
def test_commitverse_writes_trees_and_commits_git_can_read(
    git_executable, tmp_path, object_type
):
    repository = tmp_path / "repository"
    objects_dir = _initialize_repository(git_executable, repository)
    empty_tree_payload = b""
    empty_tree_id = write_object(objects_dir, "tree", empty_tree_payload)

    if object_type == "tree":
        object_id = empty_tree_id
        payload = empty_tree_payload
    else:
        payload = (
            f"tree {empty_tree_id}\n"
            "author CommitVerse Compatibility <compat@example.invalid> 0 +0000\n"
            "committer CommitVerse Compatibility <compat@example.invalid> 0 +0000\n"
            "\n"
            "compatibility test\n"
        ).encode("ascii")
        object_id = write_object(objects_dir, object_type, payload)

    _assert_git_reads_object(git_executable, repository, object_id, object_type, payload)


def _assert_git_reads_object(git_executable, repository, object_id, object_type, payload):
    assert _run_git(git_executable, repository, "cat-file", "-t", object_id).stdout == (
        f"{object_type}\n".encode("ascii")
    )
    assert _run_git(git_executable, repository, "cat-file", "-s", object_id).stdout == (
        f"{len(payload)}\n".encode("ascii")
    )
    assert _run_git(git_executable, repository, "cat-file", "-p", object_id).stdout == (
        payload
    )


@pytest.mark.parametrize(
    "object_type",
    ["blob", "tree", "commit"],
)
def test_commitverse_reads_objects_written_by_git(git_executable, tmp_path, object_type):
    repository = tmp_path / "repository"
    objects_dir = _initialize_repository(git_executable, repository)
    if object_type == "blob":
        payload = b"Git-written blob\x00payload"
    elif object_type == "tree":
        payload = b""
    else:
        tree_id = _run_git(
            git_executable,
            repository,
            "hash-object",
            "-w",
            "-t",
            "tree",
            "--stdin",
            input=b"",
        ).stdout.decode("ascii").strip()
        payload = (
            f"tree {tree_id}\n"
            "author CommitVerse Compatibility <compat@example.invalid> 0 +0000\n"
            "committer CommitVerse Compatibility <compat@example.invalid> 0 +0000\n"
            "\n"
            "compatibility test\n"
        ).encode("ascii")

    object_id = _run_git(
        git_executable,
        repository,
        "hash-object",
        "-w",
        "-t",
        object_type,
        "--stdin",
        input=payload,
    ).stdout.decode("ascii").strip()

    assert read_object(objects_dir, object_id) == (object_type, payload)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"plain text",
        b"line one\nline two\n",
        b"\x00\xff\x10binary\x00",
    ],
    ids=["empty", "text", "newline", "binary"],
)
def test_object_id_matches_git_hash_object(git_executable, tmp_path, payload):
    repository = tmp_path / "repository"
    _initialize_repository(git_executable, repository)

    git_object_id = _run_git(
        git_executable,
        repository,
        "hash-object",
        "--stdin",
        input=payload,
    ).stdout.decode("ascii").strip()

    assert hash_object("blob", payload) == git_object_id
