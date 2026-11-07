import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from historical_fact_evidence_preflight import build as build_historical_fact_preflight
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

    def test_historical_fact_preflight_is_observable_but_non_authorizing(self):
        candidates = {
            "first_ten_candidate_ids": ["story-a"],
            "rows": [{"story_id": "story-a", "real_visual_internal_evidence": True}],
        }
        receipts = {"rows": [{"story_id": "story-a", "external_delivery_truth": "BLOCKED", "receipts": {}}]}
        legacy_facts = {
            "facts": [
                {
                    "id": "story-a",
                    "status": "verified",
                    "material_fact_gate": "PASS",
                    "sources": [{"name": "Official", "url": "https://example.test/source", "tier": "T1"}],
                    "fact_kernel": {"format_hint": "straight_news", "claims": [{"text": "legacy claim"}]},
                }
            ]
        }

        def reader(url):
            return {
                "requested_url": url,
                "final_url": url,
                "http_status": 200,
                "content_type": "text/html",
                "bytes_hashed": 10,
                "content_sha256": "a" * 64,
                "bounded_read_truncated": False,
                "readback_ok": True,
            }

        preflight = build_historical_fact_preflight(candidates, legacy_facts, reader=reader)
        result = materialize(candidates, receipts, [("facts_registry.json", legacy_facts)], fact_preflight=preflight)
        row = result["rows"][0]
        self.assertEqual(row["historical_fact_preflight_state"], "LEGACY_VERIFIED_FACT_SOURCE_READBACK_ONLY")
        self.assertTrue(row["historical_legacy_verified_fact_record_present"])
        self.assertTrue(row["historical_all_t1_sources_readback_ok"])
        self.assertFalse(row["historical_explicit_core_v2_fact_kernel_present"])
        self.assertFalse(row["historical_fact_preflight_promotion_allowed"])
        self.assertEqual(row["terminal_reason"], "BLOCKED_FACT_KERNEL_EVIDENCE")
        self.assertFalse(result["historical_fact_preflight"]["promotion_allowed"])
        self.assertFalse(result["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
