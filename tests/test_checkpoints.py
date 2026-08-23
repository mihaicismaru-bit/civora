import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.checkpoints import StoryCheckpointError, StoryCheckpointStore
from civora.models import Evidence, FactKernel, Signal, StoryObject


class StoryCheckpointStoreTests(unittest.TestCase):
    def make_story(self):
        signal = Signal(
            title="Test signal",
            summary="Checkpoint persistence test",
            geography=["Test"],
            source_ids=["source-1"],
            public_interest=0.8,
            impact=0.7,
            novelty=0.5,
            utility=0.9,
            factual_risk=0.1,
        )
        kernel = FactKernel(
            confirmed_facts=["A confirmed fact"],
            uncertain_claims=[],
            affected_groups=["residents"],
            next_expected_event=None,
            evidence=[Evidence("source-1", "Evidence claim", confidence=0.9)],
        )
        return StoryObject(signal=signal, fact_kernel=kernel)

    def test_checkpoint_is_checksum_protected(self):
        story = self.make_story()
        with TemporaryDirectory() as td:
            store = StoryCheckpointStore(Path(td))
            path = store.save(story, "signal")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["label"], "signal")
            self.assertEqual(payload["story"]["id"], story.id)
            self.assertRegex(payload["checksum"], r"^[0-9a-f]{64}$")

    def test_checkpoint_recovers_previous_valid_generation(self):
        story = self.make_story()
        with TemporaryDirectory() as td:
            store = StoryCheckpointStore(Path(td))
            path = store.save(story, "signal")
            story.trust_score = 42.0
            store.save(story, "signal")
            path.write_text("{corrupt", encoding="utf-8")

            payload = store.load(story.id, story.version, "signal")
            self.assertEqual(payload["story"]["trust_score"], 0.0)
            repaired = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(repaired["story"]["trust_score"], 0.0)

    def test_checkpoint_fails_closed_when_both_generations_are_invalid(self):
        story = self.make_story()
        with TemporaryDirectory() as td:
            store = StoryCheckpointStore(Path(td))
            path = store.save(story, "signal")
            store.save(story, "signal")
            path.write_text("{corrupt", encoding="utf-8")
            path.with_suffix(path.suffix + ".bak").write_text("{also-corrupt", encoding="utf-8")

            with self.assertRaises(StoryCheckpointError):
                store.load(story.id, story.version, "signal")


if __name__ == "__main__":
    unittest.main()
