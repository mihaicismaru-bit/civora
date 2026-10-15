from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_field_evidence_shadow_lane import extract_field_evidence  # noqa: E402


def page(number: int, text: str):
    return {
        "page_number": number,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": len(text),
    }


class ISJFieldEvidenceShadowLaneTests(unittest.TestCase):
    def _content(self):
        vacancy = """INSPECTORATUL ȘCOLAR JUDEȚEAN VÂLCEA
Nr.4596/17.08.2026
Lista funcțiilor vacante de director și director adjunct din unitățile de învățământ
preuniversitar din Județul Vâlcea pentru care se organizează concurs, sesiunea 2026
 1 VÂLCEA Școala A Director
 2 VÂLCEA Școala B Director
 3 VÂLCEA Școala C Director
 4 VÂLCEA Școala D Director
 5 VÂLCEA Școala E Director
 6 VÂLCEA Școala F Director
 7 VÂLCEA Școala G Director
 8 VÂLCEA Școala H Director
 9 VÂLCEA Școala I Director
10 VÂLCEA Școala J Director
11 VÂLCEA Școala K Director
12 VÂLCEA Școala L Director
13 VÂLCEA Școala M Director
14 VÂLCEA Școala N Director
15 VÂLCEA Școala O Director
16 VÂLCEA Școala P Director
17 VÂLCEA Școala Q Director
18 VÂLCEA Școala R Director
19 VÂLCEA Școala S Director
20 VÂLCEA Școala T Director
"""
        methodology = """MONITORUL OFICIAL AL ROMÂNIEI, PARTEA I, Nr. 552 bis/6.VII.2026
Anexa la Ordinul ministrului educației și cercetării nr. 4.155/2026
Art. 3 (1) Poate participa la concurs cadrul didactic care îndeplinește cumulativ următoarele condiții:
a) este absolvent al învățământului superior cu diplomă de licență sau atestat de echivalare;
b) este titular în învățământul preuniversitar, având încheiat contract de muncă pe perioadă nedeterminată;
c) are o vechime în învățământul preuniversitar de minimum 5 ani;
"""
        vacancy_sha = hashlib.sha256(vacancy.encode("utf-8")).hexdigest()
        methodology_sha = hashlib.sha256(methodology.encode("utf-8")).hexdigest()
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [
                {
                    "state": "DOCUMENT_TEXT_EXTRACTED_SHADOW",
                    "document_label": "LISTA POSTURI CONCURS DIRECTORI 2026.pdf",
                    "document_content_evidence_id": "doc-content-vacancy",
                    "document_text_evidence_id": "doc-text-vacancy",
                    "normalized_text_sha256": vacancy_sha,
                    "pages": [page(1, vacancy)],
                },
                {
                    "state": "DOCUMENT_TEXT_EXTRACTED_SHADOW",
                    "document_label": "OMEC-4155-Metodologiei privind organizarea CONCURS DIRECTORI 2026.pdf",
                    "document_content_evidence_id": "doc-content-methodology",
                    "document_text_evidence_id": "doc-text-methodology",
                    "normalized_text_sha256": methodology_sha,
                    "pages": [page(1, methodology)],
                },
            ],
        }

    def test_exact_fields_are_evidence_bound_without_promotion(self):
        result = extract_field_evidence(self._content())
        self.assertEqual(result["verified_document_count"], 2)
        self.assertEqual(result["field_evidence_count"], 9)
        self.assertEqual(result["material_candidate_shadow_count"], 1)
        self.assertEqual(result["blocked_count"], 0)
        fields = {
            field["field"]: field
            for row in result["rows"]
            for field in row.get("fields") or []
        }
        self.assertEqual(fields["list_document_number"]["value"], "4596")
        self.assertEqual(fields["list_document_date"]["value"], "2026-08-17")
        self.assertEqual(fields["contest_session_year"]["value"], 2026)
        self.assertEqual(fields["vacant_function_count"]["value"], 20)
        self.assertEqual(fields["minimum_preuniversity_seniority_years"]["value"], 5)
        self.assertTrue(fields["requires_higher_education_degree_or_equivalence"]["value"])
        self.assertTrue(fields["requires_tenured_preuniversity_indefinite_contract"]["value"])
        for field in fields.values():
            self.assertEqual(field["state"], "FIELD_EVIDENCE_VERIFIED_SHADOW")
            self.assertTrue(field["field_evidence_id"].startswith("isj-field-"))
            self.assertFalse(field["fact_kernel_promotion_allowed"])
            self.assertFalse(field["writer_allowed"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["site_publish_allowed"])
        self.assertFalse(result["social_publish_allowed"])

    def test_missing_table_index_blocks_vacancy_document(self):
        content = self._content()
        text = content["rows"][0]["pages"][0]["text"].replace("10 VÂLCEA Școala J Director\n", "")
        content["rows"][0]["pages"] = [page(1, text)]
        content["rows"][0]["normalized_text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result = extract_field_evidence(content)
        vacancy = result["rows"][0]
        self.assertEqual(vacancy["state"], "BLOCKED")
        self.assertIn("vacancy_row_indices_not_contiguous", vacancy["error"])
        self.assertEqual(vacancy["field_evidence_count"], 0)

    def test_wrong_session_year_prevents_material_candidate(self):
        content = self._content()
        text = content["rows"][0]["pages"][0]["text"].replace("sesiunea 2026", "sesiunea 2025")
        content["rows"][0]["pages"] = [page(1, text)]
        content["rows"][0]["normalized_text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result = extract_field_evidence(content)
        self.assertEqual(result["rows"][0]["state"], "BLOCKED")
        self.assertEqual(result["material_candidate_shadow_count"], 0)

    def test_unextracted_document_is_ignored(self):
        content = self._content()
        content["rows"][0]["state"] = "DOCUMENT_CONTENT_CAPTURED_SHADOW"
        result = extract_field_evidence(content)
        self.assertEqual(result["verified_document_count"], 1)
        self.assertEqual(result["field_evidence_count"], 5)
        self.assertEqual(result["material_candidate_shadow_count"], 0)


if __name__ == "__main__":
    unittest.main()
