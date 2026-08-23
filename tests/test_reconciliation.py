import unittest

from civora.reconciliation import (
    ClaimEvidenceReconciler,
    ReconciliationPolicy,
)


class ClaimEvidenceReconcilerTests(unittest.TestCase):
    def evidence(self):
        return [
            {
                "evidence_id": "e1",
                "source_id": "source-a",
                "confidence": 0.80,
            },
            {
                "evidence_id": "e2",
                "source_id": "source-b",
                "confidence": 0.75,
            },
            {
                "evidence_id": "e3",
                "source_id": "source-a",
                "confidence": 0.95,
            },
        ]

    def test_two_independent_sources_corroborate_fact(self):
        result = ClaimEvidenceReconciler().reconcile(
            confirmed_facts=[{"fact_id": "f1", "evidence_ids": ["e1", "e2"]}],
            uncertain_claims=[],
            evidence=self.evidence(),
        )
        assessment = result["fact_assessments"][0]
        self.assertEqual(assessment["status"], "corroborated")
        self.assertEqual(assessment["independent_source_count"], 2)
        self.assertGreaterEqual(assessment["confidence"], 0.80)
        self.assertEqual(result["gate"], "corroborated")

    def test_same_source_is_not_false_corroboration(self):
        result = ClaimEvidenceReconciler().reconcile(
            confirmed_facts=[{"fact_id": "f1", "evidence_ids": ["e1", "e3"]}],
            uncertain_claims=[],
            evidence=self.evidence(),
        )
        assessment = result["fact_assessments"][0]
        self.assertEqual(assessment["status"], "single_source")
        self.assertEqual(assessment["independent_source_count"], 1)
        self.assertEqual(assessment["confidence"], 0.95)

    def test_unlinked_fact_is_unsupported(self):
        result = ClaimEvidenceReconciler().reconcile(
            confirmed_facts=[{"fact_id": "f1", "evidence_ids": []}],
            uncertain_claims=[],
            evidence=self.evidence(),
        )
        self.assertEqual(
            result["fact_assessments"][0]["status"],
            "unsupported",
        )
        self.assertEqual(result["gate"], "needs_review")

    def test_uncertain_claim_can_be_candidate_corroborated_without_mutation(self):
        claim = {"claim_id": "c1", "evidence_ids": ["e1", "e2"]}
        result = ClaimEvidenceReconciler().reconcile(
            confirmed_facts=[],
            uncertain_claims=[claim],
            evidence=self.evidence(),
        )
        assessment = result["claim_assessments"][0]
        self.assertEqual(assessment["status"], "candidate_corroborated")
        self.assertEqual(claim, {"claim_id": "c1", "evidence_ids": ["e1", "e2"]})

    def test_missing_evidence_reference_does_not_inflate_support(self):
        result = ClaimEvidenceReconciler().reconcile(
            confirmed_facts=[{"fact_id": "f1", "evidence_ids": ["missing"]}],
            uncertain_claims=[],
            evidence=self.evidence(),
        )
        assessment = result["fact_assessments"][0]
        self.assertEqual(assessment["status"], "unsupported")
        self.assertEqual(assessment["confidence"], 0.0)

    def test_policy_validation(self):
        with self.assertRaises(ValueError):
            ReconciliationPolicy(corroboration_min_sources=1)
        with self.assertRaises(ValueError):
            ReconciliationPolicy(corroboration_min_confidence=1.1)


if __name__ == "__main__":
    unittest.main()
