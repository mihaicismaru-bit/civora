import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from photo_truth_gate import _candidate_fingerprint, _candidate_id, _external_provenance_probe
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
                "d8b16613110809449b51663b",
                "6546c2c57ea3bec64c372747",
                "1fc80eac6f7052a36ebc8a56",
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

        lapusata = stories["d8b16613110809449b51663b"]
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
            "candidate_id": "d8b16613110809449b51663b",
            "source_label": "isu",
            "source_url": "https://isuvl.igsu.ro/stiri-locale/incendiu-izbucnit-la-un-autoturism-in-localitatea-lapusata-799",
            "headline": "Incendiu izbucnit la un autoturism, în localitatea Lăpușata",
            "where": "Lăpușata",
            "who": "Inspectoratul pentru Situații de Urgență Vâlcea",
        }
        self.assertEqual(lapusata_binding.get("candidate_id"), expected_lapusata_candidate["candidate_id"])
        for field in ("source_label", "source_url", "headline", "where", "who"):
            self.assertEqual(lapusata_binding.get(field), expected_lapusata_candidate[field], field)
        self.assertEqual(lapusata_binding.get("candidate_fingerprint"), _candidate_fingerprint(expected_lapusata_candidate))

        madulari = stories["6546c2c57ea3bec64c372747"]
        madulari_image = madulari.get("image") or {}
        madulari_binding = madulari.get("binding") or {}
        self.assertEqual(madulari_image.get("source_type"), "creative_commons")
        self.assertEqual(madulari_image.get("rights_basis"), "creative_commons")
        self.assertEqual(madulari_image.get("license_url"), "https://creativecommons.org/licenses/by/3.0/")
        self.assertIn("Alexandru Baboş", str(madulari_image.get("credit") or ""))
        self.assertIn("satul Mamu", str(madulari_image.get("editorial_note") or ""))
        self.assertIn("nu surprinde incendiul forestier", str(madulari_image.get("editorial_note") or ""))
        self.assertIn("not evidence of the forest fire", str(madulari.get("approval_basis") or ""))
        expected_madulari_candidate = {
            "candidate_id": "6546c2c57ea3bec64c372747",
            "source_label": "isu",
            "source_url": "https://isuvl.igsu.ro/stiri-locale/incendiu-in-fondul-forestier-al-localitatii-madulari-801",
            "headline": "Incendiu în fondul forestier al localității Mădulari",
            "where": "Mădulari",
            "who": "Inspectoratul pentru Situații de Urgență Vâlcea",
        }
        self.assertEqual(madulari_binding.get("candidate_id"), expected_madulari_candidate["candidate_id"])
        for field in ("source_label", "source_url", "headline", "where", "who"):
            self.assertEqual(madulari_binding.get(field), expected_madulari_candidate[field], field)
        self.assertEqual(madulari_binding.get("candidate_fingerprint"), _candidate_fingerprint(expected_madulari_candidate))

        ipj = stories["1fc80eac6f7052a36ebc8a56"]
        ipj_image = ipj.get("image") or {}
        ipj_binding = ipj.get("binding") or {}
        self.assertEqual(ipj_image.get("source_type"), "creative_commons")
        self.assertEqual(ipj_image.get("rights_basis"), "creative_commons")
        self.assertEqual(ipj_image.get("license_url"), "https://creativecommons.org/licenses/by/3.0/")
        self.assertIn("L.Kenzel", str(ipj_image.get("credit") or ""))
        self.assertIn("DN7/E81", str(ipj_image.get("editorial_note") or ""))
        self.assertIn("nu dovedește că acțiunile IPJ", str(ipj_image.get("editorial_note") or ""))
        self.assertIn("not evidence that the 11–13 September 2026 police actions occurred", str(ipj.get("approval_basis") or ""))
        expected_ipj_candidate = {
            "candidate_id": "1fc80eac6f7052a36ebc8a56",
            "source_label": "ipj",
            "source_url": "https://vl.politiaromana.ro/ro/stiri-si-media/comunicate/actiuni-pentru-siguranta-rutiera-in-judetul-valcea",
            "headline": "ACȚIUNI PENTRU SIGURANȚA RUTIERĂ ÎN JUDEȚUL VÂLCEA",
            "where": "județul Vâlcea",
            "who": "Inspectoratul de Poliție Județean Vâlcea",
        }
        self.assertEqual(ipj_binding.get("candidate_id"), expected_ipj_candidate["candidate_id"])
        for field in ("source_label", "source_url", "headline", "where", "who"):
            self.assertEqual(ipj_binding.get(field), expected_ipj_candidate[field], field)
        self.assertEqual(ipj_binding.get("candidate_fingerprint"), _candidate_fingerprint(expected_ipj_candidate))

    def test_public_safety_candidate_identity_ignores_volatile_detail_hash(self):
        source_url = "https://isuvl.igsu.ro/stiri-locale/incendiu-izbucnit-la-un-autoturism-in-localitatea-lapusata-799"
        first = _candidate_id({"detail_id": "a" * 24}, source_label="isu", source_url=source_url)
        second = _candidate_id({"detail_id": "b" * 24}, source_label="isu", source_url=source_url)
        self.assertEqual(first, "d8b16613110809449b51663b")
        self.assertEqual(second, first)

    def test_explicit_story_id_still_wins_over_source_stable_identity(self):
        source_url = "https://vl.politiaromana.ro/example"
        explicit = _candidate_id({"story_id": "canonical-story-id", "detail_id": "a" * 24}, source_label="ipj", source_url=source_url)
        self.assertEqual(explicit, "canonical-story-id")

    @patch("photo_truth_gate._read_binary_head")
    @patch("photo_truth_gate._read_text")
    def test_photo_probe_accepts_only_exact_commons_identity_on_upload_429(self, read_text, read_binary):
        source_url = "https://commons.wikimedia.org/wiki/File:Approved.jpg"
        direct_url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Approved.jpg"
        read_text.return_value = {"status":"PASS","http_status":200,"final_url":source_url,"content_type":"text/html; charset=UTF-8","readback_ok":True,"body":('<script type="application/ld+json">' '{"@type":"ImageObject","contentUrl":"https://upload.wikimedia.org/wikipedia/commons/a/ab/Approved.jpg",' '"license":"https://creativecommons.org/licenses/by-sa/4.0/","name":"Approved"}' '</script>')}
        read_binary.return_value = {"status":"FAILED","http_status":429,"readback_ok":False,"rate_limited":True,"attempts":3}
        result = _external_provenance_probe({"source_url":source_url,"direct_source_url":direct_url}, timeout=1.0)
        self.assertIs(result["readback_ok"], True)
        self.assertIs(result["direct_source_effective_ok"], True)
        self.assertEqual(result["direct_source_fallback"], "wikimedia_commons_source_page_identity_fallback_for_direct_429")
        self.assertIs(result["provenance_asset"]["asset_identity_ok"], True)
        self.assertIs(result["provenance_asset"]["license_present"], True)

    @patch("photo_truth_gate._read_binary_head")
    @patch("photo_truth_gate._read_text")
    def test_photo_probe_rejects_commons_429_when_jsonld_points_to_different_asset(self, read_text, read_binary):
        source_url = "https://commons.wikimedia.org/wiki/File:Approved.jpg"
        direct_url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Approved.jpg"
        read_text.return_value = {"status":"PASS","http_status":200,"final_url":source_url,"content_type":"text/html; charset=UTF-8","readback_ok":True,"body":('<script type="application/ld+json">' '{"@type":"ImageObject","contentUrl":"https://upload.wikimedia.org/wikipedia/commons/a/ab/Different.jpg",' '"license":"https://creativecommons.org/licenses/by-sa/4.0/"}' '</script>')}
        read_binary.return_value = {"status":"FAILED","http_status":429,"readback_ok":False,"rate_limited":True,"attempts":3}
        result = _external_provenance_probe({"source_url":source_url,"direct_source_url":direct_url}, timeout=1.0)
        self.assertIs(result["readback_ok"], False)
        self.assertIs(result["direct_source_effective_ok"], False)
        self.assertIsNone(result["direct_source_fallback"])
        self.assertIs(result["provenance_asset"]["asset_identity_ok"], False)


if __name__ == "__main__":
    unittest.main()
