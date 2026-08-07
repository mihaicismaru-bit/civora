import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.contradictions import ExplicitContradictionEngine
from civora.fact_contradictions import FactContradictionStore, FactContradictionStoreError
from civora.fact_kernel import FactKernelStore
from civora.models import (
    Evidence,
    EvidencePolarity,
    EvidenceRelation,
    FactKernel,
    Signal,
    Source,
    StoryObject,
)
from civora.orchestrator import Orchestrator


class ContradictionTests(unittest.TestCase):
    def make_story(self, support_confidence=0.9, contradiction_confidence=0.9):
        supporting = Source("Primarie", "official", ["Valcea"], 0.95, 0.95, 0.9, 0.9, 0.9, 0.05)
        contradicting = Source("ISU", "official", ["Valcea"], 0.95, 0.95, 0.9, 0.9, 0.9, 0.05)
        statement = "Circulatia este restrictionata temporar in centru."
        contrary = "Circulatia functioneaza normal in centru."
        signal = Signal(
            title="Trafic in centru",
            summary="Sursele raporteaza situatia traficului.",
            geography=["Valcea"],
            source_ids=[supporting.id, contradicting.id],
            public_interest=0.9,
            impact=0.8,
            novelty=0.5,
            utility=0.9,
            factual_risk=0.2,
        )
        evidence = [
            Evidence(supporting.id, statement, confidence=support_confidence),
            Evidence(contradicting.id, contrary, confidence=contradiction_confidence),
        ]
        relation = EvidenceRelation(
            target_statement=statement,
            source_id=contradicting.id,
            evidence_claim=contrary,
            polarity=EvidencePolarity.CONTRADICT,
        )
        kernel = FactKernel(
            confirmed_facts=[statement],
            uncertain_claims=[],
            affected_groups=["soferi"],
            next_expected_event=None,
            evidence=evidence,
            evidence_relations=[relation],
        )
        return StoryObject(signal=signal, fact_kernel=kernel), {supporting.id: supporting, contradicting.id: contradicting}

    def kernel_record(self, story):
        with TemporaryDirectory() as td:
            return FactKernelStore(Path(td) / "kernels.json").persist_story(story)

    def test_disputed_when_strong_support_and_contradiction_coexist(self):
        story, _ = self.make_story()
        record = self.kernel_record(story)
        result = ExplicitContradictionEngine().evaluate(record, story.fact_kernel.evidence_relations)
        assessment = result["assessments"][0]
        self.assertEqual(assessment["status"], "disputed")
        self.assertEqual(result["gate"], "conflict_review")
        self.assertEqual(len(assessment["supporting_source_ids"]), 1)
        self.assertEqual(len(assessment["contradicting_source_ids"]), 1)

    def test_uncontested_without_explicit_contradiction(self):
        story, _ = self.make_story()
        record = self.kernel_record(story)
        result = ExplicitContradictionEngine().evaluate(record, [])
        self.assertEqual(result["assessments"][0]["status"], "uncontested")
        self.assertEqual(result["gate"], "clear")

    def test_contradicted_when_contradiction_is_strong_and_support_is_weak(self):
        story, _ = self.make_story(support_confidence=0.3, contradiction_confidence=0.9)
        record = self.kernel_record(story)
        result = ExplicitContradictionEngine().evaluate(record, story.fact_kernel.evidence_relations)
        self.assertEqual(result["assessments"][0]["status"], "contradicted")

    def test_invalid_relation_target_fails_closed(self):
        story, _ = self.make_story()
        record = self.kernel_record(story)
        bad = EvidenceRelation(
            target_statement="Statement absent from kernel",
            source_id=story.fact_kernel.evidence[1].source_id,
            evidence_claim=story.fact_kernel.evidence[1].claim,
            polarity=EvidencePolarity.CONTRADICT,
        )
        with self.assertRaises(ValueError):
            ExplicitContradictionEngine().evaluate(record, [bad])

    def test_same_evidence_cannot_support_and_contradict_same_target(self):
        story, _ = self.make_story()
        record = self.kernel_record(story)
        contradiction = story.fact_kernel.evidence_relations[0]
        support = EvidenceRelation(
            target_statement=contradiction.target_statement,
            source_id=contradiction.source_id,
            evidence_claim=contradiction.evidence_claim,
            polarity=EvidencePolarity.SUPPORT,
        )
        with self.assertRaises(ValueError):
            ExplicitContradictionEngine().evaluate(record, [contradiction, support])

    def test_durable_store_is_idempotent(self):
        story, _ = self.make_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            kernel = FactKernelStore(root / "kernels.json").persist_story(story)
            store = FactContradictionStore(root / "contradictions.json")
            first = store.persist_kernel(kernel, story.fact_kernel.evidence_relations)
            second = store.persist_kernel(kernel, story.fact_kernel.evidence_relations)
            self.assertEqual(first["report_id"], second["report_id"])
            self.assertEqual(store.load_story(story.id)["result"]["gate"], "conflict_review")

    def test_durable_store_rejects_invalid_relation(self):
        story, _ = self.make_story()
        bad = EvidenceRelation(
            target_statement="missing",
            source_id=story.fact_kernel.evidence[1].source_id,
            evidence_claim=story.fact_kernel.evidence[1].claim,
            polarity=EvidencePolarity.CONTRADICT,
        )
        with TemporaryDirectory() as td:
            root = Path(td)
            kernel = FactKernelStore(root / "kernels.json").persist_story(story)
            with self.assertRaises(FactContradictionStoreError):
                FactContradictionStore(root / "contradictions.json").persist_kernel(kernel, [bad])

    def test_orchestrator_persists_contradiction_report(self):
        story, sources = self.make_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            result = Orchestrator(root).run(story, sources)
            report = FactContradictionStore(root / "fact_contradictions.json").load_story(story.id)
            self.assertIsNotNone(report)
            self.assertEqual(report["result"]["gate"], "conflict_review")
            self.assertEqual(result.state.value, "packaged")


if __name__ == "__main__":
    unittest.main()
