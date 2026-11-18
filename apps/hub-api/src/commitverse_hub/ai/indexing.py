"""Permission-bound repository text indexing foundation."""

from __future__ import annotations

import ast
from pathlib import Path

_TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".md"}
_IGNORED_PARTS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv"}


def index_repository_text(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if any(part in _IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        result[path.relative_to(root).as_posix()] = text
    return result


def extract_python_symbols(root: Path) -> dict[str, list[str]]:
    symbols: dict[str, list[str]] = {}
    for path, text in index_repository_text(root).items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
        symbols[path] = sorted(set(names))
    return symbols
