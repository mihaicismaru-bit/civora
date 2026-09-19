from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from shadow_gate_report import build_report  # noqa: E402


def candidate(story_id: str, state: str = "CONSISTENT") -> dict:
    return {
        "story_id": story_id,
        "canonical_site_visual_binding_state": state,
        "canonical_site_visual_filename_match": state == "CONSISTENT",
        "canonical_site_visual_source_match": state == "CONSISTENT",
        "canonical_site_visual_rights_match": state == "CONSISTENT",
        "canonical_site_visual_provenance_verified": state == "CONSISTENT",
    }


class ShadowGateReportTests(unittest.TestCase):
    def test_exact_permission_visual_and_kernel_blockers(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-a"],
            "rows": [candidate("story-a", "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-a",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": {
                            "status": "FAILED",
                            "readback_ok": False,
                            "article_image_bound": False,
                            "public_image_readback_ok": False,
                            "provenance_source_readback_ok": True,
                            "direct_source_readback_ok": True,
                        },
                        "facebook": {
                            "status": "FAILED",
                            "readback_ok": False,
                            "error_code": 10,
                            "error_message": "(#10) This endpoint requires the 'pages_read_engagement' permission or the 'Page Public Content Access' feature.",
                        },
                        "instagram": {"status": "DELIVERED", "readback_ok": True},
                    },
                }
            ]
        }
        transactions = {
            "rows": [
                {
                    "story_id": "story-a",
                    "terminal_reason": "BLOCKED_FACT_KERNEL_EVIDENCE",
                }
            ]
        }
        report = build_report(candidates, receipts, transactions)
        row = report["rows"][0]
        self.assertEqual(row["truth_state"], "BLOCKED")
        self.assertIn("CROSS_SURFACE_VISUAL_BINDING_DIVERGENCE", row["blockers"])
        self.assertIn("VISUAL_ARTICLE_BINDING_FAILED", row["blockers"])
        self.assertIn("FACEBOOK_READBACK_PERMISSION_MISSING", row["blockers"])
        self.assertIn("FACT_KERNEL_EVIDENCE_MISSING", row["blockers"])
        self.assertIn("META_READ_PERMISSION_CONFIGURATION_REQUIRED", row["owner_actions"])
        self.assertEqual(row["canonical_site_visual_binding_state"], "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        self.assertFalse(report["acceptance_ready"])

    def test_fully_bound_replay_can_be_truth_complete_without_granting_acceptance(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-b"],
            "rows": [candidate("story-b")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-b",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": {
                            "status": "VERIFIED",
                            "readback_ok": True,
                            "article_image_bound": True,
                            "public_image_readback_ok": True,
                            "provenance_source_readback_ok": True,
                            "direct_source_readback_ok": True,
                        },
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": {"status": "DELIVERED", "readback_ok": True},
                    },
                }
            ]
        }
        transactions = {
            "rows": [
                {
                    "story_id": "story-b",
                    "state": "AUDIT_REPLAY_READY",
                    "terminal_reason": None,
                }
            ]
        }
        report = build_report(candidates, receipts, transactions)
        self.assertEqual(report["truth_complete_count"], 1)
        self.assertEqual(report["rows"][0]["blockers"], [])
        self.assertEqual(report["rows"][0]["truth_state"], "REPLAY_TRUTH_COMPLETE")
        self.assertEqual(report["rows"][0]["canonical_site_visual_binding_state"], "CONSISTENT")
        self.assertFalse(report["acceptance_ready"])
        self.assertEqual(report["publication_authority"], "NONE")

    def test_missing_cross_surface_binding_fails_closed(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-missing"],
            "rows": [{"story_id": "story-missing"}],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-missing",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": {"status": "VERIFIED", "readback_ok": True},
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": {"status": "DELIVERED", "readback_ok": True},
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-missing", "terminal_reason": None}]}
        report = build_report(candidates, receipts, transactions)
        blockers = report["rows"][0]["blockers"]
        self.assertEqual(blockers, ["CROSS_SURFACE_VISUAL_BINDING_UNKNOWN"])
        self.assertEqual(report["truth_complete_count"], 0)

    def test_not_ready_cross_surface_binding_is_explicit_blocker(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-not-ready"],
            "rows": [candidate("story-not-ready", "NOT_READY")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-not-ready",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": {"status": "VERIFIED", "readback_ok": True},
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": {"status": "DELIVERED", "readback_ok": True},
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-not-ready", "terminal_reason": None}]}
        report = build_report(candidates, receipts, transactions)
        self.assertIn("CROSS_SURFACE_VISUAL_BINDING_NOT_READY", report["rows"][0]["blockers"])

    def test_generic_facebook_failure_is_not_misclassified_as_permission(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-c"],
            "rows": [candidate("story-c")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-c",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": {"status": "VERIFIED", "readback_ok": True},
                        "facebook": {
                            "status": "FAILED",
                            "readback_ok": False,
                            "error_code": 190,
                            "error_message": "Invalid OAuth access token.",
                        },
                        "instagram": {"status": "DELIVERED", "readback_ok": True},
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-c", "terminal_reason": None}]}
        report = build_report(candidates, receipts, transactions)
        blockers = report["rows"][0]["blockers"]
        self.assertIn("FACEBOOK_READBACK_FAILED", blockers)
        self.assertNotIn("FACEBOOK_READBACK_PERMISSION_MISSING", blockers)
        self.assertNotIn("CROSS_SURFACE_VISUAL_BINDING_DIVERGENCE", blockers)


if __name__ == "__main__":
    unittest.main()
