from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import prod
from typing import Iterable


class ReconciliationStatus(str, Enum):
    CORROBORATED = "corroborated"
    SINGLE_SOURCE = "single_source"
    WEAKLY_SUPPORTED = "weakly_supported"
    UNSUPPORTED = "unsupported"
    CANDIDATE_CORROBORATED = "candidate_corroborated"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class ReconciliationPolicy:
    corroboration_min_sources: int = 2
    corroboration_min_confidence: float = 0.80
    single_source_min_confidence: float = 0.70

    def __post_init__(self) -> None:
        if self.corroboration_min_sources < 2:
            raise ValueError("corroboration_min_sources must be at least 2")
        for value in (
            self.corroboration_min_confidence,
            self.single_source_min_confidence,
        ):
            if not 0 <= value <= 1:
                raise ValueError("confidence thresholds must be between 0 and 1")


class ClaimEvidenceReconciler:
    """Deterministic support aggregation for already-linked evidence.

    The reconciler never edits evidence and never performs fuzzy semantic
    matching. It evaluates only evidence IDs already linked by the Fact Kernel.
    Evidence from the same source counts once, using that source's strongest
    confidence value. Cross-source support is combined as
    ``1 - Π(1-confidence)``.
    """

    def __init__(self, policy: ReconciliationPolicy | None = None):
        self.policy = policy or ReconciliationPolicy()

    @staticmethod
    def _source_support(
        evidence_ids: Iterable[str],
        evidence_map: dict[str, dict],
    ) -> dict[str, float]:
        support: dict[str, float] = {}
        for evidence_id in evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if evidence is None:
                continue
            source_id = str(evidence["source_id"])
            confidence = float(evidence["confidence"])
            support[source_id] = max(support.get(source_id, 0.0), confidence)
        return support

    @staticmethod
    def _combined_confidence(source_support: dict[str, float]) -> float:
        if not source_support:
            return 0.0
        value = 1.0 - prod(1.0 - confidence for confidence in source_support.values())
        return round(value, 4)

    def _assess(
        self,
        *,
        record_id: str,
        evidence_ids: list[str],
        evidence_map: dict[str, dict],
        uncertain: bool,
    ) -> dict:
        source_support = self._source_support(evidence_ids, evidence_map)
        source_ids = sorted(source_support)
        confidence = self._combined_confidence(source_support)
        source_count = len(source_ids)

        if uncertain:
            if (
                source_count >= self.policy.corroboration_min_sources
                and confidence >= self.policy.corroboration_min_confidence
            ):
                status = ReconciliationStatus.CANDIDATE_CORROBORATED
            else:
                status = ReconciliationStatus.UNCERTAIN
        elif source_count == 0:
            status = ReconciliationStatus.UNSUPPORTED
        elif (
            source_count >= self.policy.corroboration_min_sources
            and confidence >= self.policy.corroboration_min_confidence
        ):
            status = ReconciliationStatus.CORROBORATED
        elif (
            source_count == 1
            and confidence >= self.policy.single_source_min_confidence
        ):
            status = ReconciliationStatus.SINGLE_SOURCE
        else:
            status = ReconciliationStatus.WEAKLY_SUPPORTED

        return {
            "record_id": record_id,
            "status": status.value,
            "confidence": confidence,
            "independent_source_count": source_count,
            "source_ids": source_ids,
            "evidence_ids": sorted(evidence_ids),
        }

    def reconcile(
        self,
        *,
        confirmed_facts: list[dict],
        uncertain_claims: list[dict],
        evidence: list[dict],
    ) -> dict:
        evidence_map = {
            item["evidence_id"]: item
            for item in evidence
        }
        fact_assessments = [
            self._assess(
                record_id=fact["fact_id"],
                evidence_ids=list(fact.get("evidence_ids", [])),
                evidence_map=evidence_map,
                uncertain=False,
            )
            for fact in confirmed_facts
        ]
        claim_assessments = [
            self._assess(
                record_id=claim["claim_id"],
                evidence_ids=list(claim.get("evidence_ids", [])),
                evidence_map=evidence_map,
                uncertain=True,
            )
            for claim in uncertain_claims
        ]

        corroborated = sum(
            assessment["status"] == ReconciliationStatus.CORROBORATED.value
            for assessment in fact_assessments
        )
        unsupported = sum(
            assessment["status"] == ReconciliationStatus.UNSUPPORTED.value
            for assessment in fact_assessments
        )
        candidates = sum(
            assessment["status"]
            == ReconciliationStatus.CANDIDATE_CORROBORATED.value
            for assessment in claim_assessments
        )

        if unsupported:
            gate = "needs_review"
        elif fact_assessments and corroborated == len(fact_assessments):
            gate = "corroborated"
        elif fact_assessments:
            gate = "review_support_strength"
        else:
            gate = "needs_review"

        return {
            "policy": {
                "corroboration_min_sources": self.policy.corroboration_min_sources,
                "corroboration_min_confidence": self.policy.corroboration_min_confidence,
                "single_source_min_confidence": self.policy.single_source_min_confidence,
            },
            "fact_assessments": fact_assessments,
            "claim_assessments": claim_assessments,
            "summary": {
                "confirmed_fact_count": len(fact_assessments),
                "corroborated_fact_count": corroborated,
                "unsupported_fact_count": unsupported,
                "candidate_corroborated_claim_count": candidates,
            },
            "gate": gate,
        }
