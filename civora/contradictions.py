from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import prod

from .fact_kernel import normalize_statement
from .models import EvidencePolarity, EvidenceRelation


class ContradictionStatus(str, Enum):
    UNCONTESTED = "uncontested"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ContradictionPolicy:
    dispute_min_confidence: float = 0.70
    contradiction_min_confidence: float = 0.80
    weak_support_ceiling: float = 0.50

    def __post_init__(self) -> None:
        for value in (
            self.dispute_min_confidence,
            self.contradiction_min_confidence,
            self.weak_support_ceiling,
        ):
            if not 0 <= value <= 1:
                raise ValueError("contradiction thresholds must be between 0 and 1")


class ExplicitContradictionEngine:
    """Evaluate explicit support/contradiction relations without semantic guessing.

    Existing Fact Kernel evidence links count as support. Additional support or
    contradiction is accepted only through ``EvidenceRelation`` objects. A
    relation must resolve both its target statement and evidence identity; an
    unresolved relation raises instead of silently changing the editorial state.
    """

    def __init__(self, policy: ContradictionPolicy | None = None):
        self.policy = policy or ContradictionPolicy()

    @staticmethod
    def _combined(source_support: dict[str, float]) -> float:
        if not source_support:
            return 0.0
        return round(1.0 - prod(1.0 - value for value in source_support.values()), 4)

    @staticmethod
    def _strongest_by_source(evidence_ids: list[str], evidence_map: dict[str, dict]) -> dict[str, float]:
        result: dict[str, float] = {}
        for evidence_id in evidence_ids:
            evidence = evidence_map[evidence_id]
            source_id = str(evidence["source_id"])
            confidence = float(evidence["confidence"])
            result[source_id] = max(result.get(source_id, 0.0), confidence)
        return result

    @staticmethod
    def _target_map(kernel_record: dict) -> dict[str, dict]:
        targets: dict[str, dict] = {}
        for record in [
            *kernel_record.get("confirmed_facts", []),
            *kernel_record.get("uncertain_claims", []),
        ]:
            key = normalize_statement(record["statement"])
            if key in targets:
                raise ValueError("duplicate normalized contradiction target")
            targets[key] = record
        return targets

    @staticmethod
    def _evidence_lookup(kernel_record: dict) -> dict[tuple[str, str], list[dict]]:
        lookup: dict[tuple[str, str], list[dict]] = {}
        for evidence in kernel_record.get("evidence", []):
            key = (
                str(evidence["source_id"]),
                normalize_statement(evidence["claim"]),
            )
            lookup.setdefault(key, []).append(evidence)
        return lookup

    def evaluate(self, kernel_record: dict, relations: list[EvidenceRelation]) -> dict:
        evidence_map = {
            evidence["evidence_id"]: evidence
            for evidence in kernel_record.get("evidence", [])
        }
        target_map = self._target_map(kernel_record)
        evidence_lookup = self._evidence_lookup(kernel_record)

        explicit: dict[str, dict[str, set[str]]] = {}
        normalized_relations = []
        for relation in relations:
            target_key = normalize_statement(relation.target_statement)
            target = target_map.get(target_key)
            if target is None:
                raise ValueError("evidence relation target does not exist in Fact Kernel")
            evidence_key = (
                str(relation.source_id),
                normalize_statement(relation.evidence_claim),
            )
            matches = evidence_lookup.get(evidence_key, [])
            if len(matches) != 1:
                raise ValueError("evidence relation must resolve exactly one evidence record")
            evidence_id = matches[0]["evidence_id"]
            record_id = target.get("fact_id") or target.get("claim_id")
            bucket = explicit.setdefault(
                record_id,
                {"support": set(), "contradict": set()},
            )
            bucket[relation.polarity.value].add(evidence_id)
            normalized_relations.append(
                {
                    "record_id": record_id,
                    "evidence_id": evidence_id,
                    "polarity": relation.polarity.value,
                }
            )

        assessments = []
        for target in [
            *kernel_record.get("confirmed_facts", []),
            *kernel_record.get("uncertain_claims", []),
        ]:
            record_id = target.get("fact_id") or target.get("claim_id")
            bucket = explicit.get(record_id, {"support": set(), "contradict": set()})
            supporting_ids = set(target.get("evidence_ids", [])) | set(bucket["support"])
            contradicting_ids = set(bucket["contradict"])
            if supporting_ids & contradicting_ids:
                raise ValueError("same evidence cannot both support and contradict one target")

            support_by_source = self._strongest_by_source(sorted(supporting_ids), evidence_map)
            contradict_by_source = self._strongest_by_source(sorted(contradicting_ids), evidence_map)
            support_confidence = self._combined(support_by_source)
            contradiction_confidence = self._combined(contradict_by_source)

            if not contradicting_ids:
                status = ContradictionStatus.UNCONTESTED
            elif (
                contradiction_confidence >= self.policy.contradiction_min_confidence
                and support_confidence < self.policy.weak_support_ceiling
            ):
                status = ContradictionStatus.CONTRADICTED
            elif (
                contradiction_confidence >= self.policy.dispute_min_confidence
                and support_confidence >= self.policy.dispute_min_confidence
            ):
                status = ContradictionStatus.DISPUTED
            else:
                status = ContradictionStatus.UNRESOLVED

            assessments.append(
                {
                    "record_id": record_id,
                    "status": status.value,
                    "support_confidence": support_confidence,
                    "contradiction_confidence": contradiction_confidence,
                    "supporting_source_ids": sorted(support_by_source),
                    "contradicting_source_ids": sorted(contradict_by_source),
                    "supporting_evidence_ids": sorted(supporting_ids),
                    "contradicting_evidence_ids": sorted(contradicting_ids),
                }
            )

        disputed = sum(item["status"] == ContradictionStatus.DISPUTED.value for item in assessments)
        contradicted = sum(item["status"] == ContradictionStatus.CONTRADICTED.value for item in assessments)
        unresolved = sum(item["status"] == ContradictionStatus.UNRESOLVED.value for item in assessments)
        gate = "clear" if not (disputed or contradicted or unresolved) else "conflict_review"

        normalized_relations.sort(key=lambda item: (item["record_id"], item["evidence_id"], item["polarity"]))
        return {
            "policy": {
                "dispute_min_confidence": self.policy.dispute_min_confidence,
                "contradiction_min_confidence": self.policy.contradiction_min_confidence,
                "weak_support_ceiling": self.policy.weak_support_ceiling,
            },
            "relations": normalized_relations,
            "assessments": assessments,
            "summary": {
                "target_count": len(assessments),
                "disputed_count": disputed,
                "contradicted_count": contradicted,
                "unresolved_count": unresolved,
            },
            "gate": gate,
        }
