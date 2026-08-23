import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.fact_kernel import FactKernelStore
from civora.models import Evidence, FactKernel, Signal, Source, StoryObject
from civora.orchestrator import Orchestrator


class FactKernelOrchestratorTests(unittest.TestCase):
    def test_verified_story_persists_fact_kernel_before_drafting(self):
        source_a = Source(
            "Primărie",
            "official",
            ["Râmnicu Vâlcea"],
            0.95,
            0.90,
            0.80,
            0.85,
            0.90,
            0.10,
        )
        source_b = Source(
            "ISU",
            "official",
            ["Vâlcea"],
            0.98,
            0.95,
            0.95,
            0.90,
            0.95,
            0.05,
        )
        statement = "Circulația va fi restricționată temporar în zona centrală."
        story = StoryObject(
            signal=Signal(
                title="Trafic restricționat temporar în centrul orașului",
                summary="Măsura afectează circulația locală.",
                geography=["Râmnicu Vâlcea"],
                source_ids=[source_a.id, source_b.id],
                public_interest=0.9,
                impact=0.8,
                novelty=0.5,
                utility=0.9,
                factual_risk=0.1,
            ),
            fact_kernel=FactKernel(
                confirmed_facts=[statement],
                uncertain_claims=[],
                affected_groups=["șoferi"],
                next_expected_event="Ridicarea restricției.",
                evidence=[
                    Evidence(source_a.id, statement, confidence=0.95),
                    Evidence(source_b.id, statement, confidence=0.90),
                ],
            ),
        )

        with TemporaryDirectory() as td:
            root = Path(td)
            result = Orchestrator(root).run(
                story,
                {source_a.id: source_a, source_b.id: source_b},
            )
            persisted = FactKernelStore(root / "fact_kernels.json").load_story(
                story.id
            )
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["story_id"], story.id)
            self.assertEqual(persisted["verification_status"], "verified")
            self.assertEqual(persisted["gate"], "grounded")
            self.assertEqual(persisted["provenance_coverage"], 1.0)
            self.assertEqual(result.article["verification_status"], "verified")


if __name__ == "__main__":
    unittest.main()
