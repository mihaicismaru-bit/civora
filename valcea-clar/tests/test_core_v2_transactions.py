import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from materialize_shadow_transactions import find_explicit_evidence, materialize


class ShadowTransactionTest(unittest.TestCase):
    def test_missing_structured_kernel_fails_closed(self):
        candidates = {
            "first_ten_candidate_ids": ["story-a"],
            "rows": [{"story_id": "story-a", "real_visual_internal_evidence": True}],
        }
        receipts = {"rows": [{"story_id": "story-a", "external_delivery_truth": "VERIFIED", "receipts": {}}]}
        evidence = [("legacy.json", {"items": [{"story_id": "story-a", "headline": "Only prose-ish metadata"}]})]
        result = materialize(candidates, receipts, evidence)
        self.assertEqual(result["rows"][0]["terminal_reason"], "BLOCKED_FACT_KERNEL_EVIDENCE")
        self.assertFalse(result["acceptance_ready"])

    def test_explicit_structured_evidence_can_reach_replay_ready(self):
        kernel = {
            "what": "A happened",
            "who": "Institution A",
            "where": "Râmnicu Vâlcea",
            "when": "2026-09-18",
            "why_it_matters": "Residents are affected.",
            "source": "Institution A",
            "source_url": "https://example.test/source",
            "claims": ["A happened"],
            "evidence_ids": ["ev-1"],
        }
        package = {
            "body": "A happened in Râmnicu Vâlcea. " * 12,
            "claims": [{"text": "A happened", "kernel_claim_index": 0, "evidence_ids": ["ev-1"]}],
        }
        candidates = {
            "first_ten_candidate_ids": ["story-a"],
            "rows": [{"story_id": "story-a", "real_visual_internal_evidence": True}],
        }
        receipts = {"rows": [{"story_id": "story-a", "external_delivery_truth": "VERIFIED", "receipts": {}}]}
        evidence = [("structured.json", {"items": [{"story_id": "story-a", "fact_kernel": kernel, "article_package": package}]})]
        result = materialize(candidates, receipts, evidence)
        row = result["rows"][0]
        self.assertEqual(row["state"], "AUDIT_REPLAY_READY")
        self.assertIsNone(row["terminal_reason"])
        self.assertEqual(row["integrity"]["fabricated_claims"], 0)
        self.assertEqual(result["fully_bound_replay_count"], 1)

    def test_finds_only_explicit_story_bound_evidence(self):
        docs = [("a.json", {"items": [{"story_id": "other", "fact_kernel": {"what": "x"}}]})]
        found = find_explicit_evidence("story-a", docs)
        self.assertEqual(found["matched_record_count"], 0)
        self.assertIsNone(found["kernel"])


if __name__ == "__main__":
    unittest.main()
