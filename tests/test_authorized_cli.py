from __future__ import annotations

from io import StringIO
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civora.cli import EXIT_ERROR, EXIT_OK, main


class AuthorizedStoryCliTests(unittest.TestCase):
    @staticmethod
    def _projection() -> dict:
        return {
            "story_id": "story-1",
            "kernel_id": "kernel-1",
            "kernel_revision": 3,
            "kernel_semantic_hash": "a" * 64,
            "editorial_decision_id": "decision-1",
            "authorization_mode": "auto_draft",
            "authorized_facts": [
                {
                    "fact_id": "fact-safe",
                    "statement": "The council approved the measure.",
                    "evidence_ids": ["evidence-1", "evidence-2"],
                    "confidence": 0.94,
                    "independent_source_count": 2,
                    "source_ids": ["source-a", "source-b"],
                    "reconciliation_status": "corroborated",
                    "contradiction_status": "uncontested",
                }
            ],
            "authorized_uncertain_claims": [],
            "excluded_facts": [
                {
                    "fact_id": "fact-excluded",
                    "statement": "The project will start tomorrow.",
                    "reasons": ["fact_not_uncontested"],
                }
            ],
            "policy": {
                "require_grounded_provenance": True,
                "require_corroborated_facts_for_auto": True,
                "allow_human_review_support_statuses": [
                    "corroborated", "single_source", "weakly_supported"
                ],
                "require_uncontested_facts": True,
                "allow_candidate_uncertain_claims": True,
            },
        }

    @patch("civora.cli.AuthorizedStoryBuilder.build")
    @patch("civora.cli.EditorialApprovalStore.load_story")
    @patch("civora.cli.EditorialGateStore.load_story")
    @patch("civora.cli.FactContradictionStore.load_story")
    @patch("civora.cli.FactReconciliationStore.load_story")
    @patch("civora.cli.FactKernelStore.load_story")
    def test_authorized_story_exposes_authorized_and_excluded_facts(
        self,
        load_kernel,
        load_reconciliation,
        load_contradictions,
        load_gate,
        load_approval,
        build_projection,
    ) -> None:
        load_kernel.return_value = {"story_id": "story-1"}
        load_reconciliation.return_value = {"story_id": "story-1"}
        load_contradictions.return_value = {"story_id": "story-1"}
        load_gate.return_value = {"story_id": "story-1", "decision": "auto_draft"}
        load_approval.return_value = None
        build_projection.return_value = self._projection()

        with TemporaryDirectory() as tmp:
            output = StringIO()
            code = main(["--state-dir", tmp, "authorized-story", "story-1"], output=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["authorization_mode"], "auto_draft")
        self.assertEqual(payload["authorized_fact_count"], 1)
        self.assertEqual(payload["excluded_fact_count"], 1)
        self.assertEqual(payload["authorized_facts"][0]["fact_id"], "fact-safe")
        self.assertEqual(
            payload["excluded_facts"][0]["reasons"], ["fact_not_uncontested"]
        )
        build_projection.assert_called_once()

    def test_authorized_story_missing_durable_chain_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            output = StringIO()
            code = main(["--state-dir", tmp, "authorized-story", "missing"], output=output)
        payload = json.loads(output.getvalue())
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("authorization projection unavailable", payload["error"])
        self.assertIn("fact_kernel", payload["error"])
        self.assertIn("editorial_gate", payload["error"])


if __name__ == "__main__":
    unittest.main()
