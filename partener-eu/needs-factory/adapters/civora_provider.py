from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, Mapping, Protocol, Sequence


class DiscoveryProvider(Protocol):
    def discover(self, task: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        ...


class CivoraProviderError(RuntimeError):
    """Raised when the external CIVORA provider cannot return a valid receipt envelope."""


class CivoraCommandProvider:
    """Thin process bridge to an existing CIVORA discovery command.

    The bridge does not implement crawling. It sends one canonical research task as
    JSON on stdin and expects {"receipts": [...]} on stdout. argv is passed directly
    to subprocess without a shell, avoiding an additional command interpreter.
    """

    def __init__(self, argv: Sequence[str], *, timeout_seconds: int = 120) -> None:
        if not argv or any(not str(item).strip() for item in argv):
            raise ValueError("CIVORA provider argv must contain at least one non-empty element")
        if timeout_seconds <= 0 or timeout_seconds > 900:
            raise ValueError("timeout_seconds must be in 1..900")
        self.argv = [str(item) for item in argv]
        self.timeout_seconds = timeout_seconds

    def discover(self, task: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        payload = {
            "schema_version": "nf.civora_discovery_request.v0.1",
            "task": dict(task),
        }
        try:
            completed = subprocess.run(
                self.argv,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CivoraProviderError(str(exc)) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "provider failed").strip()
            raise CivoraProviderError(f"provider_exit_{completed.returncode}:{detail[:500]}")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CivoraProviderError("provider_stdout_not_json") from exc
        if response.get("schema_version") not in {"nf.civora_discovery_response.v0.1", None}:
            raise CivoraProviderError("unsupported_provider_response_schema")
        receipts = response.get("receipts")
        if not isinstance(receipts, list):
            raise CivoraProviderError("provider_response_missing_receipts_list")
        return receipts


class StaticDiscoveryProvider:
    """Deterministic provider used only for tests/fixtures, never as project evidence by itself."""

    def __init__(self, receipts_by_requirement: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
        self.receipts_by_requirement = {
            str(key): [dict(item) for item in value]
            for key, value in receipts_by_requirement.items()
        }
        self.calls = []

    def discover(self, task: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        requirement_id = str(task.get("requirement_id") or "")
        self.calls.append(requirement_id)
        return [dict(item) for item in self.receipts_by_requirement.get(requirement_id, [])]
