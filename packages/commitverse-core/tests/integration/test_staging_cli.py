from commitverse_core.cli import main
from commitverse_core.index import read_index
from commitverse_core.index import Index, IndexEntry, IndexStat, write_index
from commitverse_core.objects import hash_object
from commitverse_core.repository import initialize_repository
from commitverse_core.trees import read_tree


def test_add_write_tree_and_ls_files_commands(tmp_path, monkeypatch, capsysbinary):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "nested").mkdir()
    (repository.root / "nested" / "space name.txt").write_bytes(b"payload")
    (repository.root / "root.txt").write_bytes(b"root")
    monkeypatch.chdir(repository.root)

    assert main(["add", "nested", "root.txt"]) == 0
    assert main(["ls-files"]) == 0
    assert capsysbinary.readouterr().out == b"nested/space name.txt\nroot.txt\n"

    assert main(["write-tree"]) == 0
    root_id = capsysbinary.readouterr().out.decode().strip()
    entries = read_tree(repository.objects_dir, root_id)
    assert [entry.name for entry in entries] == [b"nested", b"root.txt"]


def test_add_all_command_stages_changes_and_write_tree_empty_index(tmp_path, monkeypatch, capsysbinary):
    repository = initialize_repository(tmp_path / "repo")
    monkeypatch.chdir(repository.root)

    assert main(["write-tree"]) == 0
    empty_tree_id = capsysbinary.readouterr().out.decode().strip()
    assert empty_tree_id == hash_object("tree", b"")

    (repository.root / "file").write_text("before")
    assert main(["add", "file"]) == 0
    (repository.root / "file").write_text("after")
    (repository.root / "new").write_text("new")
    assert main(["add", "-A"]) == 0

    entries = read_index(repository.git_dir / "index").entries
    assert [entry.path for entry in entries] == [b"file", b"new"]
    assert main(["ls-files"]) == 0
    assert capsysbinary.readouterr().out == b"file\nnew\n"


def test_add_reports_missing_paths_and_requires_arguments(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    monkeypatch.chdir(repository.root)

    assert main(["add"]) == 1
    assert "requires one or more paths or -A" in capsys.readouterr().err
    assert main(["add", "missing"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_write_tree_reports_unmerged_index_entries(tmp_path, monkeypatch, capsys):
    repository = initialize_repository(tmp_path / "repo")
    write_index(
        repository.git_dir / "index",
        Index(
            (
                IndexEntry(
                    b"conflict",
                    "1" * 40,
                    IndexStat(mode=0o100644),
                    stage=2,
                ),
            )
        ),
    )
    monkeypatch.chdir(repository.root)

    assert main(["write-tree"]) == 1
    assert "unmerged" in capsys.readouterr().err


def test_repositories_keep_staging_indexes_isolated(tmp_path, monkeypatch):
    first = initialize_repository(tmp_path / "first")
    second = initialize_repository(tmp_path / "second")
    (first.root / "file").write_text("first")
    (second.root / "file").write_text("second")

    monkeypatch.chdir(first.root)
    assert main(["add", "file"]) == 0
    monkeypatch.chdir(second.root)
    assert main(["add", "file"]) == 0

    first_entry = read_index(first.git_dir / "index").entries[0]
    second_entry = read_index(second.git_dir / "index").entries[0]
    assert first_entry.object_id != second_entry.object_id
