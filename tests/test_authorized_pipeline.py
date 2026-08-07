import unittest

from civora.models import FactKernel, Signal, StoryObject, StoryState
from civora.pipeline import PipelineError, generate_article


class AuthorizedPipelineTests(unittest.TestCase):
    def make_story(self):
        signal = Signal(
            title="Authorized headline",
            summary="Authorized summary",
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
            next_expected_event=None,
            evidence=[],
        )
        return StoryObject(signal=signal, fact_kernel=kernel, state=StoryState.READY)

    def test_generate_article_requires_explicit_authorized_projection(self):
        story = self.make_story()
        with self.assertRaises(TypeError):
            generate_article(story)

    def test_article_uses_only_authorized_projection_not_raw_fact_kernel(self):
        story = self.make_story()
        authorization = {
            "story_id": story.id,
            "kernel_id": "kernel-1",
            "kernel_revision": 1,
            "kernel_semantic_hash": "hash-1",
            "editorial_decision_id": "decision-1",
            "authorization_mode": "auto_draft",
            "authorized_facts": [
                {"fact_id": "fact-1", "statement": "Authorized fact only."}
            ],
            "authorized_uncertain_claims": [],
        }
        result = generate_article(story, authorization)
        self.assertEqual(result.article["confirmed_facts"], ["Authorized fact only."])
        self.assertEqual(result.article["what_is_uncertain"], [])
        self.assertNotIn("Raw fact", result.article["confirmed_facts"][0])
        self.assertEqual(result.article["authorization"]["editorial_decision_id"], "decision-1")

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
