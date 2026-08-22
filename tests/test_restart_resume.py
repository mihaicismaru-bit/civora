import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.editorial_resolution import EditorialResolutionCoordinator
from civora.models import Evidence, FactKernel, Signal, Source, StoryObject, StoryState
from civora.orchestrator import Orchestrator
from civora.resume import resume_approved_story
from civora.review import ReviewQueue
from civora.transactions import TransactionJournal


class RestartResumeTests(unittest.TestCase):
    def test_prepared_approval_resolution_recovers_after_restart_and_packages(self):
        with TemporaryDirectory() as td:
            root = Path(td)
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
            result = orchestrator.run(story, {source.id: source})
            self.assertEqual(result.state, StoryState.BLOCKED)
            self.assertIsNone(result.article)

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
            journal.prepare(EditorialResolutionCoordinator.OPERATION, payload, tx_id="restart-tx")
            orchestrator.editorial_approval_store.decide(
                case["case_id"], action="approved", actor="editor",
                reason="manual source verification completed",
            )
            self.assertEqual(queue.get(story.id)["status"], "pending")

            resumed = resume_approved_story(root, story.id, story.version)
            self.assertEqual(resumed.state, StoryState.PACKAGED)
            self.assertIsNotNone(resumed.article)
            self.assertIsNotNone(resumed.content_pack)

            recovered_queue = ReviewQueue(root / "review_queue.json")
            recovered_journal = TransactionJournal(root / "transactions.json")
            self.assertEqual(recovered_queue.get(story.id)["status"], "approved")
            recovered_journal.load()
            self.assertEqual(recovered_journal.records["restart-tx"]["status"], "committed")
            self.assertTrue((root / f"{story.id}_v1_editorial_approved.json").exists())
            self.assertTrue((root / f"{story.id}_v1_packaged.json").exists())


if __name__ == "__main__":
    unittest.main()
