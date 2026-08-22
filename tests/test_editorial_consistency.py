import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.editorial_approval import EditorialApprovalStore
from civora.editorial_consistency import EditorialConsistencyInspector
from civora.editorial_resolution import EditorialResolutionCoordinator
from civora.orchestrator import Orchestrator, OrchestratorError
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class EditorialConsistencyTests(unittest.TestCase):
    @staticmethod
    def decision(story_id="story-1"):
        return {
            "decision": "review",
            "decision_id": "decision-1",
            "story_id": story_id,
            "kernel_semantic_hash": "a" * 64,
        }

    @staticmethod
    def story_payload(story_id="story-1"):
        return {"id": story_id}

    def stores(self, root: Path):
        approval = EditorialApprovalStore(root / "editorial_approval.json")
        queue = ReviewQueue(root / "review_queue.json")
        journal = TransactionJournal(root / "transactions.json")
        inspector = EditorialConsistencyInspector(approval.path, queue.path, journal.path)
        return approval, queue, journal, inspector

    def test_pending_case_and_pending_queue_are_consistent(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, queue, _, inspector = self.stores(root)
            approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", self.story_payload(), "editorial_gate:review")

            status = inspector.inspect()
            self.assertEqual(status["status"], "healthy")
            self.assertEqual(status["mismatch_count"], 0)
            self.assertEqual(status["recoverable_mismatch_count"], 0)

    def test_prepared_resolution_covers_temporary_approval_queue_divergence(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, queue, journal, inspector = self.stores(root)
            case = approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", self.story_payload(), "editorial_gate:review")
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

            status = inspector.inspect()
            self.assertEqual(status["status"], "pending_transaction")
            self.assertEqual(status["mismatch_count"], 0)
            self.assertEqual(status["recoverable_mismatch_count"], 1)

    def test_committed_resolution_divergence_is_degraded(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, queue, journal, inspector = self.stores(root)
            case = approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", self.story_payload(), "editorial_gate:review")
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
            journal.commit("tx-1")

            status = inspector.inspect()
            self.assertEqual(status["status"], "degraded")
            self.assertGreaterEqual(status["mismatch_count"], 1)
            self.assertTrue(
                any(item["type"] == "committed_resolution_not_reflected" for item in status["mismatches"])
            )

    def test_startup_replays_prepared_resolution_then_requires_consistency(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, queue, journal, _ = self.stores(root)
            case = approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", self.story_payload(), "editorial_gate:review")
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

            orchestrator = Orchestrator(
                root,
                review_queue=queue,
                transaction_journal=journal,
                editorial_approval_store=approval,
            )
            report = orchestrator.startup_health_gate()
            self.assertIn(report.status, {"healthy", "recovered_from_backup"})
            self.assertEqual(queue.get("story-1")["status"], "approved")
            journal.load()
            self.assertEqual(journal.records["tx-1"]["status"], "committed")

    def test_startup_blocks_committed_cross_store_divergence(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, queue, journal, _ = self.stores(root)
            case = approval.ensure_pending(self.decision())
            queue.enqueue_payload("story-1", self.story_payload(), "editorial_gate:review")
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
            journal.commit("tx-1")

            orchestrator = Orchestrator(
                root,
                review_queue=queue,
                transaction_journal=journal,
                editorial_approval_store=approval,
            )
            with self.assertRaisesRegex(OrchestratorError, "editorial durable stores are inconsistent"):
                orchestrator.startup_health_gate()


if __name__ == "__main__":
    unittest.main()
