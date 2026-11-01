from commitverse_core.commit_service import create_commit
from commitverse_core.diff import generate_diff
from commitverse_core.repository import initialize_repository
from commitverse_core.staging import add_paths


def _configure_identity(repository):
    with (repository.git_dir / "config").open("a", encoding="utf-8") as config:
        config.write("\n[user]\n\tname = Diff User\n\temail = diff@example.test\n")


def _commit_files(repository, files):
    for path, payload in files.items():
        target = repository.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    add_paths(repository, all=True, cwd=repository.root)
    return create_commit(
        repository,
        "snapshot",
        environment={
            "GIT_AUTHOR_NAME": "Diff User",
            "GIT_AUTHOR_EMAIL": "diff@example.test",
            "GIT_COMMITTER_NAME": "Diff User",
            "GIT_COMMITTER_EMAIL": "diff@example.test",
        },
    )


def test_unstaged_text_diff_and_staged_diff_are_separate(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(
        repository,
        {"file.txt": b"first\nold value\nlast\n", "removed.txt": b"remove\n"},
    )
    (repository.root / "file.txt").write_bytes(b"first\nnew value\nlast\n")
    add_paths(repository, ["file.txt"], cwd=repository.root)
    (repository.root / "file.txt").write_bytes(b"first\nworking value\nlast\n")
    (repository.root / "removed.txt").unlink()

    unstaged = generate_diff(repository)
    cached = generate_diff(repository, cached=True)

    assert "diff --git a/file.txt b/file.txt\n" in unstaged
    assert "-new value\n+working value\n" in unstaged
    assert "deleted file mode 100644\n" in unstaged
    assert "-remove\n" in unstaged
    assert "-old value\n+new value\n" in cached
    assert "working value" not in cached


def test_text_addition_deletion_empty_file_and_unicode(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(repository, {"deleted.txt": b"remove\n"})
    (repository.root / "added.txt").write_bytes("snowman \N{SNOWMAN}\n".encode())
    (repository.root / "empty.txt").write_bytes(b"")
    (repository.root / "deleted.txt").unlink()
    add_paths(repository, ["added.txt", "empty.txt"], cwd=repository.root)

    diff = generate_diff(repository)
    cached = generate_diff(repository, cached=True)

    assert "new file mode 100644\n" in cached
    assert "deleted file mode 100644\n" in diff
    assert "+snowman \N{SNOWMAN}\n" in cached
    assert "diff --git a/added.txt b/added.txt\n" in cached
    assert "diff --git a/empty.txt b/empty.txt\n" in cached
    assert "Binary files" not in diff


def test_diff_preserves_missing_final_newline_markers(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(repository, {"file.txt": b"old"})
    (repository.root / "file.txt").write_bytes(b"new")

    diff = generate_diff(repository)

    assert "-old\n\\ No newline at end of file\n" in diff
    assert "+new\n\\ No newline at end of file\n" in diff


def test_binary_files_are_not_decoded_as_text(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(repository, {"binary": b"\x00\xff"})
    (repository.root / "binary").write_bytes(b"\x00\xfe")

    diff = generate_diff(repository)

    assert "Binary files a/binary and b/binary differ\n" in diff
    assert "\ufffd" not in diff


def test_mode_only_change_is_reported_without_content_hunks(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(repository, {"script": b"echo hi\n"})
    (repository.root / "script").chmod(0o755)

    diff = generate_diff(repository)

    assert "old mode 100644\nnew mode 100755\n" in diff
    assert "@@" not in diff


def test_no_changes_and_untracked_files_produce_no_diff(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(repository, {"tracked": b"same\n"})
    (repository.root / "untracked").write_text("not included")

    assert generate_diff(repository) == ""
    assert generate_diff(repository, cached=True) == ""


def test_empty_blob_addition_is_reported_even_without_hunks(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository.root / "empty").write_bytes(b"")
    add_paths(repository, ["empty"], cwd=repository.root)

    diff = generate_diff(repository, cached=True)

    assert "new file mode 100644\n" in diff
    assert "diff --git a/empty b/empty\n" in diff
    assert "@@" not in diff


def test_untracked_files_are_excluded_but_staged_and_working_changes_are_not(
    tmp_path,
):
    repository = initialize_repository(tmp_path / "repo")
    _configure_identity(repository)
    _commit_files(repository, {"tracked": b"before\n"})
    (repository.root / "tracked").write_bytes(b"staged\n")
    add_paths(repository, ["tracked"], cwd=repository.root)
    (repository.root / "tracked").write_bytes(b"working\n")
    (repository.root / "untracked").write_text("ignored by diff")

    unstaged = generate_diff(repository)
    cached = generate_diff(repository, cached=True)

    assert "-staged\n+working\n" in unstaged
    assert "-before\n+staged\n" in cached
    assert "untracked" not in unstaged + cached
