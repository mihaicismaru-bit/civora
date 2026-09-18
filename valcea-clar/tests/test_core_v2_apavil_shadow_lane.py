from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from apavil_shadow_lane import verify_document  # noqa: E402


class ApavilShadowLaneTests(unittest.TestCase):
    def _document(self, *, dates=None, geography=None, signal_class="SCHEDULED_WATER_OUTAGE"):
        return {
            "source_id": "signal-apavil-valcea-scheduled-outages",
            "source_content_sha256": "a" * 64,
            "signals": [
                {
                    "signal_id": "apavil-outage-abc123",
                    "source_id": "signal-apavil-valcea-scheduled-outages",
                    "source_name": "APAVIL S.A. Vâlcea — Opriri programate",
                    "source_url": "https://apavil.ro/?page_id=962",
                    "source_tier": "T1",
                    "title": "Anunț întrerupere furnizare apă potabilă în municipiul Râmnicu Vâlcea în data de 21.09.2026, în intervalul 09:00 - 15:00",
                    "signal_class": signal_class,
                    "effective_dates": dates if dates is not None else ["2026-09-21"],
                    "effective_date_status": "EXPLICIT_VISIBLE_TEXT",
                    "time_range": {"start": "09:00", "end": "15:00", "basis": "EXPLICIT_VISIBLE_TEXT"},
                    "explicit_geography": geography if geography is not None else ["municipiul Râmnicu Vâlcea"],
                    "current_status_claim_allowed": False,
                    "fact_kernel_authority": False,
                    "publication_authority": "NONE",
                }
            ],
        }

    def test_explicit_future_schedule_builds_kernel_and_claim_bound_article(self):
        result = verify_document(self._document(), as_of=date(2026, 9, 18))
        self.assertEqual(result["verified_written_shadow_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["state"], "VERIFIED_WRITTEN_SHADOW")
        self.assertEqual(row["publication_authority"], "NONE")
        self.assertFalse(row["current_status_claim_allowed"])
        self.assertEqual(row["integrity"]["status"], "PASS")
        self.assertEqual(row["integrity"]["fabricated_claims"], 0)
        self.assertGreaterEqual(len(row["article_package"]["body"]), 180)
        self.assertIn("programată", row["article_package"]["body"])
        self.assertIn("source-snapshot:" + "a" * 64, row["fact_kernel"]["evidence_ids"])

    def test_past_schedule_is_truthful_no_story(self):
        result = verify_document(self._document(dates=["2026-09-17"]), as_of=date(2026, 9, 18))
        row = result["rows"][0]
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "stale_scheduled_outage")
        self.assertEqual(result["verified_written_shadow_count"], 0)

    def test_missing_explicit_geography_blocks_instead_of_inferring(self):
        result = verify_document(self._document(geography=[]), as_of=date(2026, 9, 18))
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "explicit_geography_missing")

    def test_non_material_signal_terminates_no_story(self):
        result = verify_document(self._document(signal_class="HOLD"), as_of=date(2026, 9, 18))
        row = result["rows"][0]
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "not_scheduled_water_outage")


if __name__ == "__main__":
    unittest.main()
