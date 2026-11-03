import subprocess
import sys
from pathlib import Path

import pytest

from commitverse_core.cli import main
from commitverse_core.objects import hash_object
from commitverse_core.repository import initialize_repository


def test_init_command_initializes_and_reinitializes_repository(tmp_path, capsys):
    repository_path = tmp_path / "project"

    assert main(["init", str(repository_path)]) == 0
    first_output = capsys.readouterr()
    assert "Initialized CommitVerse repository" in first_output.out
    assert (repository_path / ".git" / "HEAD").is_file()

    assert main(["init", str(repository_path)]) == 0
    second_output = capsys.readouterr()
    assert "Reinitialized CommitVerse repository" in second_output.out
    assert second_output.err == ""


def test_init_command_defaults_to_current_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["init"]) == 0

    assert (tmp_path / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"
    assert "Initialized CommitVerse repository" in capsys.readouterr().out


def test_init_bare_command_supports_spaces_and_reinitialization(
    tmp_path, capsys
):
    repository_path = tmp_path / "bare server.git"

    assert main(["init", "--bare", str(repository_path)]) == 0
    first_output = capsys.readouterr()
    assert "Initialized bare CommitVerse repository" in first_output.out
    assert (repository_path / "HEAD").read_text() == "ref: refs/heads/main\n"
    assert not (repository_path / ".git").exists()

    assert main(["init", "--bare", str(repository_path)]) == 0
    second_output = capsys.readouterr()
    assert "Reinitialized bare CommitVerse repository" in second_output.out


def test_worktree_commands_reject_bare_repository(
    tmp_path, monkeypatch, capsys
):
    repository = initialize_repository(tmp_path / "bare.git", bare=True)
    monkeypatch.chdir(repository.root)

    assert main(["add", "-A"]) == 1
    assert "requires a working tree" in capsys.readouterr().err
    assert main(["status"]) == 1
    assert "requires a working tree" in capsys.readouterr().err


def test_cv_console_script_initializes_repository(tmp_path):
    repository_path = tmp_path / "console-repository"
    executable = Path(sys.executable).with_name("cv")

    result = subprocess.run(
        [str(executable), "init", str(repository_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert b"Initialized CommitVerse repository" in result.stdout
    assert (repository_path / ".git" / "HEAD").read_text() == "ref: refs/heads/main\n"


@pytest.mark.parametrize(
    "payload",
    [b"", b"text with a newline\n", b"\x00\xffbinary\x00payload"],
    ids=["empty", "text", "binary"],
)
def test_hash_and_cat_file_commands_round_trip_bytes(
    tmp_path, monkeypatch, capsysbinary, payload
):
    repository = initialize_repository(tmp_path / "repository")
    monkeypatch.chdir(repository.root)
    file_path = repository.root / "input.bin"
    file_path.write_bytes(payload)

    assert main(["hash-object", "-w", file_path.name]) == 0
    object_id = capsysbinary.readouterr().out.decode("ascii").strip()
    assert object_id == hash_object("blob", payload)
    assert (repository.objects_dir / object_id[:2] / object_id[2:]).is_file()

    assert main(["cat-file", "-t", object_id]) == 0
    assert capsysbinary.readouterr().out == b"blob\n"

    assert main(["cat-file", "-s", object_id]) == 0
    assert capsysbinary.readouterr().out == f"{len(payload)}\n".encode("ascii")

    assert main(["cat-file", "-p", object_id]) == 0
    assert capsysbinary.readouterr().out == payload


def test_hash_object_reports_missing_file(tmp_path, monkeypatch, capsys):
    initialize_repository(tmp_path / "repository")
    monkeypatch.chdir(tmp_path / "repository")

    assert main(["hash-object", "-w", "missing.txt"]) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert "cv: error:" in result.err
    assert "missing.txt" in result.err


def test_hash_object_requires_repository(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outside.txt").write_text("content")

    assert main(["hash-object", "-w", "outside.txt"]) == 1
    assert "no valid CommitVerse repository" in capsys.readouterr().err


@pytest.mark.parametrize("object_id", ["invalid", "A" * 40, "0" * 40])
def test_cat_file_reports_invalid_or_missing_object(
    tmp_path, monkeypatch, capsys, object_id
):
    initialize_repository(tmp_path / "repository")
    monkeypatch.chdir(tmp_path / "repository")

    assert main(["cat-file", "-t", object_id]) == 1
    assert "cv: error:" in capsys.readouterr().err


def test_multiple_repositories_store_objects_independently(
    tmp_path, monkeypatch, capsysbinary
):
    first_repository = initialize_repository(tmp_path / "first")
    second_repository = initialize_repository(tmp_path / "second")
    payload = b"same content"

    for repository in (first_repository, second_repository):
        file_path = repository.root / "input"
        file_path.write_bytes(payload)
        monkeypatch.chdir(repository.root)
        assert main(["hash-object", "-w", str(file_path)]) == 0
        assert capsysbinary.readouterr().out.strip() == hash_object(
            "blob", payload
        ).encode()

    object_id = hash_object("blob", payload)
    assert (first_repository.objects_dir / object_id[:2] / object_id[2:]).is_file()
    assert (second_repository.objects_dir / object_id[:2] / object_id[2:]).is_file()
