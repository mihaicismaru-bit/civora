from __future__ import annotations

from typing import Any, Dict, Mapping

from adapters.semantic_provider import NeedDecisionProvider, SemanticProviderError, build_semantic_packet
from .need_synthesis import promote_decision_set


def run_need_synthesis(
    hypotheses_bundle: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    provider: NeedDecisionProvider,
) -> Dict[str, Any]:
    decisions = []
    provider_errors = []
    provider_calls = []

    for hypothesis in hypotheses_bundle.get("hypotheses", []) or []:
        hypothesis_id = str(hypothesis.get("hypothesis_id") or "")
        if hypothesis.get("status") != "EVIDENCE_AVAILABLE":
            decisions.append({
                "hypothesis_id": hypothesis_id,
                "decision": "insufficient",
                "evidence_ids": list(hypothesis.get("evidence_ids") or []),
                "prohibited_overclaim": hypothesis.get("prohibited_overclaim"),
            })
            continue
        packet = build_semantic_packet(hypothesis, evidence_by_id)
        try:
            decision = dict(provider.decide(packet))
            provider_calls.append(hypothesis_id)
        except Exception as exc:
            provider_errors.append({"hypothesis_id": hypothesis_id, "error": str(exc)})
            decisions.append({
                "hypothesis_id": hypothesis_id,
                "decision": "insufficient",
                "evidence_ids": list(hypothesis.get("evidence_ids") or []),
                "prohibited_overclaim": hypothesis.get("prohibited_overclaim"),
            })
            continue
        decisions.append(decision)

    promoted = promote_decision_set(hypotheses_bundle, decisions, evidence_by_id)
    if provider_errors:
        promoted["state"] = "BLOCKED_SEMANTIC"
        promoted["failures"] = list(promoted.get("failures") or []) + [
            {"failure": "semantic_provider_error", **item} for item in provider_errors
        ]
    promoted["provider_calls"] = provider_calls
    promoted["provider_errors"] = provider_errors
    promoted["policy"] = {
        "provider_receives_only_evidence_bound_packet": True,
        "unready_hypotheses_auto_resolve_to_insufficient": True,
        "provider_error_never_promotes_need": True,
        "causal_fields_forbidden": True,
    }
    return promoted
