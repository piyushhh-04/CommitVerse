"""Validated, formatting-preserving repository configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from commitverse_core.repository import Repository


class ConfigurationError(ValueError):
    """Raised when repository configuration is missing or malformed."""


class ConfigurationIOError(ConfigurationError):
    """Raised when configuration cannot be read or written."""


class ConfigurationLockError(ConfigurationIOError):
    """Raised when another process owns the configuration lock."""


class ConfigurationDurabilityError(ConfigurationIOError):
    """Raised when a published configuration cannot be durably synchronized."""


_SECTION_PATTERN = re.compile(
    r'^\[([A-Za-z][A-Za-z0-9.-]*)(?:\s+"((?:\\.|[^"\\])*)")?\]\s*$'
)
_KEY_PATTERN = re.compile(r"^\s*([A-Za-z][A-Za-z0-9._-]*)\s*(?:=(.*))?\s*$")


@dataclass
class _Line:
    text: str
    section: tuple[str, str | None] | None = None
    key: str | None = None
    value: str | None = None


@dataclass
class ConfigurationDocument:
    """A parsed repository config that retains original line formatting."""

    _lines: list[_Line]

    @classmethod
    def read(cls, path: Path) -> "ConfigurationDocument":
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ConfigurationIOError(f"configuration file is missing: {path}") from error
        except (OSError, UnicodeError) as error:
            raise ConfigurationIOError(f"cannot read configuration {path}: {error}") from error
        return cls.parse(content)

    @classmethod
    def parse(cls, content: str) -> "ConfigurationDocument":
        lines: list[_Line] = []
        section: tuple[str, str | None] | None = None
        for number, raw in enumerate(content.splitlines(keepends=True), 1):
            body = raw.removesuffix("\n").removesuffix("\r")
            stripped = body.strip()
            if not stripped or stripped.startswith(("#", ";")):
                lines.append(_Line(raw, section=section))
                continue
            section_match = _SECTION_PATTERN.fullmatch(stripped)
            if section_match:
                subsection = _unescape_subsection(section_match.group(2))
                section = (section_match.group(1), subsection)
                lines.append(_Line(raw, section=section))
                continue
            if section is None:
                raise ConfigurationError(
                    f"configuration key appears before a section on line {number}"
                )
            key_match = _KEY_PATTERN.fullmatch(body)
            if key_match is None:
                raise ConfigurationError(f"invalid configuration syntax on line {number}")
            value = key_match.group(2)
            lines.append(
                _Line(
                    raw,
                    section=section,
                    key=key_match.group(1),
                    value="" if value is None else value.strip(),
                )
            )
        return cls(lines)

    def get_all(
        self, section: str, key: str, *, subsection: str | None = None
    ) -> list[str]:
        target = (section, subsection)
        return [
            line.value or ""
            for line in self._lines
            if line.section == target and line.key == key
        ]

    def get(
        self, section: str, key: str, *, subsection: str | None = None,
        default: str | None = None,
    ) -> str | None:
        values = self.get_all(section, key, subsection=subsection)
        return values[-1] if values else default

    def set(
        self, section: str, key: str, value: str, *,
        subsection: str | None = None,
    ) -> None:
        self._validate_name(section, key, subsection)
        self._validate_value(value)
        matches = [
            line for line in self._lines
            if line.section == (section, subsection) and line.key == key
        ]
        if matches:
            matches[0].text = self._format_key(matches[0].text, key, value)
            matches[0].value = value
            for duplicate in matches[1:]:
                self._lines.remove(duplicate)
            return
        self._append_key(section, key, value, subsection=subsection)

    def add(
        self, section: str, key: str, value: str, *,
        subsection: str | None = None,
    ) -> None:
        self._validate_name(section, key, subsection)
        self._validate_value(value)
        self._append_key(section, key, value, subsection=subsection)

    def remove_key(
        self, section: str, key: str, *, subsection: str | None = None
    ) -> None:
        target = (section, subsection)
        self._lines = [
            line for line in self._lines
            if not (line.section == target and line.key == key)
        ]

    def remove_section(self, section: str, *, subsection: str | None = None) -> None:
        target = (section, subsection)
        indexes = [
            index for index, line in enumerate(self._lines)
            if line.section == target
        ]
        if not indexes:
            return
        first = indexes[0]
        while first > 0 and self._lines[first - 1].section == target:
            first -= 1
        self._lines = [
            line for index, line in enumerate(self._lines)
            if index < first or line.section != target
        ]

    def render(self) -> str:
        return "".join(line.text for line in self._lines)

    def validate(self) -> None:
        parsed = self.parse(self.render())
        if len(parsed._lines) != len(self._lines):
            raise ConfigurationError("configuration changed during validation")

    def _append_key(
        self, section: str, key: str, value: str, *, subsection: str | None
    ) -> None:
        target = (section, subsection)
        section_indexes = [
            index for index, line in enumerate(self._lines)
            if line.section == target and line.key is None
        ]
        rendered = self._format_section(section, subsection)
        indentation = "\t"
        for line in self._lines:
            if line.section == target and line.key is not None:
                indentation = line.text[: len(line.text) - len(line.text.lstrip())]
                break
        new_line = _Line(
            f"{indentation}{key} = {value}\n",
            section=target,
            key=key,
            value=value,
        )
        if section_indexes:
            index = section_indexes[-1] + 1
            while index < len(self._lines) and self._lines[index].section == target:
                index += 1
            self._lines.insert(index, new_line)
            return
        if self._lines and not self._lines[-1].text.endswith("\n"):
            self._lines[-1].text += "\n"
        if self._lines and self._lines[-1].text.strip():
            self._lines.append(_Line("\n", section=target))
        self._lines.extend(
            [_Line(rendered, section=target), new_line]
        )

    @staticmethod
    def _format_section(section: str, subsection: str | None) -> str:
        if subsection is None:
            return f"[{section}]\n"
        escaped = subsection.replace("\\", "\\\\").replace('"', '\\"')
        return f'[{section} "{escaped}"]\n'

    @staticmethod
    def _format_key(original: str, key: str, value: str) -> str:
        newline = "\n" if original.endswith("\n") else ""
        indentation = original[: len(original) - len(original.lstrip())]
        return f"{indentation}{key} = {value}{newline}"

    @staticmethod
    def _validate_name(section: str, key: str, subsection: str | None) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]*", section):
            raise ConfigurationError(f"invalid configuration section: {section!r}")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", key):
            raise ConfigurationError(f"invalid configuration key: {key!r}")
        if subsection is not None and ("\n" in subsection or "\r" in subsection):
            raise ConfigurationError("configuration subsection contains a newline")

    @staticmethod
    def _validate_value(value: str) -> None:
        if "\n" in value or "\r" in value:
            raise ConfigurationError("configuration value contains a newline")


def update_configuration(
    path: Path, mutation: Callable[[ConfigurationDocument], None]
) -> None:
    """Apply a validated mutation using an exclusively-created lock file."""
    lock_path = path.with_name(f"{path.name}.lock")
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError as error:
        raise ConfigurationLockError(f"configuration lock already exists: {lock_path}") from error
    except OSError as error:
        raise ConfigurationIOError(f"cannot create configuration lock {lock_path}: {error}") from error

    replaced = False
    try:
        document = ConfigurationDocument.read(path)
        mutation(document)
        document.validate()
        content = document.render().encode("utf-8")
        with os.fdopen(fd, "wb") as lock:
            fd = -1
            lock.write(content)
            lock.flush()
            os.fsync(lock.fileno())
        os.replace(lock_path, path)
        replaced = True
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            raise ConfigurationDurabilityError(
                f"configuration was replaced but directory durability is uncertain: {error}"
            ) from error
    except ConfigurationError:
        raise
    except (OSError, UnicodeError) as error:
        raise ConfigurationIOError(f"cannot update configuration {path}: {error}") from error
    finally:
        if not replaced:
            try:
                if fd >= 0:
                    os.close(fd)
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def read_repository_configuration(repository: "Repository") -> ConfigurationDocument:
    """Read configuration through the repository's shared Git-directory path."""
    return ConfigurationDocument.read(repository.config_path)


def update_repository_configuration(
    repository: "Repository", mutation: Callable[[ConfigurationDocument], None]
) -> None:
    """Safely mutate configuration for either bare or non-bare repositories."""
    update_configuration(repository.config_path, mutation)


def _unescape_subsection(value: str | None) -> str | None:
    if value is None:
        return None
    result: list[str] = []
    escaped = False
    for character in value:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            result.append(character)
    if escaped:
        raise ConfigurationError("unterminated subsection escape")
    return "".join(result)
