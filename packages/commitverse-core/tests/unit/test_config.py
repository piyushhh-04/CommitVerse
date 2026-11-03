import pytest

from commitverse_core.config import (
    ConfigurationDurabilityError,
    ConfigurationError,
    ConfigurationIOError,
    ConfigurationLockError,
    ConfigurationDocument,
    update_configuration,
    update_repository_configuration,
)
from commitverse_core.repository import initialize_repository


def test_configuration_preserves_comments_sections_and_repeated_values():
    document = ConfigurationDocument.parse(
        "# header\n"
        "[remote \"origin\"]\n"
        "\turl = ../server.git\n"
        "\tfetch = first\n"
        "\tfetch = second\n"
        "\n"
        "[user]\n"
        "name = Existing\n"
    )

    assert document.get("remote", "url", subsection="origin") == "../server.git"
    assert document.get_all("remote", "fetch", subsection="origin") == [
        "first",
        "second",
    ]
    document.set("user", "name", "Updated")
    document.add("remote", "fetch", "third", subsection="origin")

    rendered = document.render()
    assert "# header\n" in rendered
    assert "\tfetch = first\n\tfetch = second\n" in rendered
    assert "\tfetch = third\n" in rendered
    assert "name = Updated\n" in rendered


def test_configuration_mutations_remove_keys_and_sections():
    document = ConfigurationDocument.parse(
        "[core]\n"
        "bare = false\n"
        "filemode = true\n"
        "\n"
        "[user]\n"
        "name = User\n"
    )

    document.remove_key("core", "filemode")
    document.remove_section("user")

    assert document.get("core", "bare") == "false"
    assert document.get("core", "filemode") is None
    assert document.get("user", "name") is None
    assert "[user]" not in document.render()


@pytest.mark.parametrize(
    "content",
    [
        "key = value\n",
        "[core\nbare = false\n",
        "[core]\ninvalid key = value\n",
        "[core \"unterminated]\nvalue = x\n",
    ],
)
def test_configuration_rejects_malformed_syntax(content):
    with pytest.raises(ConfigurationError):
        ConfigurationDocument.parse(content)


def test_configuration_rejects_unsafe_mutation_values():
    document = ConfigurationDocument.parse("[core]\n")

    with pytest.raises(ConfigurationError):
        document.set("core", "value", "line one\nline two")


def test_configuration_update_is_atomic_and_preserves_unrelated_content(tmp_path):
    path = tmp_path / "config"
    original = "[core]\nrepositoryformatversion = 0\nbare = false\n# keep me\n"
    path.write_text(original)

    update_configuration(path, lambda config: config.set("core", "bare", "true"))

    assert path.read_text() == (
        "[core]\nrepositoryformatversion = 0\nbare = true\n# keep me\n"
    )
    assert not path.with_name("config.lock").exists()


def test_configuration_lock_collision_preserves_original(tmp_path):
    path = tmp_path / "config"
    path.write_text("[core]\nbare = false\n")
    lock_path = tmp_path / "config.lock"
    lock_path.write_text("owned by another process")

    with pytest.raises(ConfigurationLockError):
        update_configuration(path, lambda config: config.set("core", "bare", "true"))

    assert path.read_text() == "[core]\nbare = false\n"
    assert lock_path.read_text() == "owned by another process"


def test_configuration_replacement_failure_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / "config"
    path.write_text("[core]\nbare = false\n")

    def fail_replace(source, destination):
        raise OSError("injected replacement failure")

    monkeypatch.setattr("commitverse_core.config.os.replace", fail_replace)

    with pytest.raises(ConfigurationIOError, match="cannot update configuration"):
        update_configuration(path, lambda config: config.set("core", "bare", "true"))

    assert path.read_text() == "[core]\nbare = false\n"
    assert not path.with_name("config.lock").exists()


def test_configuration_reports_post_replacement_durability_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "config"
    path.write_text("[core]\nbare = false\n")
    real_fsync = __import__("os").fsync
    calls = 0

    def fail_directory_fsync(file_descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        real_fsync(file_descriptor)

    monkeypatch.setattr("commitverse_core.config.os.fsync", fail_directory_fsync)

    with pytest.raises(ConfigurationDurabilityError):
        update_configuration(path, lambda config: config.set("core", "bare", "true"))

    assert "bare = true" in path.read_text()
    assert not path.with_name("config.lock").exists()


def test_repository_configuration_works_for_bare_and_non_bare(tmp_path):
    non_bare = initialize_repository(tmp_path / "project")
    bare = initialize_repository(tmp_path / "server.git", bare=True)

    update_repository_configuration(
        non_bare, lambda config: config.set("user", "name", "Worktree User")
    )
    update_repository_configuration(
        bare,
        lambda config: config.set("remote", "url", "../other.git", subsection="origin"),
    )

    assert non_bare.config_path.read_text().endswith(
        "[user]\n\tname = Worktree User\n"
    )
    assert 'remote "origin"' in bare.config_path.read_text()
