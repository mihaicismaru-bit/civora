import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.health import RuntimeHealthReport
from civora.orchestrator import Orchestrator, OrchestratorError
from civora.recovery import RecoveryEventLedger
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class SequenceInspector:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def inspect(self):
        index = min(self.calls, len(self.statuses) - 1)
        self.calls += 1
        return RuntimeHealthReport(
            status=self.statuses[index],
            generated_at="2026-08-07T04:00:00+00:00",
            components=[],
        )


class StartupHealthGateTests(unittest.TestCase):
    def test_corrupt_initial_state_blocks_before_recovery(self):
        with TemporaryDirectory() as td:
            inspector = SequenceInspector(["corrupt"])
            orchestrator = Orchestrator(Path(td), health_inspector=inspector)

            with self.assertRaisesRegex(OrchestratorError, "durable runtime state is corrupt"):
                orchestrator.startup_health_gate()

            self.assertEqual(inspector.calls, 1)

    def test_pending_transaction_is_replayed_then_runtime_reinspected(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            queue = ReviewQueue(root / "review.json")
            journal = TransactionJournal(root / "transactions.json")
            tx_id = journal.prepare(
                Orchestrator.STORY_TO_REVIEW,
                {
                    "story_id": "story-recovery",
                    "story": {"id": "story-recovery", "state": "blocked"},
                    "reason": "trust_score_below_threshold",
                },
            )
            inspector = SequenceInspector(["degraded", "healthy"])
            orchestrator = Orchestrator(
                root / "state",
                review_queue=queue,
                transaction_journal=TransactionJournal(root / "transactions.json"),
                health_inspector=inspector,
            )

            report = orchestrator.startup_health_gate()

            self.assertEqual(report.status, "healthy")
            self.assertEqual(inspector.calls, 2)
            self.assertEqual(len(ReviewQueue(root / "review.json").pending()), 1)
            final = TransactionJournal(root / "transactions.json")
            self.assertEqual(final.records[tx_id]["status"], "committed")

    def test_runtime_still_degraded_after_recovery_is_blocked(self):
        with TemporaryDirectory() as td:
            inspector = SequenceInspector(["degraded", "degraded"])
            orchestrator = Orchestrator(Path(td), health_inspector=inspector)

            with self.assertRaisesRegex(OrchestratorError, "remains degraded after recovery"):
                orchestrator.startup_health_gate()

            self.assertEqual(inspector.calls, 2)

    def test_recovered_from_backup_is_an_allowed_final_state(self):
        with TemporaryDirectory() as td:
            inspector = SequenceInspector(["recovered_from_backup", "recovered_from_backup"])
            orchestrator = Orchestrator(Path(td), health_inspector=inspector)

            report = orchestrator.startup_health_gate()

            self.assertEqual(report.status, "recovered_from_backup")
            self.assertEqual(inspector.calls, 2)

    def test_startup_repairs_missing_resolution_audit_before_final_authorization(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            journal_path = root / "transactions.json"
            ledger_path = root / "recovery_events.json"
            journal = TransactionJournal(journal_path, max_recovery_attempts=1)
            tx_id = journal.prepare("story_to_review", {"story_id": "story-audit"})
            journal.recover(lambda record: (_ for _ in ()).throw(RuntimeError("permanent failure")))
            journal.resolve_dead_letter(
                tx_id,
                "abort",
                actor="operator",
                reason="invalid payload",
            )
            self.assertEqual(RecoveryEventLedger(ledger_path).all(), [])

            inspector = SequenceInspector(["healthy", "healthy"])
            orchestrator = Orchestrator(
                root,
                transaction_journal=TransactionJournal(journal_path),
                health_inspector=inspector,
                recovery_ledger=RecoveryEventLedger(ledger_path),
            )

            report = orchestrator.startup_health_gate()

            self.assertEqual(report.status, "healthy")
            events = RecoveryEventLedger(ledger_path).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "resolution")
            self.assertEqual(events[0]["details"]["transaction_id"], tx_id)
            self.assertEqual(events[0]["status"], "abort")

            orchestrator.startup_health_gate()
            self.assertEqual(len(RecoveryEventLedger(ledger_path).all()), 1)


if __name__ == "__main__":
    unittest.main()
