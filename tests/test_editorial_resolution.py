import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.editorial_approval import EditorialApprovalStore
from civora.editorial_resolution import EditorialResolutionCoordinator, EditorialResolutionError
from civora.orchestrator import Orchestrator
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class EditorialResolutionTests(unittest.TestCase):
    @staticmethod
    def decision(story_id="story-1"):
        return {
            "decision_id": "d" * 64,
            "story_id": story_id,
            "kernel_semantic_hash": "a" * 64,
            "decision": "review",
        }

    @staticmethod
    def story_payload(story_id="story-1"):
        return {"id": story_id, "state": "blocked"}

    def make_active(self, root: Path, story_id="story-1"):
        approval = EditorialApprovalStore(root / "editorial_approval.json")
        case = approval.ensure_pending(self.decision(story_id))
        queue = ReviewQueue(root / "review_queue.json")
        queue.enqueue_payload(story_id, self.story_payload(story_id), "editorial_gate:disputed")
        journal = TransactionJournal(root / "transactions.json")
        return approval, case, queue, journal

    def test_decision_resolves_approval_and_queue_in_one_journaled_operation(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, case, queue, journal = self.make_active(root)
            coordinator = EditorialResolutionCoordinator(approval, queue, journal)
            result = coordinator.decide(
                case["case_id"],
                action="approved",
                actor="editor-1",
                reason="primary record verified",
            )
            self.assertEqual(result["case"]["state"], "approved")
            self.assertEqual(result["review_queue_item"]["status"], "approved")
            self.assertEqual(result["review_queue_item"]["history"][-1]["actor"], "editor-1")
            journal.load()
            self.assertEqual(journal.records[result["transaction_id"]]["status"], "committed")

    def test_revision_required_is_mirrored_to_queue(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, case, queue, journal = self.make_active(root)
            result = EditorialResolutionCoordinator(approval, queue, journal).decide(
                case["case_id"],
                action="revision_required",
                actor="editor-2",
                reason="needs one more source",
            )
            self.assertEqual(result["case"]["state"], "revision_required")
            self.assertEqual(queue.get("story-1")["status"], "revision_required")

    def test_prepared_transaction_repairs_crash_after_approval_write(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, case, queue, journal = self.make_active(root)
            payload = {
                "case_id": case["case_id"],
                "story_id": "story-1",
                "action": "approved",
                "actor": "editor-crash",
                "reason": "verified before simulated crash",
                "review_queue_required": True,
            }
            tx_id = journal.prepare(EditorialResolutionCoordinator.OPERATION, payload)
            approval.decide(
                case["case_id"],
                action="approved",
                actor="editor-crash",
                reason="verified before simulated crash",
            )
            self.assertEqual(queue.get("story-1")["status"], "pending")

            orchestrator = Orchestrator(
                root,
                review_queue=ReviewQueue(root / "review_queue.json"),
                transaction_journal=TransactionJournal(root / "transactions.json"),
                editorial_approval_store=EditorialApprovalStore(root / "editorial_approval.json"),
            )
            recovered = orchestrator.recover_pending_transactions()
            self.assertEqual(recovered, [tx_id])
            self.assertEqual(ReviewQueue(root / "review_queue.json").get("story-1")["status"], "approved")
            final_journal = TransactionJournal(root / "transactions.json")
            self.assertEqual(final_journal.records[tx_id]["status"], "committed")

    def test_different_terminal_queue_state_fails_closed(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval, case, queue, journal = self.make_active(root)
            queue.resolve("story-1", action="rejected", actor="editor-a", reason="first decision")
            coordinator = EditorialResolutionCoordinator(approval, queue, journal)
            with self.assertRaises(EditorialResolutionError):
                coordinator.decide(
                    case["case_id"],
                    action="approved",
                    actor="editor-b",
                    reason="conflicting decision",
                )

    def test_queue_disabled_case_remains_supported(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            approval = EditorialApprovalStore(root / "editorial_approval.json")
            case = approval.ensure_pending(self.decision())
            queue = ReviewQueue(root / "review_queue.json")
            journal = TransactionJournal(root / "transactions.json")
            result = EditorialResolutionCoordinator(approval, queue, journal).decide(
                case["case_id"], action="approved", actor="editor", reason="manual approval"
            )
            self.assertEqual(result["case"]["state"], "approved")
            self.assertIsNone(result["review_queue_item"])

    def test_schema_2_queue_without_history_remains_readable(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            queue = ReviewQueue(root / "review_queue.json")
            queue.enqueue_payload("story-1", self.story_payload(), "legacy")
            path = root / "review_queue.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["items"]["story-1"].pop("history", None)
            payload["checksum"] = queue.store.checksum(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")
            restored = ReviewQueue(path)
            self.assertEqual(restored.get("story-1")["status"], "pending")


if __name__ == "__main__":
    unittest.main()
