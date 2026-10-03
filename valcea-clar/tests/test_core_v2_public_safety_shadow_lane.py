from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from public_safety_shadow_lane import promote_detail, verify_receipt  # noqa: E402


class PublicSafetyShadowLaneTests(unittest.TestCase):
    def _ipj_detail(self):
        return {
            "authority_class": "FIRST_PARTY_COUNTY_POLICE_ARTICLE_DETAIL_EVIDENCE",
            "observation_state": "POLICE_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
            "source_assertion_scope": "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            "verification_state": "POLICE_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
            "detail_url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/actiune-rutiera-test",
            "detail_sha256": "a" * 64,
            "index_evidence_sha256": "b" * 64,
            "index_title": "Acțiune rutieră în municipiul Râmnicu Vâlcea",
            "visible_title": "Acțiune rutieră în municipiul Râmnicu Vâlcea",
            "explicit_date_text": "18 septembrie 2026",
            "field_evidence": [
                {
                    "excerpt": "Polițiștii au efectuat verificări în trafic în municipiul Râmnicu Vâlcea.",
                    "epistemic_tags": ["POLICE_REPORTED_OBSERVATION", "ROAD_OR_PUBLIC_SAFETY_MEASURE"],
                    "evidence_sha256": "c" * 64,
                    "source_assertion_scope": "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                },
                {
                    "excerpt": "În cauză a fost dispusă o măsură procedurală, iar cercetările continuă.",
                    "epistemic_tags": ["PROCEDURAL_MEASURE", "ALLEGATION_OR_SUSPICION"],
                    "evidence_sha256": "d" * 64,
                    "source_assertion_scope": "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                },
            ],
        }

    def _isu_detail(self):
        return {
            "authority_class": "FIRST_PARTY_COUNTY_EMERGENCY_ARTICLE_DETAIL_EVIDENCE",
            "observation_state": "ISU_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
            "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            "verification_state": "ISU_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
            "detail_url": "https://isuvl.igsu.ro/stiri-locale/incendiu-test-123",
            "detail_sha256": "e" * 64,
            "index_evidence_sha256": "f" * 64,
            "index_title": "Intervenție ISU în localitatea Băile Olănești",
            "visible_title": "Intervenție ISU în localitatea Băile Olănești",
            "explicit_date_text": "18.09.2026",
            "field_evidence": [
                {
                    "excerpt": "Echipajele ISU au intervenit în localitatea Băile Olănești pentru gestionarea situației.",
                    "epistemic_tags": ["ISU_REPORTED_OBSERVATION", "RESPONSE_ACTION"],
                    "evidence_sha256": "1" * 64,
                    "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                },
                {
                    "excerpt": "Într-un context separat din corpul paginii este menționată localitatea Măciuca; aceasta nu poate înlocui localizarea explicită din titlu. Sursa menționează o cauză probabilă și un număr raportat de persoane afectate.",
                    "epistemic_tags": ["REPORTED_CAUSE_OR_ORIGIN", "REPORTED_AFFECTED_OR_CASUALTY", "REPORTED_NUMERIC_COUNT"],
                    "evidence_sha256": "2" * 64,
                    "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                },
            ],
        }

    def _receipt(self, source: str, detail):
        if source == "ipj":
            return {
                "status": "PASS",
                "authority_class": "FIRST_PARTY_COUNTY_POLICE_ARTICLE_DETAIL_EVIDENCE",
                "observation_state": "POLICE_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
                "source_assertion_scope": "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                "material_fact_use": False,
                "fact_kernel_write_authorized": False,
                "details": [detail],
            }
        return {
            "status": "PASS",
            "authority_class": "FIRST_PARTY_COUNTY_EMERGENCY_ARTICLE_DETAIL_EVIDENCE",
            "observation_state": "ISU_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
            "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            "material_fact_use": False,
            "fact_kernel_write_authorized": False,
            "details": [detail],
        }

    def test_ipj_detail_promotes_only_with_attributed_epistemic_language(self):
        result = verify_receipt("ipj", self._receipt("ipj", self._ipj_detail()), as_of=date(2026, 9, 18))
        self.assertEqual(result["verified_written_shadow_count"], 1)
        self.assertEqual(result["fabricated_claim_count"], 0)
        row = result["rows"][0]
        self.assertEqual(row["state"], "VERIFIED_WRITTEN_SHADOW")
        self.assertEqual(row["integrity"]["status"], "PASS")
        self.assertFalse(row["production_writer_ready"])
        body = row["article_package"]["body"]
        self.assertIn("rămâne atribuită IPJ Vâlcea", body)
        self.assertIn("nu prezintă o reținere", body)
        self.assertIn("nu ca moment confirmat al evenimentului", body)
        self.assertEqual(row["fact_kernel"]["where"], "Râmnicu Vâlcea")
        self.assertGreaterEqual(len(row["fact_kernel"]["evidence_ids"]), 4)

    def test_isu_detail_preserves_reported_cause_and_count_limits(self):
        result = verify_receipt("isu", self._receipt("isu", self._isu_detail()), as_of=date(2026, 9, 18))
        self.assertEqual(result["verified_written_shadow_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["integrity"]["fabricated_claims"], 0)
        body = row["article_package"]["body"]
        self.assertIn("Cauzele, numărul persoanelor afectate", body)
        self.assertIn("fără verificare separată", body)
        self.assertEqual(row["fact_kernel"]["where"], "Băile Olănești")

    def test_title_locality_wins_over_unrelated_body_place(self):
        detail = self._isu_detail()
        detail["index_title"] = "Incendiu izbucnit într-o gospodărie din localitatea Mădulari"
        detail["visible_title"] = "ISU Vâlcea - Incendiu izbucnit într-o gospodărie din localitatea Mădulari"
        detail["field_evidence"][0]["excerpt"] = "Pompierii au intervenit în localitatea Mădulari pentru stingerea incendiului."
        detail["field_evidence"][1]["excerpt"] = "Pagina conține și o referință separată la localitatea Măciuca, care nu descrie locul incidentului."
        row = promote_detail("isu", detail, as_of=date(2026, 9, 18))
        self.assertEqual(row["state"], "VERIFIED_WRITTEN_SHADOW")
        self.assertEqual(row["fact_kernel"]["where"], "Mădulari")

    def test_genitive_locality_is_extracted_from_title(self):
        detail = self._isu_detail()
        detail["index_title"] = "Incendiu la o anexă gospodărească pe raza localității Lăpușata"
        detail["visible_title"] = detail["index_title"]
        detail["field_evidence"][0]["excerpt"] = "Echipajele ISU au intervenit pentru gestionarea incendiului."
        row = promote_detail("isu", detail, as_of=date(2026, 9, 18))
        self.assertEqual(row["state"], "VERIFIED_WRITTEN_SHADOW")
        self.assertEqual(row["fact_kernel"]["where"], "Lăpușata")

    def test_multiple_body_geographies_block_when_title_has_none(self):
        detail = self._isu_detail()
        detail["index_title"] = "Bilanț al intervențiilor pompierilor din ultimele ore"
        detail["visible_title"] = detail["index_title"]
        detail["field_evidence"] = [
            {
                "excerpt": "Echipajele ISU au intervenit în localitatea Drăgășani și în localitatea Măciuca.",
                "epistemic_tags": ["ISU_REPORTED_OBSERVATION", "RESPONSE_ACTION"],
                "evidence_sha256": "4" * 64,
                "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            }
        ]
        row = promote_detail("isu", detail, as_of=date(2026, 9, 18))
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "ambiguous_multiple_geographies")

    def test_missing_explicit_source_date_is_no_story(self):
        detail = self._ipj_detail()
        detail["explicit_date_text"] = None
        row = promote_detail("ipj", detail, as_of=date(2026, 9, 18))
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "explicit_source_date_missing")

    def test_stale_detail_is_no_story(self):
        detail = self._isu_detail()
        detail["explicit_date_text"] = "1 septembrie 2026"
        row = promote_detail("isu", detail, as_of=date(2026, 9, 18))
        self.assertEqual(row["state"], "NO_STORY")
        self.assertEqual(row["reason"], "stale_first_party_detail")

    def test_missing_explicit_geography_blocks_without_inference(self):
        detail = self._ipj_detail()
        detail["index_title"] = "Acțiune rutieră desfășurată de polițiști"
        detail["visible_title"] = detail["index_title"]
        detail["field_evidence"] = [
            {
                "excerpt": "Polițiștii au desfășurat verificări în trafic, potrivit comunicării oficiale.",
                "epistemic_tags": ["POLICE_REPORTED_OBSERVATION"],
                "evidence_sha256": "3" * 64,
                "source_assertion_scope": "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            }
        ]
        row = promote_detail("ipj", detail, as_of=date(2026, 9, 18))
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "explicit_geography_missing")

    def test_non_authorizing_upstream_contract_is_required(self):
        receipt = self._receipt("isu", self._isu_detail())
        receipt["fact_kernel_write_authorized"] = True
        result = verify_receipt("isu", receipt, as_of=date(2026, 9, 18))
        self.assertEqual(result["status"], "BLOCKED_UPSTREAM_AUTHORITY_CHANGED")
        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
