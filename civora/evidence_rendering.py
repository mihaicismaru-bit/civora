from __future__ import annotations

from dataclasses import dataclass


class EvidenceRenderingError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceRenderingPolicy:
    max_dek_facts: int = 2
    use_authorized_uncertainty_for_next: bool = False


class EvidenceConstrainedRenderer:
    """Render reader-visible factual prose only from an authorized projection.

    The renderer is intentionally conservative. It does not paraphrase, infer
    causality, or reuse signal title/summary text. Reader-visible factual fields
    are assembled verbatim from facts that already passed provenance,
    reconciliation, contradiction, and editorial authorization gates.
    """

    def __init__(self, policy: EvidenceRenderingPolicy | None = None):
        self.policy = policy or EvidenceRenderingPolicy()

    @staticmethod
    def _statements(items: object) -> list[str]:
        if not isinstance(items, list):
            raise EvidenceRenderingError("authorized projection statements must be a list")
        statements: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                raise EvidenceRenderingError("authorized projection item is malformed")
            statement = item.get("statement")
            if not isinstance(statement, str) or not statement.strip():
                raise EvidenceRenderingError("authorized projection contains an empty statement")
            statements.append(statement.strip())
        return statements

    def render(self, authorization: dict) -> dict:
        if not isinstance(authorization, dict):
            raise EvidenceRenderingError("rendering requires an authorized projection")

        facts = self._statements(authorization.get("authorized_facts"))
        if not facts:
            raise EvidenceRenderingError("rendering requires at least one authorized fact")

        uncertain = self._statements(authorization.get("authorized_uncertain_claims", []))
        dek_facts = facts[: max(1, self.policy.max_dek_facts)]

        # Verbatim-only composition keeps the rendering layer from introducing
        # unsupported factual or causal claims. Editorial style can be improved
        # later only by a separately validated evidence-preserving rewriter.
        headline = facts[0]
        dek = " ".join(dek_facts)
        why_it_matters = facts[1] if len(facts) > 1 else facts[0]
        next_text = uncertain[0] if self.policy.use_authorized_uncertainty_for_next and uncertain else None

        return {
            "headline": headline,
            "dek": dek,
            "why_it_matters": why_it_matters,
            "next": next_text,
            "rendering_source": "authorized_projection",
            "authorized_fact_ids": [item.get("fact_id") for item in authorization["authorized_facts"]],
            "authorized_uncertain_claim_ids": [
                item.get("claim_id") for item in authorization.get("authorized_uncertain_claims", [])
            ],
        }
