import pytest

from commitverse_core.commits import Commit, CommitIdentity, write_commit
from commitverse_core.objects import write_object
from commitverse_core.refs import compare_and_swap_ref
from commitverse_core.repository import initialize_repository
from commitverse_core.transport import LocalFilesystemTransport, TransportError
from commitverse_core.trees import write_tree


def _commit(repository, message=b"commit\n", parents=()):
    identity = CommitIdentity("Transport", "transport@example.test", 1_700_000_000, 0)
    return write_commit(
        repository.objects_dir,
        Commit(write_tree(repository.objects_dir, []), tuple(parents), identity, identity, message),
    )


def test_advertises_bare_branches_tags_and_symbolic_head(tmp_path):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(repository)
    compare_and_swap_ref(repository, "refs/heads/main", None, commit_id)
    compare_and_swap_ref(repository, "refs/heads/zeta", None, commit_id)
    compare_and_swap_ref(repository, "refs/tags/v1", None, commit_id)

    advertisement = LocalFilesystemTransport.open(repository.root).advertise()

    assert [reference.name for reference in advertisement.branches] == [
        "refs/heads/main",
        "refs/heads/zeta",
    ]
    assert [reference.name for reference in advertisement.tags] == ["refs/tags/v1"]
    assert advertisement.head_symbolic_ref == "refs/heads/main"
    assert advertisement.head_target == commit_id


def test_advertises_non_bare_repository_and_spaces_in_path(tmp_path):
    repository = initialize_repository(tmp_path / "remote with spaces")
    commit_id = _commit(repository)
    compare_and_swap_ref(repository, "refs/heads/main", None, commit_id)

    advertisement = LocalFilesystemTransport.open(str(repository.root)).advertise()

    assert advertisement.repository.bare is False
    assert advertisement.branches[0].object_id == commit_id


def test_relative_path_requires_explicit_base_and_resolves_from_base(tmp_path):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)

    with pytest.raises(TransportError, match="explicit base"):
        LocalFilesystemTransport.open("remote.git")

    transport = LocalFilesystemTransport.open("remote.git", base=tmp_path)
    assert transport.repository.root == repository.root


def test_invalid_paths_and_arbitrary_directories_are_rejected(tmp_path):
    with pytest.raises(TransportError, match="invalid local remote"):
        LocalFilesystemTransport.open(tmp_path / "missing.git")
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    with pytest.raises(TransportError):
        LocalFilesystemTransport.open(ordinary)


def test_empty_unborn_head_has_no_target(tmp_path):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)

    advertisement = LocalFilesystemTransport.open(repository.root).advertise()

    assert advertisement.head_symbolic_ref == "refs/heads/main"
    assert advertisement.head_target is None


def test_missing_head_is_rejected(tmp_path):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)
    repository.head_path.unlink()

    with pytest.raises(TransportError, match="HEAD"):
        LocalFilesystemTransport.open(repository.root)


@pytest.mark.parametrize(
    "head_contents",
    ["ref: refs/../escape\n", "not-a-head\n"],
)
def test_invalid_or_dangling_head_is_rejected(tmp_path, head_contents):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)
    repository.head_path.write_text(head_contents, encoding="ascii")

    with pytest.raises(TransportError, match="HEAD"):
        LocalFilesystemTransport.open(repository.root).advertise()


def test_dangling_and_non_commit_branch_refs_are_rejected(tmp_path):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)
    repository.head_path.write_text("ref: refs/heads/main\n", encoding="ascii")
    (repository.git_dir / "refs/heads/main").write_text("f" * 40 + "\n", encoding="ascii")

    with pytest.raises(TransportError, match="invalid remote reference"):
        LocalFilesystemTransport.open(repository.root).advertise()

    blob_id = write_object(repository.objects_dir, "blob", b"blob")
    (repository.git_dir / "refs/heads/main").write_text(blob_id + "\n", encoding="ascii")
    with pytest.raises(TransportError, match="does not target a commit"):
        LocalFilesystemTransport.open(repository.root).advertise()


def test_advertisement_does_not_create_or_modify_remote_files(tmp_path):
    repository = initialize_repository(tmp_path / "remote.git", bare=True)
    commit_id = _commit(repository)
    compare_and_swap_ref(repository, "refs/heads/main", None, commit_id)
    before = {
        path.relative_to(repository.git_dir): path.read_bytes()
        for path in repository.git_dir.rglob("*")
        if path.is_file()
    }

    LocalFilesystemTransport.open(repository.root).advertise()

    after = {
        path.relative_to(repository.git_dir): path.read_bytes()
        for path in repository.git_dir.rglob("*")
        if path.is_file()
    }
    assert after == before
