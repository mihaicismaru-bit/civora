import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from civora.editorial_approval import EditorialApprovalError, EditorialApprovalStore
from civora.models import (
    Evidence,
    EvidencePolarity,
    EvidenceRelation,
    FactKernel,
    Signal,
    Source,
    StoryObject,
    StoryState,
)
from civora.orchestrator import Orchestrator, OrchestratorError


class EditorialApprovalTests(unittest.TestCase):
    def review_decision(self):
        return {
            "decision_id": "d" * 64,
            "story_id": "story-1",
            "kernel_semantic_hash": "a" * 64,
            "decision": "review",
        }

    def disputed_story(self):
        s1 = Source("A", "official", ["Valcea"], .95, .95, .95, .95, .95, .05)
        s2 = Source("B", "official", ["Valcea"], .95, .95, .95, .95, .95, .05)
        s3 = Source("C", "official", ["Valcea"], .95, .95, .95, .95, .95, .05)
        fact = "Drumul este deschis traficului."
        contrary = "Drumul este inchis traficului."
        signal = Signal(
            title="Situatie trafic",
            summary="Sursele raporteaza situatia traficului.",
            geography=["Valcea"],
            source_ids=[s1.id, s2.id, s3.id],
            public_interest=.8,
            impact=.8,
            novelty=.5,
            utility=.8,
            factual_risk=.2,
        )
        kernel = FactKernel(
            confirmed_facts=[fact],
            uncertain_claims=[],
            affected_groups=["soferi"],
            next_expected_event=None,
            evidence=[
                Evidence(s1.id, fact, confidence=.9),
                Evidence(s2.id, fact, confidence=.9),
                Evidence(s3.id, contrary, confidence=.9),
            ],
            evidence_relations=[
                EvidenceRelation(
                    target_statement=fact,
                    source_id=s3.id,
                    evidence_claim=contrary,
                    polarity=EvidencePolarity.CONTRADICT,
                )
            ],
        )
        story = StoryObject(signal=signal, fact_kernel=kernel)
        return story, {s1.id: s1, s2.id: s2, s3.id: s3}

    def weak_support_story(self):
        source = Source("A", "official", ["Valcea"], .95, .95, .95, .95, .95, .05)
        fact = "Restrictia temporara este in vigoare."
        signal = Signal(
            title="Restrictie temporara",
            summary="Traficul local necesita o ruta alternativa.",
            geography=["Valcea"],
            source_ids=[source.id],
            public_interest=.8,
            impact=.8,
            novelty=.5,
            utility=.8,
            factual_risk=.2,
        )
        kernel = FactKernel(
            confirmed_facts=[fact],
            uncertain_claims=[],
            affected_groups=["soferi"],
            next_expected_event=None,
            evidence=[Evidence(source.id, fact, confidence=.95)],
        )
        return StoryObject(signal=signal, fact_kernel=kernel), {source.id: source}

    def test_review_decision_creates_idempotent_pending_case(self):
        with TemporaryDirectory() as td:
            store = EditorialApprovalStore(Path(td) / "approval.json")
            first = store.ensure_pending(self.review_decision())
            second = store.ensure_pending(self.review_decision())
            self.assertEqual(first["case_id"], second["case_id"])
            self.assertEqual(first["state"], "pending")
            self.assertEqual(len(first["history"]), 1)

    def test_pending_case_can_be_approved_with_audit(self):
        with TemporaryDirectory() as td:
            store = EditorialApprovalStore(Path(td) / "approval.json")
            pending = store.ensure_pending(self.review_decision())
            approved = store.decide(
                pending["case_id"],
                action="approved",
                actor="editor-1",
                reason="conflict resolved from primary record",
            )
            self.assertEqual(approved["state"], "approved")
            self.assertEqual(approved["history"][-1]["actor"], "editor-1")
            self.assertEqual(approved["history"][-1]["from"], "pending")

    def test_resolved_case_cannot_be_reused_or_changed(self):
        with TemporaryDirectory() as td:
            store = EditorialApprovalStore(Path(td) / "approval.json")
            pending = store.ensure_pending(self.review_decision())
            store.decide(
                pending["case_id"],
                action="rejected",
                actor="editor-1",
                reason="evidence remains contradictory",
            )
            with self.assertRaises(EditorialApprovalError):
                store.decide(
                    pending["case_id"],
                    action="approved",
                    actor="editor-2",
                    reason="late override",
                )

    def test_decision_requires_actor_and_reason(self):
        with TemporaryDirectory() as td:
            store = EditorialApprovalStore(Path(td) / "approval.json")
            pending = store.ensure_pending(self.review_decision())
            with self.assertRaises(EditorialApprovalError):
                store.decide(pending["case_id"], action="approved", actor="", reason="ok")
            with self.assertRaises(EditorialApprovalError):
                store.decide(pending["case_id"], action="approved", actor="editor", reason="")

    def test_orchestrator_creates_pending_case_for_editorial_review(self):
        story, sources = self.disputed_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            result = Orchestrator(root).run(story, sources)
            self.assertEqual(result.state, StoryState.BLOCKED)
            case = EditorialApprovalStore(root / "editorial_approval.json").load_story(story.id)
            self.assertIsNotNone(case)
            self.assertEqual(case["state"], "pending")

    def test_approval_allows_controlled_pipeline_reentry_for_grounded_uncontested_review_fact(self):
        story, sources = self.weak_support_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            orchestrator = Orchestrator(root)
            blocked = orchestrator.run(story, sources)
            self.assertEqual(blocked.state, StoryState.BLOCKED)
            case = orchestrator.editorial_approval_store.load_story(story.id)
            orchestrator.editorial_approval_store.decide(
                case["case_id"],
                action="approved",
                actor="editor-1",
                reason="manual verification completed",
            )
            result = orchestrator.resume_after_approval(story)
            self.assertEqual(result.state, StoryState.PACKAGED)
            self.assertEqual(result.article["authorization"]["authorization_mode"], "human_approved")
            self.assertIsNotNone(result.content_pack)

    def test_approval_cannot_override_explicitly_disputed_fact(self):
        story, sources = self.disputed_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            orchestrator = Orchestrator(root)
            orchestrator.run(story, sources)
            case = orchestrator.editorial_approval_store.load_story(story.id)
            orchestrator.editorial_approval_store.decide(
                case["case_id"],
                action="approved",
                actor="editor-1",
                reason="manual review requested publication",
            )
            with self.assertRaisesRegex(OrchestratorError, "no confirmed facts are authorized"):
                orchestrator.resume_after_approval(story)

    def test_reentry_fails_without_approval(self):
        story, sources = self.weak_support_story()
        with TemporaryDirectory() as td:
            root = Path(td)
            orchestrator = Orchestrator(root)
            orchestrator.run(story, sources)
            with self.assertRaises(OrchestratorError):
                orchestrator.resume_after_approval(story)


if __name__ == "__main__":
    unittest.main()
