from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civora.cli import EXIT_OK, EXIT_UNHEALTHY, main
from civora.editorial_approval import EditorialApprovalStore
from civora.editorial_resolution import EditorialResolutionCoordinator
from civora.models import Evidence, FactKernel, Signal, Source, StoryObject, StoryState
from civora.orchestrator import Orchestrator
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class EditorialCliControlTests(unittest.TestCase):
    @staticmethod
    def _review_decision(story_id: str) -> dict:
        return {
            "decision_id": f"decision-{story_id}",
            "story_id": story_id,
            "kernel_semantic_hash": "a" * 64,
            "decision": "review",
        }

    def test_health_exposes_editorial_cross_store_consistency(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            EditorialApprovalStore(state_dir / "editorial_approval.json").ensure_pending(
                self._review_decision("story-missing-queue")
            )

            output = StringIO()
            code = main(["--state-dir", tmp, "health"], output=output)
            payload = json.loads(output.getvalue())
            components = {item["name"]: item for item in payload["components"]}

            self.assertEqual(code, EXIT_UNHEALTHY)
            self.assertEqual(payload["status"], "degraded")
            self.assertIn("editorial_consistency", components)
            self.assertEqual(components["editorial_consistency"]["status"], "degraded")
            self.assertEqual(components["editorial_consistency"]["details"]["mismatch_count"], 1)

    def test_editorial_consistency_command_is_machine_readable(self) -> None:
        with TemporaryDirectory() as tmp:
            output = StringIO()
            code = main(["--state-dir", tmp, "editorial-consistency"], output=output)
            payload = json.loads(output.getvalue())

            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "healthy")
            self.assertEqual(payload["mismatch_count"], 0)
            self.assertEqual(payload["recoverable_mismatch_count"], 0)

    def test_resume_approved_cli_recovers_prepared_resolution_and_packages(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = ReviewQueue(root / "review_queue.json")
            journal = TransactionJournal(root / "transactions.json")
            source = Source(
                "Official source", "official", ["Valcea"],
                0.95, 0.95, 0.95, 0.95, 0.95, 0.05,
            )
            statement = "Temporary traffic restrictions are in force."
            signal = Signal(
                title="Temporary traffic restrictions",
                summary="Drivers should use alternate routes.",
                geography=["Valcea"], source_ids=[source.id],
                public_interest=0.9, impact=0.8, novelty=0.5,
                utility=0.9, factual_risk=0.1,
            )
            story = StoryObject(
                signal=signal,
                fact_kernel=FactKernel(
                    confirmed_facts=[statement], uncertain_claims=[],
                    affected_groups=["drivers"], next_expected_event=None,
                    evidence=[Evidence(source.id, statement, confidence=0.95)],
                ),
            )
            orchestrator = Orchestrator(root, review_queue=queue, transaction_journal=journal)
            blocked = orchestrator.run(story, {source.id: source})
            self.assertEqual(blocked.state, StoryState.BLOCKED)

            case = orchestrator.editorial_approval_store.load_story(story.id)
            self.assertIsNotNone(case)
            payload = {
                "case_id": case["case_id"],
                "story_id": story.id,
                "action": "approved",
                "actor": "editor",
                "reason": "manual source verification completed",
                "review_queue_required": True,
            }
            journal.prepare(EditorialResolutionCoordinator.OPERATION, payload, tx_id="cli-restart-tx")
            orchestrator.editorial_approval_store.decide(
                case["case_id"], action="approved", actor="editor",
                reason="manual source verification completed",
            )

            output = StringIO()
            code = main(
                ["--state-dir", tmp, "resume-approved", story.id, "--version", "1"],
                output=output,
            )
            result = json.loads(output.getvalue())

            self.assertEqual(code, EXIT_OK)
            self.assertTrue(result["resumed"])
            self.assertEqual(result["story"]["state"], StoryState.PACKAGED.value)
            self.assertIsNotNone(result["story"]["article"])
            self.assertIsNotNone(result["story"]["content_pack"])
            self.assertEqual(ReviewQueue(root / "review_queue.json").get(story.id)["status"], "approved")
            recovered_journal = TransactionJournal(root / "transactions.json")
            recovered_journal.load()
            self.assertEqual(recovered_journal.records["cli-restart-tx"]["status"], "committed")


if __name__ == "__main__":
    unittest.main()
