import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from instagram_visual_identity import compare_vectors, identity_decision


class InstagramVisualIdentityTest(unittest.TestCase):
    def test_exact_and_near_reencoded_vectors_match(self):
        left = [(i * 17 + (i // 11) * 7) % 256 for i in range(1024)]
        exact = compare_vectors(left, list(left))
        self.assertTrue(exact["same_visual"])
        self.assertEqual(exact["correlation"], 1.0)
        self.assertEqual(exact["mae_normalized"], 0.0)

        near = [max(0, min(255, value + (1 if i % 5 else -1))) for i, value in enumerate(left)]
        transformed = compare_vectors(left, near)
        self.assertTrue(transformed["same_visual"])
        self.assertGreaterEqual(transformed["correlation"], 0.96)
        self.assertLessEqual(transformed["mae_normalized"], 0.12)

    def test_different_visual_fails_closed(self):
        left = [(i * 13) % 256 for i in range(1024)]
        right = [255 - value for value in left]
        result = compare_vectors(left, right)
        self.assertFalse(result["same_visual"])
        self.assertLess(result["correlation"], 0.0)

    def test_identity_requires_exactly_one_remote_match(self):
        unique = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": True, "composite_score": 0.97},
            {"remote_id": "b", "media_url": "https://example.test/b.jpg", "same_visual": False, "composite_score": 0.31},
        ])
        self.assertTrue(unique["identity_bound"])
        self.assertEqual(unique["matched_remote_id"], "a")
        self.assertEqual(unique["identity_state"], "APPROVED_VISUAL_MATCHED_REMOTE_IMAGE")

        ambiguous = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": True, "composite_score": 0.97},
            {"remote_id": "b", "media_url": "https://example.test/b.jpg", "same_visual": True, "composite_score": 0.96},
        ])
        self.assertFalse(ambiguous["identity_bound"])
        self.assertEqual(ambiguous["identity_state"], "AMBIGUOUS_MULTIPLE_REMOTE_MATCHES")

        none = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": False, "composite_score": 0.55},
        ])
        self.assertFalse(none["identity_bound"])
        self.assertEqual(none["identity_state"], "NO_REMOTE_IMAGE_MATCHED_APPROVED_VISUAL")


if __name__ == "__main__":
    unittest.main()
