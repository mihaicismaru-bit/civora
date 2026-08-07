from __future__ import annotations

from typing import Any, Mapping

from .models import (
    Evidence,
    EvidencePolarity,
    EvidenceRelation,
    FactKernel,
    Signal,
    StoryObject,
    StoryState,
    VerificationStatus,
)


class StoryCodecError(ValueError):
    pass


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StoryCodecError(f"{name} must be an object")
    return value


def story_from_dict(payload: Mapping[str, Any]) -> StoryObject:
    """Rehydrate a StoryObject from a durable checkpoint payload.

    The decoder is explicit and fail-closed: enum values and required nested
    structures are validated by their constructors rather than silently
    defaulted. This makes restart/re-entry use the same durable story snapshot
    that was written before editorial review.
    """
    data = _require_mapping(payload, "story")
    signal_data = _require_mapping(data.get("signal"), "signal")
    kernel_data = _require_mapping(data.get("fact_kernel"), "fact_kernel")

    try:
        signal = Signal(
            title=str(signal_data["title"]),
            summary=str(signal_data["summary"]),
            geography=list(signal_data["geography"]),
            source_ids=list(signal_data["source_ids"]),
            public_interest=float(signal_data["public_interest"]),
            impact=float(signal_data["impact"]),
            novelty=float(signal_data["novelty"]),
            utility=float(signal_data["utility"]),
            factual_risk=float(signal_data["factual_risk"]),
            id=str(signal_data["id"]),
            created_at=str(signal_data["created_at"]),
        )
        evidence = [
            Evidence(
                source_id=str(item["source_id"]),
                claim=str(item["claim"]),
                url=item.get("url"),
                captured_at=str(item["captured_at"]),
                confidence=float(item["confidence"]),
            )
            for item in kernel_data.get("evidence", [])
        ]
        relations = [
            EvidenceRelation(
                target_statement=str(item["target_statement"]),
                source_id=str(item["source_id"]),
                evidence_claim=str(item["evidence_claim"]),
                polarity=EvidencePolarity(item.get("polarity", EvidencePolarity.SUPPORT.value)),
            )
            for item in kernel_data.get("evidence_relations", [])
        ]
        kernel = FactKernel(
            confirmed_facts=list(kernel_data.get("confirmed_facts", [])),
            uncertain_claims=list(kernel_data.get("uncertain_claims", [])),
            affected_groups=list(kernel_data.get("affected_groups", [])),
            next_expected_event=kernel_data.get("next_expected_event"),
            evidence=evidence,
            verification_status=VerificationStatus(kernel_data["verification_status"]),
            evidence_relations=relations,
        )
        return StoryObject(
            signal=signal,
            fact_kernel=kernel,
            state=StoryState(data["state"]),
            source_score=float(data.get("source_score", 0.0)),
            opportunity_score=float(data.get("opportunity_score", 0.0)),
            trust_score=float(data.get("trust_score", 0.0)),
            viral_score=float(data.get("viral_score", 0.0)),
            article=data.get("article"),
            content_pack=data.get("content_pack"),
            id=str(data["id"]),
            version=int(data["version"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StoryCodecError("invalid durable StoryObject payload") from exc
