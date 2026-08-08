import unittest

from civora.evidence_rendering import EvidenceConstrainedRenderer, EvidenceRenderingError
from civora.models import FactKernel, Signal, StoryObject, StoryState
from civora.pipeline import PipelineError, generate_article, generate_content_pack


class AuthorizedPipelineTests(unittest.TestCase):
    def make_story(self):
        signal = Signal(
            title="RAW SIGNAL TITLE MUST NOT LEAK",
            summary="RAW SIGNAL SUMMARY MUST NOT LEAK",
            geography=["Test"],
            source_ids=[],
            public_interest=0.5,
            impact=0.5,
            novelty=0.5,
            utility=0.5,
            factual_risk=0.1,
        )
        kernel = FactKernel(
            confirmed_facts=["Raw fact that must not be consumed directly."],
            uncertain_claims=["Raw uncertainty that must not leak directly."],
            affected_groups=[],
            next_expected_event="RAW NEXT EXPECTED EVENT MUST NOT LEAK",
            evidence=[],
        )
        return StoryObject(signal=signal, fact_kernel=kernel, state=StoryState.READY)

    def authorization(self, story, statements=None):
        statements = statements or ["Authorized fact only."]
        return {
            "story_id": story.id,
            "kernel_id": "kernel-1",
            "kernel_revision": 1,
            "kernel_semantic_hash": "hash-1",
            "editorial_decision_id": "decision-1",
            "authorization_mode": "auto_draft",
            "authorized_facts": [
                {"fact_id": f"fact-{index}", "statement": statement}
                for index, statement in enumerate(statements, start=1)
            ],
            "authorized_uncertain_claims": [],
        }

    def test_generate_article_requires_explicit_authorized_projection(self):
        story = self.make_story()
        with self.assertRaises(TypeError):
            generate_article(story)

    def test_article_uses_only_authorized_projection_not_raw_fact_kernel_or_signal(self):
        story = self.make_story()
        authorization = self.authorization(
            story,
            ["Authorized primary fact.", "Authorized contextual fact."],
        )
        result = generate_article(story, authorization)

        self.assertEqual(
            result.article["confirmed_facts"],
            ["Authorized primary fact.", "Authorized contextual fact."],
        )
        self.assertEqual(result.article["headline"], "Authorized primary fact.")
        self.assertEqual(
            result.article["dek"],
            "Authorized primary fact. Authorized contextual fact.",
        )
        self.assertEqual(result.article["why_it_matters"], "Authorized contextual fact.")
        self.assertIsNone(result.article["next"])
        self.assertEqual(result.article["what_is_uncertain"], [])
        self.assertEqual(result.article["rendering"]["source"], "authorized_projection")
        self.assertEqual(result.article["authorization"]["editorial_decision_id"], "decision-1")

        serialized = repr(result.article)
        self.assertNotIn("Raw fact", serialized)
        self.assertNotIn("RAW SIGNAL TITLE", serialized)
        self.assertNotIn("RAW SIGNAL SUMMARY", serialized)
        self.assertNotIn("RAW NEXT EXPECTED EVENT", serialized)

    def test_packaging_reuses_evidence_constrained_surfaces(self):
        story = self.make_story()
        generate_article(story, self.authorization(story, ["Authorized headline fact."]))
        result = generate_content_pack(story)
        rendered = repr(result.content_pack)
        self.assertIn("Authorized headline fact.", rendered)
        self.assertEqual(result.content_pack["audit"]["rendering_source"], "authorized_projection")
        self.assertNotIn("RAW SIGNAL TITLE", rendered)
        self.assertNotIn("RAW SIGNAL SUMMARY", rendered)
        self.assertNotIn("RAW NEXT EXPECTED EVENT", rendered)

    def test_renderer_fails_closed_on_malformed_projection(self):
        with self.assertRaisesRegex(EvidenceRenderingError, "at least one authorized fact"):
            EvidenceConstrainedRenderer().render(
                {"authorized_facts": [], "authorized_uncertain_claims": []}
            )
        with self.assertRaisesRegex(EvidenceRenderingError, "empty statement"):
            EvidenceConstrainedRenderer().render(
                {
                    "authorized_facts": [{"fact_id": "fact-1", "statement": ""}],
                    "authorized_uncertain_claims": [],
                }
            )

    def test_wrong_story_projection_fails_closed(self):
        story = self.make_story()
        with self.assertRaisesRegex(PipelineError, "different story"):
            generate_article(
                story,
                {
                    "story_id": "other-story",
                    "authorized_facts": [{"fact_id": "fact-1", "statement": "Fact."}],
                    "authorized_uncertain_claims": [],
                },
            )


if __name__ == "__main__":
    unittest.main()
