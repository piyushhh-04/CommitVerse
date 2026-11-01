from commitverse_core.cli import main
from commitverse_core.repository import initialize_repository


def _configure_identity(repository):
    with (repository.git_dir / "config").open("a", encoding="utf-8") as config:
        config.write("\n[user]\n\tname = CLI User\n\temail = cli@example.test\n")


def test_status_and_diff_cli_workflow(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    monkeypatch.chdir(repository.root)

    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "On branch main\n" in output
    assert "No commits yet." in output
    assert "working tree clean" in output

    (repository.root / "app.py").write_text("value = 1\n")
    (repository.root / "remove.txt").write_text("remove\n")
    assert main(["add", "app.py", "remove.txt"]) == 0
    assert main(["status"]) == 0
    assert "new file:   app.py" in capsys.readouterr().out
    assert main(["commit", "-m", "initial"]) == 0
    capsys.readouterr()

    (repository.root / "app.py").write_text("value = 2\n")
    (repository.root / "notes.txt").write_text("untracked\n")
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Changes not staged for commit:" in output
    assert "modified:   app.py" in output
    assert "Untracked files:" in output
    assert "notes.txt" in output
    assert main(["diff"]) == 0
    assert "-value = 1\n+value = 2\n" in capsys.readouterr().out

    assert main(["add", "app.py"]) == 0
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "Changes to be committed:" in output
    assert "modified:   app.py" in output
    assert "Changes not staged for commit:" not in output
    assert main(["diff"]) == 0
    assert capsys.readouterr().out == ""
    assert main(["diff", "--cached"]) == 0
    assert "-value = 1\n+value = 2\n" in capsys.readouterr().out

    (repository.root / "app.py").write_text("value = 3\n")
    (repository.root / "remove.txt").unlink()
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert output.count("modified:   app.py") == 2
    assert "deleted:    remove.txt" in output

    assert main(["diff"]) == 0
    assert "-value = 2\n+value = 3\n" in capsys.readouterr().out
    assert main(["diff", "--cached"]) == 0
    assert "-value = 1\n+value = 2\n" in capsys.readouterr().out

    assert main(["add", "-A"]) == 0
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "deleted:    remove.txt" in output
    assert "modified:   app.py" in output
    assert "new file:   notes.txt" in output
    assert "Changes not staged for commit:" not in output
    assert main(["commit", "-m", "update"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "working tree clean" in output


def test_status_and_diff_fail_outside_a_repository(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["status"]) == 1
    assert "no valid CommitVerse repository" in capsys.readouterr().err
    assert main(["diff"]) == 1
    assert "no valid CommitVerse repository" in capsys.readouterr().err


def test_status_identifies_detached_head(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    monkeypatch.chdir(repository.root)
    (repository.root / "file").write_text("content")
    assert main(["add", "file"]) == 0
    assert main(["commit", "-m", "root"]) == 0
    capsys.readouterr()
    object_id = (repository.git_dir / "refs/heads/main").read_text().strip()
    (repository.git_dir / "HEAD").write_text(object_id + "\n", encoding="ascii")

    assert main(["status"]) == 0
    assert f"HEAD detached at {object_id[:12]}" in capsys.readouterr().out
