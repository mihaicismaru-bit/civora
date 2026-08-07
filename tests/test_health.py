import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.health import UnifiedHealthInspector
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
                ],
            )

    def test_prepared_transaction_degrades_runtime_health(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "transactions.json"
            TransactionJournal(path).prepare("story_to_review", {"story_id": "s-1"})

            report = UnifiedHealthInspector(transaction_journal_path=path).inspect()

            self.assertEqual(report.status, "degraded")
            self.assertEqual(report.components[0].status, "pending_transaction")
            self.assertEqual(report.components[0].details["prepared_count"], 1)

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


if __name__ == "__main__":
    unittest.main()
