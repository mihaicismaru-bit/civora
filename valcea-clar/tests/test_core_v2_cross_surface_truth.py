from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from validate_cross_surface_visual_truth import validate_documents  # noqa: E402


def fixtures(state: str = "CONSISTENT"):
    candidates = {
        "schema_version": "1.2",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "first_ten_candidate_ids": ["story-a"],
        "rows": [
            {
                "story_id": "story-a",
                "canonical_site_visual_binding_state": state,
            }
        ],
    }
    visual = {
        "schema_version": "1.1",
        "publication_authority": "NONE",
        "candidate_count": 1,
        "canonical_consistent_count": 1 if state == "CONSISTENT" else 0,
        "cross_surface_divergent_count": 0 if state in {"CONSISTENT", "NOT_READY", ""} else 1,
        "results": [
            {
                "story_id": "story-a",
                "canonical_site_visual_binding_state": state,
                "readback_ok": state == "CONSISTENT",
            }
        ],
    }
    expected_blocker = None
    if not state:
        expected_blocker = "CROSS_SURFACE_VISUAL_BINDING_UNKNOWN"
    elif state == "NOT_READY":
        expected_blocker = "CROSS_SURFACE_VISUAL_BINDING_NOT_READY"
    elif state != "CONSISTENT":
        expected_blocker = "CROSS_SURFACE_VISUAL_BINDING_DIVERGENCE"
    gates = {
        "schema_version": "1.1",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "candidate_count": 1,
        "truth_complete_count": 1 if state == "CONSISTENT" else 0,
        "rows": [
            {
                "story_id": "story-a",
                "canonical_site_visual_binding_state": state or None,
                "truth_state": "REPLAY_TRUTH_COMPLETE" if state == "CONSISTENT" else "BLOCKED",
                "blockers": [] if expected_blocker is None else [expected_blocker],
            }
        ],
    }
    return candidates, visual, gates


class CrossSurfaceRuntimeTruthTests(unittest.TestCase):
    def test_consistent_binding_passes_without_cross_surface_blocker(self):
        candidates, visual, gates = fixtures("CONSISTENT")
        result = validate_documents(candidates, visual, gates)
        self.assertEqual(result["canonical_consistent_count"], 1)
        self.assertEqual(result["cross_surface_divergent_count"], 0)

    def test_divergent_binding_requires_explicit_blocker(self):
        candidates, visual, gates = fixtures("SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        result = validate_documents(candidates, visual, gates)
        self.assertEqual(result["cross_surface_divergent_count"], 1)

    def test_gate_cannot_drop_divergence(self):
        candidates, visual, gates = fixtures("SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        tampered = deepcopy(gates)
        tampered["rows"][0]["blockers"] = []
        with self.assertRaises(AssertionError):
            validate_documents(candidates, visual, tampered)

    def test_visual_replay_cannot_change_binding_state(self):
        candidates, visual, gates = fixtures("SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        tampered = deepcopy(visual)
        tampered["results"][0]["canonical_site_visual_binding_state"] = "CONSISTENT"
        with self.assertRaises(AssertionError):
            validate_documents(candidates, tampered, gates)

    def test_truth_complete_requires_consistent_binding(self):
        candidates, visual, gates = fixtures("SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        tampered = deepcopy(gates)
        tampered["rows"][0]["truth_state"] = "REPLAY_TRUTH_COMPLETE"
        with self.assertRaises(AssertionError):
            validate_documents(candidates, visual, tampered)


if __name__ == "__main__":
    unittest.main()
