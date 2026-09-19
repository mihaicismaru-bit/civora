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


def visual_receipt(state: str = "CONSISTENT", *, verified: bool = True, article_bound: bool = True) -> dict:
    return {
        "status": "VERIFIED" if verified else "FAILED",
        "readback_ok": verified,
        "article_image_bound": article_bound,
        "public_image_readback_ok": verified,
        "provenance_source_readback_ok": True,
        "direct_source_readback_ok": True,
        "canonical_site_visual_binding_state": state,
    }


def instagram_receipt(*, delivered: bool = True, visual_ok: bool = True, identity_bound: bool = True) -> dict:
    return {
        "status": "DELIVERED" if delivered else "FAILED",
        "readback_ok": delivered,
        "remote_visual_readback_ok": visual_ok,
        "remote_visual_identity_bound": identity_bound,
    }


class ShadowGateReportTests(unittest.TestCase):
    def test_exact_permission_visual_and_kernel_blockers(self) -> None:
        state = "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND"
        candidates = {
            "first_ten_candidate_ids": ["story-a"],
            "rows": [candidate("story-a", state)],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-a",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": visual_receipt(state, verified=False, article_bound=False),
                        "facebook": {
                            "status": "FAILED",
                            "readback_ok": False,
                            "error_code": 10,
                            "error_message": "(#10) This endpoint requires the 'pages_read_engagement' permission or the 'Page Public Content Access' feature.",
                        },
                        "instagram": instagram_receipt(),
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
        self.assertNotIn("CROSS_SURFACE_VISUAL_BINDING_STATE_MISMATCH", row["blockers"])
        self.assertIn("VISUAL_ARTICLE_BINDING_FAILED", row["blockers"])
        self.assertIn("FACEBOOK_READBACK_PERMISSION_MISSING", row["blockers"])
        self.assertIn("FACT_KERNEL_EVIDENCE_MISSING", row["blockers"])
        self.assertIn("META_READ_PERMISSION_CONFIGURATION_REQUIRED", row["owner_actions"])
        self.assertEqual(row["canonical_site_visual_binding_state"], state)
        self.assertTrue(row["canonical_site_visual_binding_state_match"])
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
                        "visual": visual_receipt(),
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": instagram_receipt(),
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
        self.assertTrue(report["rows"][0]["canonical_site_visual_binding_state_match"])
        self.assertFalse(report["acceptance_ready"])
        self.assertEqual(report["publication_authority"], "NONE")

    def test_remote_instagram_image_presence_without_identity_is_explicit_blocker(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-ig-unbound"],
            "rows": [candidate("story-ig-unbound")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-ig-unbound",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": visual_receipt(),
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": instagram_receipt(identity_bound=False),
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-ig-unbound", "terminal_reason": "BLOCKED_EXTERNAL_DELIVERY_EVIDENCE"}]}
        report = build_report(candidates, receipts, transactions)
        row = report["rows"][0]
        self.assertIn("INSTAGRAM_VISUAL_IDENTITY_UNBOUND", row["blockers"])
        self.assertNotIn("EXTERNAL_DELIVERY_BLOCKED", row["blockers"])
        self.assertTrue(row["instagram_remote_visual_readback_ok"])
        self.assertFalse(row["instagram_remote_visual_identity_bound"])
        self.assertEqual(report["truth_complete_count"], 0)

    def test_remote_instagram_visual_readback_failure_is_distinct(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-ig-no-image"],
            "rows": [candidate("story-ig-no-image")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-ig-no-image",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": visual_receipt(),
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": instagram_receipt(visual_ok=False, identity_bound=False),
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-ig-no-image", "terminal_reason": None}]}
        report = build_report(candidates, receipts, transactions)
        self.assertIn("INSTAGRAM_REMOTE_VISUAL_READBACK_FAILED", report["rows"][0]["blockers"])

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
                        "visual": visual_receipt(""),
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": instagram_receipt(),
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
                        "visual": visual_receipt("NOT_READY"),
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": instagram_receipt(),
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-not-ready", "terminal_reason": None}]}
        report = build_report(candidates, receipts, transactions)
        self.assertIn("CROSS_SURFACE_VISUAL_BINDING_NOT_READY", report["rows"][0]["blockers"])

    def test_binding_state_mismatch_between_candidate_and_receipt_fails_closed(self) -> None:
        candidates = {
            "first_ten_candidate_ids": ["story-drift"],
            "rows": [candidate("story-drift", "CONSISTENT")],
        }
        receipts = {
            "rows": [
                {
                    "story_id": "story-drift",
                    "receipts": {
                        "site": {"status": "DELIVERED", "readback_ok": True},
                        "visual": visual_receipt("SOCIAL_VISUAL_PRESENT_SITE_UNBOUND"),
                        "facebook": {"status": "DELIVERED", "readback_ok": True},
                        "instagram": instagram_receipt(),
                    },
                }
            ]
        }
        transactions = {"rows": [{"story_id": "story-drift", "terminal_reason": None}]}
        report = build_report(candidates, receipts, transactions)
        row = report["rows"][0]
        self.assertIn("CROSS_SURFACE_VISUAL_BINDING_STATE_MISMATCH", row["blockers"])
        self.assertFalse(row["canonical_site_visual_binding_state_match"])
        self.assertEqual(row["truth_state"], "BLOCKED")

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
                        "visual": visual_receipt(),
                        "facebook": {
                            "status": "FAILED",
                            "readback_ok": False,
                            "error_code": 190,
                            "error_message": "Invalid OAuth access token.",
                        },
                        "instagram": instagram_receipt(),
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
        self.assertNotIn("CROSS_SURFACE_VISUAL_BINDING_STATE_MISMATCH", blockers)


if __name__ == "__main__":
    unittest.main()
