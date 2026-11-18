"""Provider-independent AI engineering interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    @abstractmethod
    def analyze(self, repository_files: dict[str, str], request: dict[str, Any]) -> dict[str, Any]:
        """Produce grounded analysis or raise a provider-specific error."""


class DeterministicLocalProvider(AIProvider):
    """Local, credential-free repository analysis based on explicit source evidence."""

    name = "deterministic_local"

    def analyze(self, repository_files: dict[str, str], request: dict[str, Any]) -> dict[str, Any]:
        query = str(request.get("query", "")).strip().lower()
        findings: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        for path, content in sorted(repository_files.items()):
            lines = content.splitlines()
            for line_number, line in enumerate(lines, start=1):
                stripped = line.strip()
                if query and any(token in stripped.lower() for token in query.split()):
                    references.append({"path": path, "line": line_number, "text": stripped[:500]})
                    if len(references) >= 50:
                        break
            if len(references) >= 50:
                break
        return {
            "provider": self.name,
            "summary": "No external model was used; results are based only on indexed source text.",
            "query": query,
            "references": references,
            "findings": findings,
        }
