import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.health import UnifiedHealthInspector
from civora.recovery import RecoveryEventLedger
from civora.registry import SourceRegistry
from civora.transactions import TransactionJournal


class UnifiedHealthInspectorTests(unittest.TestCase):
    def test_empty_config_is_healthy(self):
        report = UnifiedHealthInspector().inspect()
        self.assertEqual(report.status, "healthy")
        self.assertEqual(report.components, [])

    def test_all_configured_empty_stores_are_healthy(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            report = UnifiedHealthInspector(
                source_registry_path=root / "sources.json",
                signal_store_path=root / "signals.json",
                review_queue_path=root / "review.json",
                transaction_journal_path=root / "transactions.json",
                checkpoint_dir=root / "checkpoints",
                recovery_event_ledger_path=root / "recovery-events.json",
            ).inspect()

            self.assertEqual(report.status, "healthy")
            self.assertEqual(
                [component.name for component in report.components],
                [
                    "source_registry",
                    "signal_store",
                    "review_queue",
                    "transaction_journal",
                    "story_checkpoints",
                    "recovery_event_ledger",
                ],
            )
            self.assertEqual(RecoveryEventLedger(root / "recovery-events.json").all(), [])

    def test_prepared_transaction_degrades_runtime_health(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            TransactionJournal(path).prepare("story_to_review", {"story_id": "s-1"})

            report = UnifiedHealthInspector(transaction_journal_path=path).inspect()

            self.assertEqual(report.status, "degraded")
            self.assertEqual(report.components[0].status, "pending_transaction")
            self.assertEqual(report.components[0].details["prepared_count"], 1)
            self.assertEqual(report.components[0].details["dead_letter_count"], 0)

    def test_dead_letter_transaction_degrades_runtime_health(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            journal = TransactionJournal(path, max_recovery_attempts=1)
            journal.prepare("story_to_review", {"story_id": "s-dead"})

            def fail(_record):
                raise RuntimeError("permanent failure")

            journal.recover(fail)
            report = UnifiedHealthInspector(transaction_journal_path=path).inspect()

            self.assertEqual(report.status, "degraded")
            self.assertEqual(report.components[0].status, "degraded")
            self.assertEqual(report.components[0].details["prepared_count"], 0)
            self.assertEqual(report.components[0].details["dead_letter_count"], 1)

    def test_valid_backup_recovery_is_visible_in_report(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "sources.json"
            registry = SourceRegistry(path)
            registry.store.save({"sources": []})
            registry.store.save({"sources": []})
            path.write_text("{not-json", encoding="utf-8")

            report = UnifiedHealthInspector(source_registry_path=path).inspect()

            self.assertEqual(report.status, "recovered_from_backup")
            self.assertEqual(report.components[0].status, "recovered_from_backup")

    def test_unrecoverable_store_is_reported_corrupt(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "signals.json"
            path.write_text("{not-json", encoding="utf-8")

            report = UnifiedHealthInspector(signal_store_path=path).inspect()

            self.assertEqual(report.status, "corrupt")
            self.assertEqual(report.components[0].status, "corrupt")
            self.assertIn("error", report.components[0].details)

    def test_report_serializes_to_plain_dict(self):
        with TemporaryDirectory() as td:
            report = UnifiedHealthInspector(
                transaction_journal_path=Path(td) / "transactions.json"
            ).inspect()
            payload = report.to_dict()
            self.assertEqual(payload["status"], "healthy")
            self.assertIsInstance(payload["components"], list)
            self.assertIn("generated_at", payload)

    def test_recovery_is_appended_to_event_ledger(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            sources = root / "sources.json"
            events = root / "recovery-events.json"
            registry = SourceRegistry(sources)
            registry.store.save({"sources": []})
            registry.store.save({"sources": []})
            sources.write_text("{not-json", encoding="utf-8")

            report = UnifiedHealthInspector(
                source_registry_path=sources,
                recovery_event_ledger_path=events,
            ).inspect()

            self.assertEqual(report.status, "recovered_from_backup")
            recorded = RecoveryEventLedger(events).all()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["component"], "source_registry")
            self.assertEqual(recorded[0]["event_type"], "recovery")

    def test_pending_transaction_is_appended_to_event_ledger(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            transactions = root / "transactions.json"
            events = root / "recovery-events.json"
            TransactionJournal(transactions).prepare("story_to_review", {"story_id": "s-1"})

            UnifiedHealthInspector(
                transaction_journal_path=transactions,
                recovery_event_ledger_path=events,
            ).inspect()

            recorded = RecoveryEventLedger(events).all()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["event_type"], "pending_transaction")
            self.assertEqual(recorded[0]["status"], "pending_transaction")

    def test_repeated_inspection_does_not_duplicate_same_problem(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            transactions = root / "transactions.json"
            events = root / "recovery-events.json"
            TransactionJournal(transactions).prepare("story_to_review", {"story_id": "s-1"})
            inspector = UnifiedHealthInspector(
                transaction_journal_path=transactions,
                recovery_event_ledger_path=events,
            )

            inspector.inspect()
            inspector.inspect()
            inspector.inspect()

            recorded = RecoveryEventLedger(events).all()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["status"], "pending_transaction")

    def test_healthy_transition_is_recorded_then_same_problem_can_recur(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            transactions = root / "transactions.json"
            events = root / "recovery-events.json"
            journal = TransactionJournal(transactions)
            tx = journal.prepare("story_to_review", {"story_id": "s-1"})
            inspector = UnifiedHealthInspector(
                transaction_journal_path=transactions,
                recovery_event_ledger_path=events,
            )

            inspector.inspect()
            journal.commit(tx["id"])
            inspector.inspect()
            journal.prepare("story_to_review", {"story_id": "s-2"})
            inspector.inspect()

            recorded = RecoveryEventLedger(events).all()
            self.assertEqual(
                [event["status"] for event in recorded],
                ["pending_transaction", "healthy", "pending_transaction"],
            )
            self.assertEqual(recorded[1]["event_type"], "health_transition")


if __name__ == "__main__":
    unittest.main()
