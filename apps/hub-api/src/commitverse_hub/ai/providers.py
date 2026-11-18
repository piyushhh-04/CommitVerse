"""Provider-independent AI engineering interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
import json
import os
import urllib.request
import urllib.error


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


class OllamaProvider(AIProvider):
    """Optional local Ollama adapter. It never enables paid usage."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("COMMITVERSE_OLLAMA_URL")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        self.model = model or os.environ.get("COMMITVERSE_OLLAMA_MODEL") or "qwen2.5-coder:7b"
        self.timeout_seconds = timeout_seconds

    def analyze(
        self,
        repository_files: dict[str, str],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        query = str(request.get("query", "")).strip()
        if not query:
            raise ValueError("AI query is required.")
        context_parts = [
            f"{path}\n{content[:12000]}"
            for path, content in sorted(repository_files.items())[:20]
        ]
        prompt = (
            "Answer using only the repository context below. "
            "Every source claim must include a file path and line number. "
            "Do not claim that a file or function exists unless it appears in context.\n\n"
            f"Repository context:\n{chr(10).join(context_parts)}\n\n"
            f"Question:\n{query}\n"
        )
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                with urllib.request.urlopen(
                    http_request,
                    timeout=self.timeout_seconds,
                ) as response:
                    parsed = json.loads(response.read().decode("utf-8"))
                if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
                    raise RuntimeError("Ollama returned an invalid response.")
                return {
                    "provider": self.name,
                    "model": self.model,
                    "summary": parsed["response"].strip(),
                    "query": query,
                    "references": [],
                    "findings": [],
                }
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
        raise RuntimeError(
            f"Ollama provider unavailable at {self.base_url}: {last_error}"
        )
