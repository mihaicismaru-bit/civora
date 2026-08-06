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
        evidence = [
            Evidence(s1.id, "Restricția a fost anunțată oficial.", confidence=0.95),
            Evidence(s2.id, "Măsura este confirmată operațional.", confidence=0.90),
        ]
        kernel = FactKernel(
            confirmed_facts=["Circulația va fi restricționată temporar în zona centrală."],
            uncertain_claims=[],
            affected_groups=["șoferi", "transport public"],
            next_expected_event="Ridicarea restricției după finalizarea lucrărilor.",
            evidence=evidence
        )
        return StoryObject(signal=signal, fact_kernel=kernel), {s1.id:s1, s2.id:s2}

    def test_end_to_end_pipeline(self):
        story, sources = self.make_story()
        with TemporaryDirectory() as td:
            result = Orchestrator(Path(td)).run(story, sources)
            self.assertEqual(result.state, StoryState.PACKAGED)
            self.assertGreaterEqual(result.trust_score, 70)
            self.assertIn("facebook", result.content_pack)
            self.assertEqual(len(list(Path(td).glob("*.json"))), 4)

if __name__ == "__main__":
    unittest.main()
