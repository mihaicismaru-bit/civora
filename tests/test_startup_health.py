import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.health import RuntimeHealthReport
from civora.orchestrator import Orchestrator, OrchestratorError
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


if __name__ == "__main__":
    unittest.main()
