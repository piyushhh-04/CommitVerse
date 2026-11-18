"""Lexical repository retrieval with source attribution.

This is an explicitly lexical fallback, not a semantic or embedding search.
"""

from __future__ import annotations

import re
from typing import Iterable


def lexical_rank(
    repository_files: dict[str, str],
    query: str,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_./-]+", query)
        if len(token) >= 2
    ]
    if not tokens:
        return []
    ranked: list[dict[str, object]] = []
    for path, content in sorted(repository_files.items()):
        haystack = f"{path}\n{content}".lower()
        matched = sum(haystack.count(token) for token in tokens)
        if matched == 0:
            continue
        matches: list[dict[str, object]] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if any(token in line.lower() for token in tokens):
                matches.append({"line": line_number, "text": line[:500]})
                if len(matches) >= 5:
                    break
        ranked.append(
            {
                "path": path,
                "score": float(matched),
                "matches": matches,
            }
        )
    ranked.sort(key=lambda item: (-float(item["score"]), str(item["path"])))
    return ranked[:limit]
