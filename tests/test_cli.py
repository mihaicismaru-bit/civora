from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civora.cli import EXIT_ERROR, EXIT_OK, EXIT_UNHEALTHY, main
from civora.recovery import RecoveryEventLedger
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

    def test_recovery_events_support_filters_and_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            ledger = RecoveryEventLedger(Path(tmp) / "recovery_events.json")
            ledger.append(
                component="source_registry",
                event_type="degradation",
                status="degraded",
                details={"sequence": 1},
            )
            ledger.append(
                component="signal_store",
                event_type="degradation",
                status="degraded",
                details={"sequence": 2},
            )
            output = StringIO()
            code = main(
                [
                    "--state-dir",
                    tmp,
                    "recovery-events",
                    "--event-type",
                    "degradation",
                    "--limit",
                    "1",
                ],
                output=output,
            )
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["events"][0]["component"], "signal_store")

    def test_transaction_command_returns_full_record(self) -> None:
        with TemporaryDirectory() as tmp:
            journal = TransactionJournal(Path(tmp) / "transactions.json")
            tx_id = journal.prepare("story_to_review", {"story_id": "story-9"})
            output = StringIO()
            code = main(["--state-dir", tmp, "transaction", tx_id], output=output)
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["transaction"]["id"], tx_id)
            self.assertEqual(payload["transaction"]["payload"]["story_id"], "story-9")

    def test_resolution_audit_detects_and_can_be_reconciled(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            journal = TransactionJournal(state_dir / "transactions.json", max_recovery_attempts=1)
            tx_id = journal.prepare("story_to_review", {"story_id": "story-audit"})
            journal.recover(lambda _record: (_ for _ in ()).throw(RuntimeError("permanent")))
            journal.resolve_dead_letter(
                tx_id,
                "abort",
                actor="operator-test",
                reason="invalid payload",
            )

            before_output = StringIO()
            before_code = main(["--state-dir", tmp, "resolution-audit"], output=before_output)
            before = json.loads(before_output.getvalue())
            self.assertEqual(before_code, EXIT_UNHEALTHY)
            self.assertFalse(before["consistent"])
            self.assertEqual(len(before["missing_event_ids"]), 1)
            self.assertEqual(before["orphan_event_ids"], [])

            ledger = RecoveryEventLedger(state_dir / "recovery_events.json")
            repaired = journal.reconcile_resolution_audit(ledger)
            self.assertFalse(repaired["before"]["consistent"])
            self.assertTrue(repaired["after"]["consistent"])

            after_output = StringIO()
            after_code = main(["--state-dir", tmp, "resolution-audit"], output=after_output)
            after = json.loads(after_output.getvalue())
            self.assertEqual(after_code, EXIT_OK)
            self.assertTrue(after["consistent"])
            self.assertEqual(after["missing_event_ids"], [])

    def test_resolution_audit_never_hides_orphan_events(self) -> None:
        with TemporaryDirectory() as tmp:
            ledger = RecoveryEventLedger(Path(tmp) / "recovery_events.json")
            ledger.append(
                component="transaction_journal",
                event_type="resolution",
                status="abort",
                event_id="tx-resolution:orphan",
                details={"transaction_id": "missing"},
            )
            output = StringIO()
            code = main(["--state-dir", tmp, "resolution-audit"], output=output)
            payload = json.loads(output.getvalue())
            self.assertEqual(code, EXIT_UNHEALTHY)
            self.assertEqual(payload["missing_event_ids"], [])
            self.assertEqual(payload["orphan_event_ids"], ["tx-resolution:orphan"])


if __name__ == "__main__":
    unittest.main()
