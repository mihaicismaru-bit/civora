from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from cj_road_shadow_lane import evaluate_signal, verify_document  # noqa: E402


class CjRoadShadowLaneTests(unittest.TestCase):
    AS_OF = date(2026, 9, 18)

    def _signal(self, **overrides):
        row = {
            "signal_id": "cj-road-test",
            "source_id": "signal-cj-valcea-drumuri",
            "article_url": "https://cjvalcea.ro/2026/09/17/asfaltam-dj-676d/",
            "title": "Lucrări pe DJ 676D",
            "summary_excerpt": "Consiliul Județean anunță lucrări pe DJ 676D.",
            "signal_class": "ROADWORKS_NOTICE",
            "route_refs": ["DJ 676D"],
            "publication_date": "2026-09-17",
            "publication_date_status": "URL_PATH_AND_ARTICLE_TIME_MATCH",
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
        }
        row.update(overrides)
        return row

    def _document(self, signals):
        return {
            "source_id": "signal-cj-valcea-drumuri",
            "discovered_article_count": len(signals),
            "signals": signals,
            "fetch_holds": [],
            "policy": {
                "publication_authority": "NONE",
                "signal_only": True,
                "public_projection": False,
                "auto_publication": False,
                "persistence_allowed": False,
                "fact_kernel_authority": False,
                "current_status_claim_allowed": False,
            },
        }

    def test_fresh_roadworks_is_blocked_for_material_fact_extraction(self):
        row = evaluate_signal(self._signal(), as_of=self.AS_OF)
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "material_fact_extraction_required")
        self.assertEqual(row["material_fact_status"], "UNADJUDICATED")
        self.assertFalse(row["fact_kernel_promotion_allowed"])
        self.assertFalse(row["writer_allowed"])
        self.assertNotIn("fact_kernel", row)
        self.assertNotIn("article_package", row)

    def test_closure_requires_current_operational_recheck(self):
        row = evaluate_signal(
            self._signal(signal_class="ROAD_CLOSURE_NOTICE"),
            as_of=self.AS_OF,
        )
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "current_operational_status_recheck_required")
        self.assertFalse(row["current_status_claim_allowed"])

    def test_stale_signal_is_no_story_for_live_pilot(self):
        row = evaluate_signal(self._signal(publication_date="2026-09-01"), as_of=self.AS_OF)
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "stale_source_article_for_live_news_pilot")

    def test_adapter_hold_is_no_story(self):
        row = evaluate_signal(
            self._signal(signal_class="HOLD", lifecycle="HOLD_INSUFFICIENT_OR_AMBIGUOUS_ROAD_SIGNAL"),
            as_of=self.AS_OF,
        )
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "HOLD_INSUFFICIENT_OR_AMBIGUOUS_ROAD_SIGNAL")

    def test_future_date_and_missing_route_block(self):
        future = evaluate_signal(self._signal(publication_date="2026-09-19"), as_of=self.AS_OF)
        self.assertEqual(future["state"], "BLOCKED")
        self.assertEqual(future["reason"], "future_publication_date_anomaly")
        missing_route = evaluate_signal(self._signal(route_refs=[]), as_of=self.AS_OF)
        self.assertEqual(missing_route["state"], "BLOCKED")
        self.assertEqual(missing_route["reason"], "explicit_county_road_reference_missing")

    def test_authority_drift_blocks(self):
        row = evaluate_signal(self._signal(publication_authority="PUBLISH"), as_of=self.AS_OF)
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "source_contract_authority_violation")

    def test_document_policy_must_remain_fail_closed(self):
        doc = self._document([self._signal()])
        result = verify_document(doc, as_of=self.AS_OF)
        self.assertEqual(result["status"], "PASS_SHADOW")
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertEqual(result["verified_written_shadow_count"], 0)
        self.assertEqual(result["fabricated_claim_count"], 0)

        bad = self._document([self._signal()])
        bad["policy"]["current_status_claim_allowed"] = True
        blocked = verify_document(bad, as_of=self.AS_OF)
        self.assertEqual(blocked["status"], "BLOCKED_SOURCE_CONTRACT")
        self.assertEqual(blocked["rows"], [])


if __name__ == "__main__":
    unittest.main()
