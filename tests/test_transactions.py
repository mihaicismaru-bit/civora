import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.orchestrator import Orchestrator
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal, TransactionJournalError


class TransactionJournalTests(unittest.TestCase):
    def test_prepare_commit_persists(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            journal = TransactionJournal(path)
            tx_id = journal.prepare("story_to_review", {"story_id": "s-1"})
            self.assertEqual(journal.records[tx_id]["status"], "prepared")

            journal.commit(tx_id)
            reloaded = TransactionJournal(path)
            self.assertEqual(reloaded.records[tx_id]["status"], "committed")
            self.assertEqual(reloaded.prepared(), [])

    def test_recover_replays_prepared_and_commits(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            journal = TransactionJournal(path)
            tx_id = journal.prepare("story_to_review", {"story_id": "s-2"})
            seen = []

            recovered = TransactionJournal(path).recover(lambda record: seen.append(record["payload"]["story_id"]))

            self.assertEqual(recovered, [tx_id])
            self.assertEqual(seen, ["s-2"])
            final = TransactionJournal(path)
            self.assertEqual(final.records[tx_id]["status"], "committed")

    def test_failed_recovery_remains_prepared_and_records_error(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            journal = TransactionJournal(path)
            tx_id = journal.prepare("story_to_review", {"story_id": "s-3"})

            def fail(_record):
                raise RuntimeError("simulated crash recovery failure")

            recovered = TransactionJournal(path).recover(fail)
            self.assertEqual(recovered, [])
            final = TransactionJournal(path)
            record = final.records[tx_id]
            self.assertEqual(record["status"], "prepared")
            self.assertEqual(record["recovery_attempts"], 1)
            self.assertIn("simulated crash recovery failure", record["last_error"])

    def test_recovery_is_bounded_and_moves_transaction_to_dead_letter(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            journal = TransactionJournal(path, max_recovery_attempts=3)
            tx_id = journal.prepare("story_to_review", {"story_id": "s-dead"})
            calls = []

            def fail(record):
                calls.append(record["id"])
                raise RuntimeError("permanent failure")

            for _ in range(3):
                TransactionJournal(path, max_recovery_attempts=3).recover(fail)

            final = TransactionJournal(path, max_recovery_attempts=3)
            record = final.records[tx_id]
            self.assertEqual(record["status"], "dead_letter")
            self.assertEqual(record["recovery_attempts"], 3)
            self.assertIn("permanent failure", record["last_error"])
            self.assertEqual([item["id"] for item in final.dead_letters()], [tx_id])

            TransactionJournal(path, max_recovery_attempts=3).recover(fail)
            self.assertEqual(len(calls), 3)

    def test_invalid_recovery_attempt_bound_is_rejected(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            with self.assertRaises(TransactionJournalError):
                TransactionJournal(path, max_recovery_attempts=0)

    def test_duplicate_transaction_id_is_rejected(self):
        with TemporaryDirectory() as td:
            journal = TransactionJournal(Path(td) / "transactions.json")
            journal.prepare("op", {}, tx_id="fixed")
            with self.assertRaises(TransactionJournalError):
                journal.prepare("op", {}, tx_id="fixed")

    def test_stale_instances_do_not_lose_each_others_prepared_records(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            first_writer = TransactionJournal(path)
            stale_writer = TransactionJournal(path)

            first_id = first_writer.prepare("first", {"n": 1})
            second_id = stale_writer.prepare("second", {"n": 2})

            final = TransactionJournal(path)
            self.assertIn(first_id, final.records)
            self.assertIn(second_id, final.records)
            self.assertEqual(final.records[first_id]["status"], "prepared")
            self.assertEqual(final.records[second_id]["status"], "prepared")

    def test_backup_recovery_is_inherited_from_atomic_store(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            journal = TransactionJournal(path)
            first = journal.prepare("first", {"n": 1})
            journal.commit(first)
            second = journal.prepare("second", {"n": 2})
            self.assertTrue(path.with_suffix(".json.bak").exists())

            path.write_text("{not-json", encoding="utf-8")
            recovered = TransactionJournal(path)
            self.assertTrue(recovered.recovered_from_backup)
            self.assertIn(first, recovered.records)
            self.assertNotEqual(recovered.records.get(second, {}).get("status"), "committed")

    def test_story_to_review_recovery_after_crash_before_queue_write(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            queue = ReviewQueue(root / "review.json")
            journal = TransactionJournal(root / "transactions.json")
            story_payload = {"id": "story-1", "state": "blocked"}
            tx_id = journal.prepare(
                Orchestrator.STORY_TO_REVIEW,
                {
                    "story_id": "story-1",
                    "story": story_payload,
                    "reason": "trust_score_below_threshold",
                },
            )

            recovered = Orchestrator(root / "state", queue, TransactionJournal(root / "transactions.json")).recover_pending_transactions()

            self.assertEqual(recovered, [tx_id])
            self.assertEqual(len(queue.pending()), 1)
            final = TransactionJournal(root / "transactions.json")
            self.assertEqual(final.records[tx_id]["status"], "committed")

    def test_story_to_review_recovery_is_idempotent_after_queue_write(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            queue = ReviewQueue(root / "review.json")
            journal = TransactionJournal(root / "transactions.json")
            story_payload = {"id": "story-2", "state": "blocked"}
            reason = "trust_score_below_threshold"
            tx_id = journal.prepare(
                Orchestrator.STORY_TO_REVIEW,
                {"story_id": "story-2", "story": story_payload, "reason": reason},
            )
            queue.enqueue_payload("story-2", story_payload, reason)

            recovered = Orchestrator(root / "state", queue, TransactionJournal(root / "transactions.json")).recover_pending_transactions()

            self.assertEqual(recovered, [tx_id])
            self.assertEqual(len(ReviewQueue(root / "review.json").pending()), 1)
            final = TransactionJournal(root / "transactions.json")
            self.assertEqual(final.records[tx_id]["status"], "committed")


if __name__ == "__main__":
    unittest.main()
