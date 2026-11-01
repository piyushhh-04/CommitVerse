"""Generate deterministic unified diffs for staged and unstaged changes."""

import difflib
import json
import os

from commitverse_core.objects.store import read_object
from commitverse_core.repository import Repository
from commitverse_core.status import FileState, collect_snapshot


class DiffError(ValueError):
    """Raised when a diff cannot safely represent repository contents."""


def _git_path(prefix: str, path: bytes) -> str:
    text = os.fsdecode(path)
    value = prefix + text
    unsafe = any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or 0xD800 <= ord(character) <= 0xDFFF
        or character.isspace()
        or character in ('"', "\\")
        for character in value
    )
    return json.dumps(value, ensure_ascii=True) if unsafe else value


def _object_payload(repository: Repository, state: FileState) -> bytes:
    object_type, payload = read_object(repository.objects_dir, state.object_id)
    if object_type != "blob":
        raise DiffError(
            f"file object {state.object_id} is {object_type}, not a blob"
        )
    return payload


def _text_lines(payload: bytes) -> list[str] | None:
    if b"\0" in payload:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + (
        [parts[-1]] if parts[-1] else []
    )


def _unified_lines(
    old_payload: bytes,
    new_payload: bytes,
    old_path: str,
    new_path: str,
) -> list[str] | None:
    old_lines = _text_lines(old_payload)
    new_lines = _text_lines(new_payload)
    if old_lines is None or new_lines is None:
        return None

    result: list[str] = []
    for line in difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_path,
        tofile=new_path,
        lineterm="\n",
    ):
        if (
            line
            and line[0] in " +-"
            and not line.startswith(("---", "+++", "@@"))
            and not line.endswith("\n")
        ):
            result.extend((line + "\n", "\\ No newline at end of file\n"))
        else:
            result.append(line)
    return result


def generate_diff(repository: Repository, *, cached: bool = False) -> str:
    """Return a unified diff of index/worktree or HEAD/index, without mutations."""
    snapshot = collect_snapshot(repository, include_untracked=False)
    if cached:
        before = snapshot.head
        after = snapshot.index
        after_payloads: dict[bytes, bytes] = {}
    else:
        before = snapshot.index
        after = snapshot.working_tree
        after_payloads = snapshot.working_payloads

    object_payloads: dict[str, bytes] = {}

    def load_payload(state: FileState) -> bytes:
        if state.object_id in object_payloads:
            return object_payloads[state.object_id]
        payload = _object_payload(repository, state)
        object_payloads[state.object_id] = payload
        return payload

    output: list[str] = []
    for path in sorted(set(before) | set(after)):
        old_state = before.get(path)
        new_state = after.get(path)
        if old_state == new_state:
            continue

        old_payload = b""
        if old_state is not None:
            old_payload = load_payload(old_state)
        new_payload = b""
        if new_state is not None:
            if path in after_payloads:
                new_payload = after_payloads[path]
            else:
                new_payload = load_payload(new_state)

        old_label = _git_path("a/", path)
        new_label = _git_path("b/", path)
        output.append(f"diff --git {old_label} {new_label}\n")
        if old_state is None and new_state is not None:
            output.append(f"new file mode {new_state.mode}\n")
        elif new_state is None and old_state is not None:
            output.append(f"deleted file mode {old_state.mode}\n")
        elif (
            old_state is not None
            and new_state is not None
            and old_state.mode != new_state.mode
        ):
            output.append(f"old mode {old_state.mode}\n")
            output.append(f"new mode {new_state.mode}\n")

        old_id = "0" * 40 if old_state is None else old_state.object_id
        new_id = "0" * 40 if new_state is None else new_state.object_id
        index_line = f"index {old_id[:7]}..{new_id[:7]}"
        if (
            old_state is not None
            and new_state is not None
            and old_state.mode == new_state.mode
        ):
            index_line += f" {old_state.mode}"
        output.append(index_line + "\n")
        old_file_label = "/dev/null" if old_state is None else old_label
        new_file_label = "/dev/null" if new_state is None else new_label

        if old_payload == new_payload:
            continue
        lines = _unified_lines(
            old_payload,
            new_payload,
            old_file_label,
            new_file_label,
        )
        if lines is None:
            output.append(
                f"Binary files {old_file_label} and {new_file_label} differ\n"
            )
        else:
            output.extend(lines)
    return "".join(output)
