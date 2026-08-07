import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.recovery import RecoveryEventLedger
from civora.transactions import TransactionJournal


class DeadLetterResolutionAuditTests(unittest.TestCase):
    @staticmethod
    def _dead_letter(journal: TransactionJournal, tx_id: str) -> None:
        def fail(_record):
            raise RuntimeError("permanent downstream failure")
        journal.recover(fail)
        assert journal.records[tx_id]["status"] == "dead_letter"

    def test_resolution_is_mirrored_to_global_recovery_ledger(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            journal = TransactionJournal(root / "transactions.json", max_recovery_attempts=1)
            ledger = RecoveryEventLedger(root / "recovery-events.json")
            tx_id = journal.prepare("story_to_review", {"story_id": "story-1"})
            self._dead_letter(journal, tx_id)

            resolved = journal.resolve_dead_letter(
                tx_id,
                "requeue",
                actor="operator:test",
                reason="downstream repaired",
                recovery_ledger=ledger,
            )

            events = RecoveryEventLedger(root / "recovery-events.json").all()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["event_type"], "resolution")
            self.assertEqual(event["status"], "requeue")
            self.assertEqual(event["details"]["transaction_id"], tx_id)
            self.assertEqual(event["details"]["actor"], "operator:test")
            self.assertEqual(event["id"], resolved["resolution_history"][-1]["event_id"])

    def test_reconciliation_repairs_crash_window_and_is_idempotent(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            journal_path = root / "transactions.json"
            ledger_path = root / "recovery-events.json"
            journal = TransactionJournal(journal_path, max_recovery_attempts=1)
            tx_id = journal.prepare("story_to_review", {"story_id": "story-2"})
            self._dead_letter(journal, tx_id)

            # Simulate process termination after the journal resolution is durable
            # but before the independent global audit ledger is updated.
            journal.resolve_dead_letter(
                tx_id,
                "abort",
                actor="operator:test",
                reason="payload irreparable",
            )
            self.assertEqual(RecoveryEventLedger(ledger_path).all(), [])

            restarted = TransactionJournal(journal_path)
            ledger = RecoveryEventLedger(ledger_path)
            first = restarted.mirror_resolution_events(ledger)
            second = TransactionJournal(journal_path).mirror_resolution_events(
                RecoveryEventLedger(ledger_path)
            )

            self.assertEqual(first, second)
            events = RecoveryEventLedger(ledger_path).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["status"], "abort")
            self.assertEqual(events[0]["details"]["reason"], "payload irreparable")

    def test_legacy_resolution_history_without_event_id_can_be_reconciled(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            journal_path = root / "transactions.json"
            ledger_path = root / "recovery-events.json"
            journal = TransactionJournal(journal_path, max_recovery_attempts=1)
            tx_id = journal.prepare("story_to_review", {"story_id": "story-legacy"})
            self._dead_letter(journal, tx_id)
            journal.resolve_dead_letter(
                tx_id,
                "abort",
                actor="operator:test",
                reason="legacy audit",
            )

            # Older checkpoint 0046 histories did not persist event_id.
            def remove_event_id(state):
                state["records"][tx_id]["resolution_history"][-1].pop("event_id", None)
            journal.store.update({"records": {}}, remove_event_id)

            mirrored = TransactionJournal(journal_path).mirror_resolution_events(
                RecoveryEventLedger(ledger_path)
            )
            self.assertEqual(len(mirrored), 1)
            self.assertTrue(mirrored[0].startswith("tx-resolution:"))
            self.assertEqual(len(RecoveryEventLedger(ledger_path).all()), 1)


if __name__ == "__main__":
    unittest.main()
