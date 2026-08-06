import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
