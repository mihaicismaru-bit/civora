from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, Mapping, Protocol, Sequence


class NeedDecisionProvider(Protocol):
    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class SemanticProviderError(RuntimeError):
    """Raised when a semantic provider does not satisfy the structured decision contract."""


def build_semantic_packet(
    hypothesis: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    evidence = []
    for evidence_id in hypothesis.get("evidence_ids", []) or []:
        record = evidence_by_id.get(str(evidence_id))
        if not record:
            continue
        evidence.append({
            "evidence_id": str(evidence_id),
            "source": record.get("source"),
            "source_type": record.get("source_type"),
            "source_family": record.get("source_family"),
            "territory": record.get("territory"),
            "scope": record.get("scope"),
            "period": record.get("period") or record.get("source_date") or record.get("publication_date"),
            "constructs": list(record.get("constructs") or []),
            "direct_measurement": record.get("direct_measurement"),
            "measures": [dict(item) for item in (record.get("measures") or [])],
        })
    return {
        "schema_version": "nf.semantic_need_packet.v0.1",
        "task": "Decide whether the evidence supports a material need. Return only the structured decision; do not create causes or use facts outside this packet.",
        "hypothesis": dict(hypothesis),
        "evidence": evidence,
    }


class CommandNeedDecisionProvider:
    """Thin bridge to an existing semantic/agent command; no LLM implementation lives here."""

    def __init__(self, argv: Sequence[str], *, timeout_seconds: int = 120) -> None:
        if not argv or any(not str(item).strip() for item in argv):
            raise ValueError("semantic provider argv must be non-empty")
        if timeout_seconds <= 0 or timeout_seconds > 900:
            raise ValueError("timeout_seconds must be in 1..900")
        self.argv = [str(item) for item in argv]
        self.timeout_seconds = timeout_seconds

    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            completed = subprocess.run(
                self.argv,
                input=json.dumps(packet, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SemanticProviderError(str(exc)) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "semantic provider failed").strip()
            raise SemanticProviderError(f"provider_exit_{completed.returncode}:{detail[:500]}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SemanticProviderError("semantic_provider_stdout_not_json") from exc
        if not isinstance(result, Mapping):
            raise SemanticProviderError("semantic_provider_result_not_object")
        return result


class StaticNeedDecisionProvider:
    def __init__(self, decisions_by_hypothesis: Mapping[str, Mapping[str, Any]]) -> None:
        self.decisions = {str(key): dict(value) for key, value in decisions_by_hypothesis.items()}
        self.calls = []

    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        hypothesis_id = str((packet.get("hypothesis") or {}).get("hypothesis_id") or "")
        self.calls.append(hypothesis_id)
        if hypothesis_id not in self.decisions:
            raise SemanticProviderError(f"missing_static_decision:{hypothesis_id}")
        return dict(self.decisions[hypothesis_id])
