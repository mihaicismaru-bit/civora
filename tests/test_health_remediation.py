import unittest
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.cli import EXIT_OK, EXIT_UNHEALTHY, main
from civora.editorial_approval import EditorialApprovalStore
from civora.editorial_resolution import EditorialResolutionCoordinator
from civora.health import UnifiedHealthInspector
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class HealthRemediationTests(unittest.TestCase):
    @staticmethod
    def _decision(story_id="story-1"):
        return {
            "decision": "review",
            "decision_id": "decision-1",
            "story_id": story_id,
            "kernel_semantic_hash": "a" * 64,
        }

    @staticmethod
    def _paths(root: Path):
        return (
            root / "editorial_approval.json",
            root / "review_queue.json",
            root / "transactions.json",
        )

    @staticmethod
    def _health(root: Path):
        approval, review, transactions = HealthRemediationTests._paths(root)
        return UnifiedHealthInspector(
            editorial_approval_path=approval,
            review_queue_path=review,
            transaction_journal_path=transactions,
        ).inspect()

    @staticmethod
    def _consistency_component(report):
        return next(item for item in report.components if item.name == "editorial_consistency")

    def _prepare_resolution_divergence(self, root: Path, *, committed: bool):
        approval_path, review_path, transaction_path = self._paths(root)
        approval = EditorialApprovalStore(approval_path)
        review = ReviewQueue(review_path)
        journal = TransactionJournal(transaction_path)
        case = approval.ensure_pending(self._decision())
        review.enqueue_payload("story-1", {"id": "story-1"}, "editorial_gate:review")
        payload = {
            "case_id": case["case_id"],
            "story_id": "story-1",
            "action": "approved",
            "actor": "editor",
            "reason": "verified manually",
            "review_queue_required": True,
        }
        journal.prepare(EditorialResolutionCoordinator.OPERATION, payload, tx_id="tx-1")
        approval.decide(
            case["case_id"], action="approved", actor="editor", reason="verified manually"
        )
        if committed:
            journal.commit("tx-1")

    def test_healthy_unified_health_contains_no_action_guidance(self):
        with TemporaryDirectory() as td:
            report = self._health(Path(td))
            component = self._consistency_component(report)

            self.assertEqual(report.status, "healthy")
            self.assertEqual(component.status, "healthy")
            self.assertEqual(component.details["remediation"]["classification"], "no_action")
            self.assertTrue(component.details["remediation"]["safe_to_automate"])

    def test_recoverable_crash_window_contains_automatic_recovery_guidance(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._prepare_resolution_divergence(root, committed=False)

            report = self._health(root)
            component = self._consistency_component(report)
            remediation = component.details["remediation"]

            self.assertEqual(component.status, "pending_transaction")
            self.assertEqual(remediation["classification"], "automatic_recovery_available")
            self.assertTrue(remediation["safe_to_automate"])
            self.assertEqual(remediation["actions"][0]["operation"], "startup_transaction_replay")
            self.assertEqual(remediation["actions"][0]["transaction_ids"], ["tx-1"])

    def test_committed_divergence_contains_manual_fail_closed_guidance(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._prepare_resolution_divergence(root, committed=True)

            report = self._health(root)
            component = self._consistency_component(report)
            remediation = component.details["remediation"]

            self.assertEqual(report.status, "degraded")
            self.assertEqual(component.status, "degraded")
            self.assertEqual(remediation["classification"], "manual_investigation_required")
            self.assertFalse(remediation["safe_to_automate"])
            self.assertTrue(all(not action["safe_to_automate"] for action in remediation["actions"]))

    def test_primary_health_cli_exposes_remediation_without_second_policy(self):
        with TemporaryDirectory() as td:
            output = StringIO()
            code = main(["--state-dir", td, "health"], output=output)
            payload = json.loads(output.getvalue())
            consistency = next(
                item for item in payload["components"] if item["name"] == "editorial_consistency"
            )

            self.assertEqual(code, EXIT_OK)
            self.assertEqual(consistency["details"]["remediation"]["classification"], "no_action")

    def test_editorial_consistency_cli_exposes_same_remediation_plan(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._prepare_resolution_divergence(root, committed=True)
            output = StringIO()
            code = main(["--state-dir", td, "editorial-consistency"], output=output)
            payload = json.loads(output.getvalue())

            self.assertEqual(code, EXIT_UNHEALTHY)
            self.assertEqual(payload["remediation"]["classification"], "manual_investigation_required")
            self.assertFalse(payload["remediation"]["safe_to_automate"])


if __name__ == "__main__":
    unittest.main()
