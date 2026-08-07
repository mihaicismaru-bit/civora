from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civora.cli import EXIT_ERROR, EXIT_OK, EXIT_UNHEALTHY, main
from civora.transactions import TransactionJournal


class OperationalCliTests(unittest.TestCase):
    def test_health_reports_healthy_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            output = StringIO()
            code = main(["--state-dir", tmp, "health"], output=output)
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "healthy")
            names = {item["name"] for item in payload["components"]}
            self.assertIn("source_registry", names)
            self.assertIn("signal_store", names)
            self.assertIn("review_queue", names)
            self.assertIn("transaction_journal", names)
            self.assertIn("recovery_event_ledger", names)

    def test_dead_letter_list_and_requeue_are_audited(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            journal = TransactionJournal(state_dir / "transactions.json", max_recovery_attempts=1)
            tx_id = journal.prepare("story_to_review", {"story_id": "story-1"})

            def fail(_record: dict) -> None:
                raise RuntimeError("boom")

            journal.recover(fail)

            listed = StringIO()
            self.assertEqual(
                main(["--state-dir", tmp, "dead-letters"], output=listed),
                EXIT_OK,
            )
            list_payload = json.loads(listed.getvalue())
            self.assertEqual(list_payload["count"], 1)
            self.assertEqual(list_payload["dead_letters"][0]["id"], tx_id)

            resolved = StringIO()
            code = main(
                [
                    "--state-dir",
                    tmp,
                    "resolve-dead-letter",
                    tx_id,
                    "--action",
                    "requeue",
                    "--actor",
                    "operator-test",
                    "--reason",
                    "transient dependency recovered",
                ],
                output=resolved,
            )
            self.assertEqual(code, EXIT_OK)
            resolution = json.loads(resolved.getvalue())["resolved"]
            self.assertEqual(resolution["status"], "prepared")
            self.assertEqual(resolution["recovery_attempts"], 0)
            self.assertEqual(resolution["resolution_history"][-1]["actor"], "operator-test")

            with (state_dir / "recovery_events.json").open("r", encoding="utf-8") as handle:
                store_payload = json.load(handle)
            events = store_payload["events"]
            resolution_events = [event for event in events if event["event_type"] == "resolution"]
            self.assertEqual(len(resolution_events), 1)
            self.assertEqual(resolution_events[0]["details"]["transaction_id"], tx_id)

    def test_health_returns_unhealthy_exit_for_dead_letter(self) -> None:
        with TemporaryDirectory() as tmp:
            journal = TransactionJournal(Path(tmp) / "transactions.json", max_recovery_attempts=1)
            journal.prepare("story_to_review", {"story_id": "story-1"})
            journal.recover(lambda _record: (_ for _ in ()).throw(RuntimeError("permanent")))

            output = StringIO()
            code = main(["--state-dir", tmp, "health"], output=output)
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_UNHEALTHY)
            self.assertEqual(payload["status"], "degraded")

    def test_resolve_unknown_transaction_returns_operational_error(self) -> None:
        with TemporaryDirectory() as tmp:
            output = StringIO()
            code = main(
                [
                    "--state-dir",
                    tmp,
                    "resolve-dead-letter",
                    "missing",
                    "--action",
                    "abort",
                    "--actor",
                    "operator-test",
                    "--reason",
                    "invalid payload",
                ],
                output=output,
            )
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_ERROR)
            self.assertIn("unknown transaction", payload["error"])


if __name__ == "__main__":
    unittest.main()
