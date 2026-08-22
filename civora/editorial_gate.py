from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EditorialGateDecision(str, Enum):
    AUTO_DRAFT = "auto_draft"
    REVIEW = "review"


@dataclass(frozen=True)
class EditorialGatePolicy:
    """Policy for automated drafting from durable editorial evidence.

    Production default is deliberately conservative: confirmed facts must be
    corroborated by the reconciliation engine and contradiction analysis must
    be completely clear before automatic drafting is allowed.
    """

    require_corroborated_facts: bool = True


class EditorialGateError(RuntimeError):
    pass


class ConflictResolutionGate:
    """Combine reconciliation and contradiction reports into one draft gate.

    The gate never infers facts itself. It validates that both derived reports
    refer to the same immutable Fact Kernel semantic revision, then converts
    their explicit outcomes into a deterministic editorial decision.
    """

    def __init__(self, policy: EditorialGatePolicy | None = None):
        self.policy = policy or EditorialGatePolicy()

    @staticmethod
    def _validate_alignment(reconciliation_report: dict, contradiction_report: dict) -> None:
        keys = ("story_id", "kernel_id", "kernel_semantic_hash", "kernel_revision")
        for key in keys:
            if reconciliation_report.get(key) != contradiction_report.get(key):
                raise EditorialGateError(f"editorial reports are misaligned on {key}")

    def evaluate(self, reconciliation_report: dict, contradiction_report: dict) -> dict:
        self._validate_alignment(reconciliation_report, contradiction_report)

        reconciliation = reconciliation_report.get("result", {})
        contradiction = contradiction_report.get("result", {})
        reconciliation_gate = reconciliation.get("gate")
        contradiction_gate = contradiction.get("gate")

        if reconciliation_gate not in {
            "corroborated",
            "review_support_strength",
            "needs_review",
        }:
            raise EditorialGateError("unknown reconciliation gate")
        if contradiction_gate not in {"clear", "conflict_review"}:
            raise EditorialGateError("unknown contradiction gate")

        reasons: list[str] = []
        if contradiction_gate != "clear":
            reasons.append("conflict_requires_review")

        if self.policy.require_corroborated_facts:
            if reconciliation_gate != "corroborated":
                reasons.append("fact_support_not_corroborated")
        elif reconciliation_gate == "needs_review":
            reasons.append("fact_support_requires_review")

        contradiction_summary = contradiction.get("summary", {})
        if contradiction_summary.get("disputed_count", 0):
            reasons.append("disputed_fact")
        if contradiction_summary.get("contradicted_count", 0):
            reasons.append("contradicted_fact")
        if contradiction_summary.get("unresolved_count", 0):
            reasons.append("unresolved_conflict")

        # Stable ordering and deduplication keeps the decision auditable.
        reasons = sorted(set(reasons))
        decision = (
            EditorialGateDecision.AUTO_DRAFT
            if not reasons
            else EditorialGateDecision.REVIEW
        )
        return {
            "story_id": reconciliation_report["story_id"],
            "kernel_id": reconciliation_report["kernel_id"],
            "kernel_revision": reconciliation_report["kernel_revision"],
            "kernel_semantic_hash": reconciliation_report["kernel_semantic_hash"],
            "decision": decision.value,
            "reasons": reasons,
            "inputs": {
                "reconciliation_report_id": reconciliation_report["report_id"],
                "contradiction_report_id": contradiction_report["report_id"],
                "reconciliation_gate": reconciliation_gate,
                "contradiction_gate": contradiction_gate,
            },
            "policy": {
                "require_corroborated_facts": self.policy.require_corroborated_facts,
            },
        }
