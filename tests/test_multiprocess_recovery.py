from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from civora.orchestrator import Orchestrator
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


CHILD_PREPARE_ONLY = r'''
from pathlib import Path
import sys
from civora.transactions import TransactionJournal

state = Path(sys.argv[1])
journal = TransactionJournal(state / "transactions.json")
story_id = sys.argv[2]
journal.prepare(
    "story_to_review",
    {
        "story_id": story_id,
        "story": {"id": story_id},
        "reason": "multiprocess_crash_test",
    },
    tx_id=sys.argv[3],
)
'''


CHILD_PREPARE_AND_ENQUEUE = r'''
from pathlib import Path
import sys
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal

state = Path(sys.argv[1])
story_id = sys.argv[2]
tx_id = sys.argv[3]
journal = TransactionJournal(state / "transactions.json")
queue = ReviewQueue(state / "review_queue.json")
journal.prepare(
    "story_to_review",
    {
        "story_id": story_id,
        "story": {"id": story_id},
        "reason": "multiprocess_crash_test",
    },
    tx_id=tx_id,
)
queue.enqueue_payload(story_id, {"id": story_id}, "multiprocess_crash_test")
# Deliberately exit without commit: simulates a crash after the queue write.
'''


CHILD_CONCURRENT_ENQUEUE = r'''
from pathlib import Path
import sys
from civora.review import ReviewQueue

path = Path(sys.argv[1])
story_id = sys.argv[2]
queue = ReviewQueue(path)
queue.enqueue_payload(story_id, {"id": story_id}, "concurrent_writer_test")
'''


CHILD_CONCURRENT_PREPARE = r'''
from pathlib import Path
import sys
from civora.transactions import TransactionJournal

path = Path(sys.argv[1])
tx_id = sys.argv[2]
journal = TransactionJournal(path)
journal.prepare(
    "noop",
    {"worker": tx_id},
    tx_id=tx_id,
)
'''


class MultiprocessRecoveryTests(unittest.TestCase):
    def _run_child(self, script: str, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", script, *(str(arg) for arg in args)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_restart_recovers_crash_after_prepare_before_review_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            story_id = "story-before-review"
            tx_id = "tx-before-review"
            self._run_child(CHILD_PREPARE_ONLY, state, story_id, tx_id)

            journal = TransactionJournal(state / "transactions.json")
            self.assertEqual(journal.records[tx_id]["status"], "prepared")
            queue = ReviewQueue(state / "review_queue.json")

            orchestrator = Orchestrator(
                state,
                review_queue=queue,
                transaction_journal=journal,
            )
            report = orchestrator.startup_health_gate()

            journal.load()
            queue.load()
            self.assertIn(report.status, {"healthy", "recovered_from_backup"})
            self.assertEqual(journal.records[tx_id]["status"], "committed")
            self.assertIn(story_id, queue.items)
            self.assertEqual(len(queue.items), 1)

    def test_restart_is_idempotent_after_queue_write_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            story_id = "story-after-review"
            tx_id = "tx-after-review"
            self._run_child(CHILD_PREPARE_AND_ENQUEUE, state, story_id, tx_id)

            queue = ReviewQueue(state / "review_queue.json")
            journal = TransactionJournal(state / "transactions.json")
            self.assertIn(story_id, queue.items)
            self.assertEqual(journal.records[tx_id]["status"], "prepared")

            orchestrator = Orchestrator(
                state,
                review_queue=queue,
                transaction_journal=journal,
            )
            orchestrator.startup_health_gate()
            # A second independent startup must remain safe and duplicate-free.
            Orchestrator(
                state,
                review_queue=ReviewQueue(state / "review_queue.json"),
                transaction_journal=TransactionJournal(state / "transactions.json"),
            ).startup_health_gate()

            final_queue = ReviewQueue(state / "review_queue.json")
            final_journal = TransactionJournal(state / "transactions.json")
            self.assertEqual(final_journal.records[tx_id]["status"], "committed")
            self.assertEqual(list(final_queue.items), [story_id])

    def test_independent_review_queue_writers_do_not_lose_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_queue.json"
            story_ids = [f"story-{index:02d}" for index in range(12)]
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", CHILD_CONCURRENT_ENQUEUE, str(path), story_id],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for story_id in story_ids
            ]
            failures = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                if process.returncode != 0:
                    failures.append((process.returncode, stdout, stderr))
            self.assertEqual(failures, [])

            queue = ReviewQueue(path)
            self.assertEqual(set(queue.items), set(story_ids))
            self.assertEqual(len(queue.items), len(story_ids))

    def test_independent_transaction_writers_do_not_lose_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transactions.json"
            tx_ids = [f"tx-{index:02d}" for index in range(12)]
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", CHILD_CONCURRENT_PREPARE, str(path), tx_id],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for tx_id in tx_ids
            ]
            failures = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                if process.returncode != 0:
                    failures.append((process.returncode, stdout, stderr))
            self.assertEqual(failures, [])

            journal = TransactionJournal(path)
            self.assertEqual(set(journal.records), set(tx_ids))
            self.assertTrue(all(record["status"] == "prepared" for record in journal.records.values()))


if __name__ == "__main__":
    unittest.main()
