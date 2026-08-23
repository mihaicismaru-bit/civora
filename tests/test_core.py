import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.models import Source, Signal, Evidence, FactKernel, StoryObject, StoryState
from civora.orchestrator import Orchestrator


class CivoraCoreTests(unittest.TestCase):
    def make_story(self):
        s1 = Source("Primărie", "official", ["Râmnicu Vâlcea"], 0.95, 0.90, 0.80, 0.85, 0.90, 0.10)
        s2 = Source("ISU", "official", ["Vâlcea"], 0.98, 0.95, 0.95, 0.90, 0.95, 0.05)
        signal = Signal(
            title="Trafic restricționat temporar în centrul orașului",
            summary="Măsura afectează circulația locală și necesită rute alternative.",
            geography=["Râmnicu Vâlcea"],
            source_ids=[s1.id, s2.id],
            public_interest=0.90, impact=0.80, novelty=0.55, utility=0.95, factual_risk=0.10
        )
        confirmed = "Circulația va fi restricționată temporar în zona centrală."
        evidence = [
            Evidence(s1.id, confirmed, confidence=0.95),
            Evidence(s2.id, confirmed, confidence=0.90),
        ]
        kernel = FactKernel(
            confirmed_facts=[confirmed],
            uncertain_claims=[],
            affected_groups=["șoferi", "transport public"],
            next_expected_event="Ridicarea restricției după finalizarea lucrărilor.",
            evidence=evidence
        )
        return StoryObject(signal=signal, fact_kernel=kernel), {s1.id: s1, s2.id: s2}

    def test_end_to_end_pipeline(self):
        story, sources = self.make_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            result = Orchestrator(root).run(story, sources)
            self.assertEqual(result.state, StoryState.PACKAGED)
            self.assertGreaterEqual(result.trust_score, 70)
            self.assertIn("facebook", result.content_pack)

            checkpoint_files = list(root.glob(f"{story.id}_v{story.version}_*.json"))
            self.assertEqual(len(checkpoint_files), 4)
            self.assertEqual(
                {path.stem.rsplit("_", 1)[-1] for path in checkpoint_files},
                {"signal", "verified", "drafted", "packaged"},
            )

            decision = Orchestrator(root).editorial_gate_store.load_story(story.id)
            self.assertEqual(decision["decision"], "auto_draft")
            self.assertEqual(decision["reasons"], [])


if __name__ == "__main__":
    unittest.main()
