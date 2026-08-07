import unittest

from civora.authorized_story import AuthorizedStoryBuilder, AuthorizedStoryError


class AuthorizedStoryBuilderTests(unittest.TestCase):
    def setUp(self):
        self.kernel = {
            "kernel_id": "kernel-1",
            "story_id": "story-1",
            "revision": 3,
            "semantic_hash": "hash-1",
            "confirmed_facts": [
                {
                    "fact_id": "fact-good",
                    "statement": "Verified fact.",
                    "evidence_ids": ["ev-1", "ev-2"],
                    "provenance_status": "grounded",
                },
                {
                    "fact_id": "fact-bad",
                    "statement": "Disputed fact.",
                    "evidence_ids": ["ev-3"],
                    "provenance_status": "grounded",
                },
            ],
            "uncertain_claims": [],
        }
        self.reconciliation = {
            "report_id": "rec-1",
            "kernel_id": "kernel-1",
            "story_id": "story-1",
            "kernel_revision": 3,
            "kernel_semantic_hash": "hash-1",
            "result": {
                "fact_assessments": [
                    {
                        "record_id": "fact-good",
                        "status": "corroborated",
                        "confidence": 0.96,
                        "independent_source_count": 2,
                        "source_ids": ["s1", "s2"],
                    },
                    {
                        "record_id": "fact-bad",
                        "status": "single_source",
                        "confidence": 0.75,
                        "independent_source_count": 1,
                        "source_ids": ["s3"],
                    },
                ],
                "claim_assessments": [],
            },
        }
        self.contradiction = {
            "report_id": "con-1",
            "kernel_id": "kernel-1",
            "story_id": "story-1",
            "kernel_revision": 3,
            "kernel_semantic_hash": "hash-1",
            "result": {
                "assessments": [
                    {"record_id": "fact-good", "status": "uncontested"},
                    {"record_id": "fact-bad", "status": "disputed"},
                ]
            },
        }
        self.auto_decision = {
            "decision_id": "decision-auto",
            "kernel_id": "kernel-1",
            "story_id": "story-1",
            "kernel_revision": 3,
            "kernel_semantic_hash": "hash-1",
            "decision": "auto_draft",
            "inputs": {
                "reconciliation_report_id": "rec-1",
                "contradiction_report_id": "con-1",
            },
        }

    def test_projection_contains_only_grounded_corroborated_uncontested_facts(self):
        result = AuthorizedStoryBuilder().build(
            kernel_record=self.kernel,
            reconciliation_report=self.reconciliation,
            contradiction_report=self.contradiction,
            editorial_decision=self.auto_decision,
        )
        self.assertEqual([item["fact_id"] for item in result["authorized_facts"]], ["fact-good"])
        self.assertEqual(result["authorization_mode"], "auto_draft")
        self.assertEqual(result["excluded_facts"][0]["fact_id"], "fact-bad")
        self.assertIn("fact_not_corroborated", result["excluded_facts"][0]["reasons"])
        self.assertIn("fact_not_uncontested", result["excluded_facts"][0]["reasons"])

    def test_review_decision_requires_exact_approved_case(self):
        decision = dict(self.auto_decision)
        decision["decision"] = "review"
        decision["decision_id"] = "decision-review"
        approval = {
            "state": "approved",
            "story_id": "story-1",
            "editorial_decision_id": "decision-review",
            "kernel_semantic_hash": "hash-1",
        }
        result = AuthorizedStoryBuilder().build(
            kernel_record=self.kernel,
            reconciliation_report=self.reconciliation,
            contradiction_report=self.contradiction,
            editorial_decision=decision,
            approval=approval,
        )
        self.assertEqual(result["authorization_mode"], "human_approved")
        self.assertEqual([item["fact_id"] for item in result["authorized_facts"]], ["fact-good"])

    def test_human_approval_does_not_promote_weak_or_disputed_fact(self):
        decision = dict(self.auto_decision)
        decision["decision"] = "review"
        decision["decision_id"] = "decision-review"
        approval = {
            "state": "approved",
            "story_id": "story-1",
            "editorial_decision_id": "decision-review",
            "kernel_semantic_hash": "hash-1",
        }
        kernel = dict(self.kernel)
        kernel["confirmed_facts"] = [self.kernel["confirmed_facts"][1]]
        with self.assertRaisesRegex(AuthorizedStoryError, "no confirmed facts"):
            AuthorizedStoryBuilder().build(
                kernel_record=kernel,
                reconciliation_report=self.reconciliation,
                contradiction_report=self.contradiction,
                editorial_decision=decision,
                approval=approval,
            )

    def test_stale_report_or_approval_fails_closed(self):
        stale = dict(self.reconciliation)
        stale["kernel_semantic_hash"] = "stale"
        with self.assertRaisesRegex(AuthorizedStoryError, "misaligned"):
            AuthorizedStoryBuilder().build(
                kernel_record=self.kernel,
                reconciliation_report=stale,
                contradiction_report=self.contradiction,
                editorial_decision=self.auto_decision,
            )

        decision = dict(self.auto_decision)
        decision["decision"] = "review"
        decision["decision_id"] = "decision-review"
        approval = {
            "state": "approved",
            "story_id": "story-1",
            "editorial_decision_id": "different-decision",
            "kernel_semantic_hash": "hash-1",
        }
        with self.assertRaisesRegex(AuthorizedStoryError, "different editorial decision"):
            AuthorizedStoryBuilder().build(
                kernel_record=self.kernel,
                reconciliation_report=self.reconciliation,
                contradiction_report=self.contradiction,
                editorial_decision=decision,
                approval=approval,
            )


if __name__ == "__main__":
    unittest.main()
