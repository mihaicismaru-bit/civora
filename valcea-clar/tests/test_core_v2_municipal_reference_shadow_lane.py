from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from municipal_reference_shadow_lane import (  # noqa: E402
    EXPANDED_INDEX_URL,
    _parse_expanded_index,
    _validate_expanded_index_url,
    verify_state,
)


class MunicipalReferenceShadowLaneTests(unittest.TestCase):
    def _state(self):
        return {
            "source_id": "signal-ramnicu-valcea-local-council-decision-reference",
            "source_tier": "T1_OFFICIAL_MUNICIPALITY_FIRST_PARTY",
            "source_url": "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?openview",
            "reference_scope": "FIRST_PARTY_LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE_ONLY",
            "publication_authority": "NONE",
            "state": "REFERENCE_READY",
            "hold_reason": None,
            "decision_document_follow_allowed": False,
            "decision_document_body_fetch_allowed": False,
            "legal_effect_inference_allowed": False,
            "current_validity_inference_allowed": False,
            "amendment_status_inference_allowed": False,
            "repeal_status_inference_allowed": False,
            "implementation_status_inference_allowed": False,
            "breaking_news_promotion_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
            "references": [
                {
                    "decision_number": 345,
                    "decision_date": "2026-09-16",
                    "title_hint": "Hotărârea nr. 345 privind un serviciu public local",
                    "document_reference_url": "https://dm.primariavl.ro/dm/2026/hotarari.nsf/X/$FILE/h345.pdf",
                    "document_reference_unfollowed": True,
                    "evidence_sha256": "a" * 64,
                }
            ],
        }

    def test_expanded_index_transport_is_exact_and_bounded(self):
        self.assertEqual(_validate_expanded_index_url(EXPANDED_INDEX_URL), EXPANDED_INDEX_URL)
        for bad in (
            "http://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?OpenView&Count=500",
            "https://evil.example/dm/2026/hotarari.nsf/vwHotarariByAn?OpenView&Count=500",
            "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?OpenView&Count=9999",
            "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?OpenView&Count=500&Start=1",
            "https://dm.primariavl.ro/dm/2025/hotarari.nsf/vwHotarariByAn?OpenView&Count=500",
        ):
            with self.assertRaises(ValueError):
                _validate_expanded_index_url(bad)

    def test_flat_visible_register_parser_is_independent_of_table_row_links(self):
        html = """
        <html><body>
          <div>2026 345 hotarirea 345 - 16 septembrie 2026 - autorizatie serviciu public</div>
          <div>2026 344 hotarirea 344 - 16 septembrie 2026 - completare retea scolara</div>
        </body></html>
        """
        payload = html.encode("utf-8")
        state = _parse_expanded_index(
            html,
            payload,
            as_of=date(2026, 9, 18),
            canonical_source_url="https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?openview",
            transport_url=EXPANDED_INDEX_URL,
        )
        self.assertEqual(state["_register_entries_parsed"], 2)
        self.assertEqual(state["_current_year_references"], 2)
        self.assertEqual(state["_direct_attachment_references"], 0)
        result = verify_state(state, as_of=date(2026, 9, 18))
        self.assertEqual(result["reference_count"], 2)
        self.assertEqual(result["no_story_count"], 2)
        self.assertEqual(result["blocked_count"], 0)
        self.assertTrue(all(row["document_reference_url"] is None for row in result["rows"]))
        self.assertTrue(all(row["state"] == "NO_STORY" for row in result["rows"]))

    def test_reference_metadata_alone_is_no_story(self):
        result = verify_state(self._state(), as_of=date(2026, 9, 18))
        self.assertEqual(result["status"], "PASS_SHADOW")
        self.assertEqual(result["verified_written_shadow_count"], 0)
        self.assertEqual(result["no_story_count"], 1)
        self.assertEqual(result["blocked_count"], 0)
        row = result["rows"][0]
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "reference_metadata_only_no_material_fact_body")
        self.assertNotIn("fact_kernel", row)
        self.assertNotIn("article_package", row)

    def test_reference_without_direct_attachment_is_still_reference_only_no_story(self):
        state = self._state()
        state["references"][0]["document_reference_url"] = None
        state["references"][0]["document_reference_unfollowed"] = True
        result = verify_state(state, as_of=date(2026, 9, 18))
        self.assertEqual(result["no_story_count"], 1)
        self.assertEqual(result["blocked_count"], 0)
        self.assertFalse(result["rows"][0]["document_reference_available"])

    def test_upstream_writer_authority_change_blocks(self):
        state = self._state()
        state["writer_allowed"] = True
        result = verify_state(state, as_of=date(2026, 9, 18))
        self.assertEqual(result["status"], "BLOCKED_UPSTREAM_AUTHORITY_CHANGED")
        self.assertEqual(result["rows"], [])

    def test_followed_document_reference_blocks_contract_change(self):
        state = self._state()
        state["references"][0]["document_reference_unfollowed"] = False
        result = verify_state(state, as_of=date(2026, 9, 18))
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["rows"][0]["reason"], "reference_follow_contract_changed")

    def test_incomplete_reference_cannot_be_promoted(self):
        state = self._state()
        state["references"][0]["evidence_sha256"] = ""
        result = verify_state(state, as_of=date(2026, 9, 18))
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["rows"][0]["reason"], "reference_evidence_incomplete")


if __name__ == "__main__":
    unittest.main()
