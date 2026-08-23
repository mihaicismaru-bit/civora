import unittest

from civora.editorial_remediation import EditorialRemediationPlanner


class EditorialRemediationPlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = EditorialRemediationPlanner()

    def test_healthy_report_requires_no_action(self):
        plan = self.planner.plan({"status": "healthy", "mismatches": [], "recoverable_mismatches": []})
        self.assertEqual(plan["classification"], "no_action")
        self.assertTrue(plan["safe_to_automate"])
        self.assertEqual(plan["actions"], [])

    def test_prepared_transaction_mismatch_is_recoverable_only(self):
        plan = self.planner.plan(
            {
                "status": "pending_transaction",
                "mismatches": [],
                "recoverable_mismatches": [
                    {
                        "type": "approval_queue_state_mismatch",
                        "story_id": "story-1",
                        "case_id": "case-1",
                        "transaction_ids": ["tx-1"],
                    }
                ],
            }
        )
        self.assertEqual(plan["classification"], "automatic_recovery_available")
        self.assertTrue(plan["safe_to_automate"])
        self.assertEqual(plan["actions"][0]["operation"], "startup_transaction_replay")
        self.assertEqual(plan["actions"][0]["transaction_ids"], ["tx-1"])
        self.assertIn(["transaction", "tx-1"], plan["actions"][0]["inspection_commands"])

    def test_committed_divergence_is_never_auto_repaired(self):
        plan = self.planner.plan(
            {
                "status": "degraded",
                "recoverable_mismatches": [],
                "mismatches": [
                    {
                        "type": "committed_resolution_not_reflected",
                        "story_id": "story-1",
                        "case_id": "case-1",
                        "transaction_id": "tx-1",
                    }
                ],
            }
        )
        self.assertEqual(plan["classification"], "manual_investigation_required")
        self.assertFalse(plan["safe_to_automate"])
        self.assertEqual(plan["actions"][0]["severity"], "fail_closed")
        self.assertEqual(plan["actions"][0]["operation"], "operator_investigation")
        self.assertIn(["editorial-story", "story-1"], plan["actions"][0]["inspection_commands"])
        self.assertIn(["approval-case", "case-1"], plan["actions"][0]["inspection_commands"])
        self.assertIn(["transaction", "tx-1"], plan["actions"][0]["inspection_commands"])

    def test_any_unrecoverable_mismatch_dominates_mixed_report(self):
        plan = self.planner.plan(
            {
                "status": "degraded",
                "recoverable_mismatches": [
                    {"type": "approval_queue_state_mismatch", "story_id": "story-1", "transaction_ids": ["tx-1"]}
                ],
                "mismatches": [
                    {"type": "transaction_story_mismatch", "case_id": "case-2", "transaction_id": "tx-2"}
                ],
            }
        )
        self.assertEqual(plan["classification"], "manual_investigation_required")
        self.assertFalse(plan["safe_to_automate"])
        self.assertEqual(len(plan["actions"]), 2)


if __name__ == "__main__":
    unittest.main()
