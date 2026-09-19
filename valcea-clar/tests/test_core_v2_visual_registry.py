import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from photo_truth_gate import _candidate_fingerprint
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
            {
                "hcl-343-local-public-finance",
                "hcl-344-local-education-access",
                "hcl-345-regulated-local-authorization",
                "isj-directori-2026-conducere-scoli",
                "3d51c1c0967c1e0d99225eba",
            },
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

        hcl344 = stories["hcl-344-local-education-access"]
        hcl344_note = str((hcl344.get("image") or {}).get("editorial_note") or "")
        hcl344_basis = str(hcl344.get("approval_basis") or "")
        self.assertIn("Foto de arhivă/context", hcl344_note)
        self.assertIn("nu prezintă Școala primară Licurici", hcl344_note)
        self.assertIn("Local Council decision", hcl344_basis)
        self.assertIn("not evidence of the school building", hcl344_basis)

        isj = stories["isj-directori-2026-conducere-scoli"]
        isj_image = isj.get("image") or {}
        isj_binding = isj.get("binding") or {}
        self.assertEqual(isj_image.get("source_type"), "creative_commons")
        self.assertEqual(isj_image.get("rights_basis"), "creative_commons")
        self.assertEqual(isj_image.get("license_url"), "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertIn("Leontin l", str(isj_image.get("credit") or ""))
        self.assertIn("Colegiul Național «Alexandru Lahovari»", str(isj_image.get("editorial_note") or ""))
        self.assertIn("nu dovedește că acest colegiu are una dintre cele 146", str(isj_image.get("editorial_note") or ""))
        self.assertIn("not evidence that Alexandru Lahovari National College is among the 146", str(isj.get("approval_basis") or ""))

        expected_candidate = {
            "candidate_id": "isj-directori-2026-conducere-scoli",
            "source_label": "isj",
            "source_url": "https://www.isjvalcea.ro/management/concurs-directori-2026",
            "headline": "Pentru sesiunea 2026, lista oficială verificată a ISJ Vâlcea cuprinde 146 de funcții vacante de director și director adjunct.",
            "where": "județul Vâlcea",
            "who": "Inspectoratul Școlar Județean Vâlcea; funcțiile vacante de director și director adjunct",
        }
        self.assertEqual(isj_binding.get("candidate_id"), expected_candidate["candidate_id"])
        for field in ("source_label", "source_url", "headline", "where", "who"):
            self.assertEqual(isj_binding.get(field), expected_candidate[field], field)
        self.assertEqual(isj_binding.get("candidate_fingerprint"), _candidate_fingerprint(expected_candidate))

        lapusata = stories["3d51c1c0967c1e0d99225eba"]
        lapusata_image = lapusata.get("image") or {}
        lapusata_binding = lapusata.get("binding") or {}
        self.assertEqual(lapusata_image.get("source_type"), "creative_commons")
        self.assertEqual(lapusata_image.get("rights_basis"), "creative_commons")
        self.assertEqual(lapusata_image.get("license_url"), "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertIn("Leontin l", str(lapusata_image.get("credit") or ""))
        self.assertIn("context geografic", str(lapusata_image.get("editorial_note") or ""))
        self.assertIn("nu surprinde incendiul autoturismului", str(lapusata_image.get("editorial_note") or ""))
        self.assertIn("not evidence of the vehicle fire", str(lapusata.get("approval_basis") or ""))

        expected_lapusata_candidate = {
            "candidate_id": "3d51c1c0967c1e0d99225eba",
            "source_label": "isu",
            "source_url": "https://isuvl.igsu.ro/stiri-locale/incendiu-izbucnit-la-un-autoturism-in-localitatea-lapusata-799",
            "headline": "Incendiu izbucnit la un autoturism, în localitatea Lăpușata",
            "where": "Lăpușata",
            "who": "Inspectoratul pentru Situații de Urgență Vâlcea",
        }
        self.assertEqual(lapusata_binding.get("candidate_id"), expected_lapusata_candidate["candidate_id"])
        for field in ("source_label", "source_url", "headline", "where", "who"):
            self.assertEqual(lapusata_binding.get(field), expected_lapusata_candidate[field], field)
        self.assertEqual(
            lapusata_binding.get("candidate_fingerprint"),
            _candidate_fingerprint(expected_lapusata_candidate),
        )


if __name__ == "__main__":
    unittest.main()
