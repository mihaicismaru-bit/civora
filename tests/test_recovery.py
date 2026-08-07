import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.recovery import RecoveryEventLedger, RecoveryEventLedgerError


class RecoveryEventLedgerTests(unittest.TestCase):
    def test_append_persists_event(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "recovery-events.json"
            ledger = RecoveryEventLedger(path)
            event = ledger.append(
                component="signal_store",
                event_type="recovery",
                status="recovered_from_backup",
                details={"path": "signals.json"},
            )

            reloaded = RecoveryEventLedger(path)
            self.assertEqual(len(reloaded.all()), 1)
            self.assertEqual(reloaded.all()[0]["id"], event["id"])

    def test_stable_event_id_makes_identical_append_idempotent(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "recovery-events.json"
            ledger = RecoveryEventLedger(path)
            kwargs = {
                "component": "transaction_journal",
                "event_type": "resolution",
                "status": "requeue",
                "details": {"transaction_id": "tx-1"},
                "timestamp": "2026-08-07T06:00:00+00:00",
                "event_id": "tx-resolution:stable",
            }
            first = ledger.append(**kwargs)
            second = RecoveryEventLedger(path).append(**kwargs)
            self.assertEqual(first, second)
            self.assertEqual(len(RecoveryEventLedger(path).all()), 1)

    def test_stable_event_id_rejects_conflicting_content(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "recovery-events.json"
            ledger = RecoveryEventLedger(path)
            ledger.append(
                component="transaction_journal",
                event_type="resolution",
                status="requeue",
                details={"transaction_id": "tx-1"},
                timestamp="2026-08-07T06:00:00+00:00",
                event_id="tx-resolution:stable",
            )
            with self.assertRaises(RecoveryEventLedgerError):
                RecoveryEventLedger(path).append(
                    component="transaction_journal",
                    event_type="resolution",
                    status="abort",
                    details={"transaction_id": "tx-1"},
                    timestamp="2026-08-07T06:00:00+00:00",
                    event_id="tx-resolution:stable",
                )

    def test_stale_writers_do_not_lose_events(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "recovery-events.json"
            first = RecoveryEventLedger(path)
            second = RecoveryEventLedger(path)

            first.append(
                component="source_registry",
                event_type="degradation",
                status="degraded",
            )
            second.append(
                component="review_queue",
                event_type="corruption",
                status="corrupt",
            )

            events = RecoveryEventLedger(path).all()
            self.assertEqual(len(events), 2)
            self.assertEqual(
                {event["component"] for event in events},
                {"source_registry", "review_queue"},
            )

    def test_corrupt_ledger_fails_closed(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "recovery-events.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(RecoveryEventLedgerError):
                RecoveryEventLedger(path)

    def test_event_type_is_validated(self):
        with TemporaryDirectory() as td:
            ledger = RecoveryEventLedger(Path(td) / "recovery-events.json")
            with self.assertRaises(RecoveryEventLedgerError):
                ledger.append(
                    component="signal_store",
                    event_type="unknown",
                    status="degraded",
                )


if __name__ == "__main__":
    unittest.main()
