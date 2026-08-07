import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.editorial_gate import ConflictResolutionGate, EditorialGateError
from civora.models import (
    Evidence,
    EvidencePolarity,
    EvidenceRelation,
    FactKernel,
    Signal,
    Source,
    StoryObject,
    StoryState,
)
from civora.orchestrator import Orchestrator
from civora.review import ReviewQueue


class EditorialGateTests(unittest.TestCase):
    def aligned_reports(self, reconciliation_gate="corroborated", contradiction_gate="clear"):
        base = {
            "story_id": "story-1",
            "kernel_id": "kernel-1",
            "kernel_revision": 1,
            "kernel_semantic_hash": "a" * 64,
        }
        reconciliation = {
            **base,
            "report_id": "recon-1",
            "result": {"gate": reconciliation_gate, "summary": {}},
        }
        contradiction = {
            **base,
            "report_id": "contra-1",
            "result": {
                "gate": contradiction_gate,
                "summary": {
                    "disputed_count": 0,
                    "contradicted_count": 0,
                    "unresolved_count": 0,
                },
            },
        }
        return reconciliation, contradiction

    def test_clear_corroborated_reports_allow_auto_draft(self):
        reconciliation, contradiction = self.aligned_reports()
        result = ConflictResolutionGate().evaluate(reconciliation, contradiction)
        self.assertEqual(result["decision"], "auto_draft")
        self.assertEqual(result["reasons"], [])

    def test_conflict_blocks_auto_draft(self):
        reconciliation, contradiction = self.aligned_reports(contradiction_gate="conflict_review")
        contradiction["result"]["summary"]["disputed_count"] = 1
        result = ConflictResolutionGate().evaluate(reconciliation, contradiction)
        self.assertEqual(result["decision"], "review")
        self.assertIn("disputed_fact", result["reasons"])

    def test_weak_support_blocks_under_production_default(self):
        reconciliation, contradiction = self.aligned_reports(reconciliation_gate="review_support_strength")
        result = ConflictResolutionGate().evaluate(reconciliation, contradiction)
        self.assertEqual(result["decision"], "review")
        self.assertIn("fact_support_not_corroborated", result["reasons"])

    def test_misaligned_reports_fail_closed(self):
        reconciliation, contradiction = self.aligned_reports()
        contradiction["kernel_semantic_hash"] = "b" * 64
        with self.assertRaises(EditorialGateError):
            ConflictResolutionGate().evaluate(reconciliation, contradiction)

    def test_orchestrator_routes_explicit_dispute_to_review_before_drafting(self):
        s1 = Source("A", "official", ["Vâlcea"], .95, .95, .95, .95, .95, .05)
        s2 = Source("B", "official", ["Vâlcea"], .95, .95, .95, .95, .95, .05)
        s3 = Source("C", "official", ["Vâlcea"], .95, .95, .95, .95, .95, .05)
        fact = "Drumul este deschis traficului."
        contradicting = "Drumul este închis traficului."
        signal = Signal(
            title="Situație trafic",
            summary="Sursele raportează situația traficului.",
            geography=["Vâlcea"],
            source_ids=[s1.id, s2.id, s3.id],
            public_interest=.8,
            impact=.8,
            novelty=.5,
            utility=.8,
            factual_risk=.2,
        )
        kernel = FactKernel(
            confirmed_facts=[fact],
            uncertain_claims=[],
            affected_groups=["șoferi"],
            next_expected_event=None,
            evidence=[
                Evidence(s1.id, fact, confidence=.9),
                Evidence(s2.id, fact, confidence=.9),
                Evidence(s3.id, contradicting, confidence=.9),
            ],
            evidence_relations=[
                EvidenceRelation(
                    target_statement=fact,
                    source_id=s3.id,
                    evidence_claim=contradicting,
                    polarity=EvidencePolarity.CONTRADICT,
                )
            ],
        )
        story = StoryObject(signal=signal, fact_kernel=kernel)
        with TemporaryDirectory() as td:
            root = Path(td)
            queue = ReviewQueue(root / "review.json")
            result = Orchestrator(root, review_queue=queue).run(
                story, {s1.id: s1, s2.id: s2, s3.id: s3}
            )
            self.assertEqual(result.state, StoryState.BLOCKED)
            self.assertIsNone(result.article)
            self.assertEqual(len(queue.pending()), 1)
            self.assertIn("editorial_gate:", queue.pending()[0]["reason"])


if __name__ == "__main__":
    unittest.main()
