import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.editorial_approval import EditorialApprovalStore
from civora.editorial_resolution import EditorialResolutionCoordinator
from civora.remediation_cli import EXIT_ACTION_REQUIRED, EXIT_OK, main
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class EditorialRemediationCliTests(unittest.TestCase):
    @staticmethod
    def decision():
        return {
            "decision": "review",
            "decision_id": "decision-1",
            "story_id": "story-1",
            "kernel_semantic_hash": "a" * 64,
        }

    def test_healthy_state_returns_no_action(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval = EditorialApprovalStore(root / "editorial_approval.json")
            queue = ReviewQueue(root / "review_queue.json")
            approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", {"id": "story-1"}, "editorial_gate:review")
            output = io.StringIO()
            code = main(["--state-dir", str(root)], output=output)
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["remediation"]["classification"], "no_action")

    def test_prepared_crash_window_returns_safe_recovery_guidance(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval = EditorialApprovalStore(root / "editorial_approval.json")
            queue = ReviewQueue(root / "review_queue.json")
            journal = TransactionJournal(root / "transactions.json")
            case = approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", {"id": "story-1"}, "editorial_gate:review")
            payload = {
                "case_id": case["case_id"],
                "story_id": "story-1",
                "action": "approved",
                "actor": "editor",
                "reason": "verified manually",
                "review_queue_required": True,
            }
            journal.prepare(EditorialResolutionCoordinator.OPERATION, payload, tx_id="tx-1")
            approval.decide(case["case_id"], action="approved", actor="editor", reason="verified manually")
            output = io.StringIO()
            code = main(["--state-dir", str(root)], output=output)
            result = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_ACTION_REQUIRED)
            self.assertEqual(result["remediation"]["classification"], "automatic_recovery_available")
            self.assertTrue(result["remediation"]["safe_to_automate"])

    def test_committed_divergence_returns_manual_fail_closed_guidance(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval = EditorialApprovalStore(root / "editorial_approval.json")
            queue = ReviewQueue(root / "review_queue.json")
            journal = TransactionJournal(root / "transactions.json")
            case = approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", {"id": "story-1"}, "editorial_gate:review")
            payload = {
                "case_id": case["case_id"],
                "story_id": "story-1",
                "action": "approved",
                "actor": "editor",
                "reason": "verified manually",
                "review_queue_required": True,
            }
            journal.prepare(EditorialResolutionCoordinator.OPERATION, payload, tx_id="tx-1")
            approval.decide(case["case_id"], action="approved", actor="editor", reason="verified manually")
            journal.commit("tx-1")
            output = io.StringIO()
            code = main(["--state-dir", str(root)], output=output)
            result = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_ACTION_REQUIRED)
            self.assertEqual(result["remediation"]["classification"], "manual_investigation_required")
            self.assertFalse(result["remediation"]["safe_to_automate"])


if __name__ == "__main__":
    unittest.main()
