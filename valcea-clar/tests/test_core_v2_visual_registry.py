import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from visual_readback import ALLOWED_RIGHTS_BASES


class CoreV2VisualRegistryTest(unittest.TestCase):
    def test_registry_is_shadow_only_and_explicit(self):
        path = ROOT / "visual_registry.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc.get("mode"), "SHADOW_ONLY")
        self.assertEqual(doc.get("publication_authority"), "NONE")
        stories = doc.get("stories") or {}
        self.assertEqual(
            set(stories),
            {"hcl-343-local-public-finance", "hcl-345-regulated-local-authorization"},
        )
        for story_id, assignment in stories.items():
            image = assignment.get("image") or {}
            self.assertEqual(image.get("kind"), "photograph", story_id)
            self.assertIs(image.get("synthetic"), False, story_id)
            self.assertIs(image.get("subject_match"), True, story_id)
            self.assertIs(image.get("editor_approved"), True, story_id)
            self.assertIs(image.get("contextual_archive"), True, story_id)
            self.assertIn(image.get("rights_basis"), ALLOWED_RIGHTS_BASES, story_id)
            self.assertTrue(str(image.get("source_url") or "").startswith("https://"), story_id)
            self.assertTrue(str(image.get("direct_source_url") or "").startswith("https://"), story_id)
            self.assertTrue(str(image.get("editorial_note") or "").strip(), story_id)
            self.assertTrue(str(assignment.get("approval_basis") or "").strip(), story_id)


if __name__ == "__main__":
    unittest.main()
