from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_article_integrity import verify_isj_article_integrity  # noqa: E402
from isj_writer_shadow_lane import compose_isj_article  # noqa: E402


class ISJWriterShadowLaneTests(unittest.TestCase):
    def _fact_inputs(self):
        claim_a = "Pentru sesiunea 2026, lista oficială verificată a ISJ Vâlcea cuprinde 146 de funcții vacante de director și director adjunct."
        claim_b = "Calendarul oficial verificat indică data de 2027-01-01 pentru intrarea în vigoare a deciziilor de numire rezultate din concurs."
        ids = ["isj-field-session", "isj-field-count", "isj-field-list-date", "isj-calendar-field-appointment"]
        kernel = {
            "what": claim_a,
            "who": "Inspectoratul Școlar Județean Vâlcea; funcțiile vacante de director și director adjunct",
            "where": "județul Vâlcea",
            "when": "Lista oficială este datată 2026-08-17; calendarul verificat indică 2027-01-01 ca dată de intrare în vigoare a deciziilor de numire.",
            "why_it_matters": "Concursul privește ocuparea conducerii unităților de învățământ din județ. Termenul de înscriere și intervalele de etapă fără an explicit nu sunt afirmate deoarece nu sunt încă verificate la același nivel.",
            "source": "Inspectoratul Școlar Județean Vâlcea — Concurs directori 2026",
            "source_url": "https://www.isjvalcea.ro/management/concurs-directori-2026",
            "claims": [claim_a, claim_b],
            "evidence_ids": ids,
        }
        fact_report = {
            "state": "FACT_KERNEL_VERIFIED_SHADOW",
            "publication_authority": "NONE",
            "writer_allowed": False,
            "kernels": [{
                "category": "LOCAL_EDUCATION_LEADERSHIP",
                "fact_kernel": kernel,
                "claim_evidence": [
                    {"claim": claim_a, "field_evidence_ids": ids[:3]},
                    {"claim": claim_b, "field_evidence_ids": [ids[0], ids[3]]},
                ],
                "excluded_unverified_or_non_normalized_fields": ["registration_deadline", "interview_window_text", "appointment_decision_deadline_text"],
                "integrity_status": "PENDING_SEPARATE_GATE",
            }],
        }
        fact_integrity = {
            "status": "PASS_SHADOW",
            "publication_authority": "NONE",
            "fact_kernel_integrity_verified": True,
            "fabricated_claim_count": 0,
            "writer_gate_status": "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION",
        }
        return fact_report, fact_integrity

    def test_writer_then_independent_article_integrity_passes(self):
        fact_report, fact_integrity = self._fact_inputs()
        article = compose_isj_article(fact_report, fact_integrity)
        self.assertEqual(article["state"], "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY")
        self.assertEqual(article["article_count"], 1)
        self.assertTrue(article["shadow_writer_executed"])
        self.assertFalse(article["production_writer_ready"])
        integrity = verify_isj_article_integrity(fact_report, fact_integrity, article)
        self.assertEqual(integrity["status"], "PASS_SHADOW")
        self.assertEqual(integrity["article_truth_state"], "VERIFIED_WRITTEN_SHADOW")
        self.assertEqual(integrity["verified_article_count"], 1)
        self.assertEqual(integrity["fabricated_claim_count"], 0)
        self.assertFalse(integrity["production_writer_ready"])

    def test_writer_blocks_if_fact_kernel_integrity_did_not_pass(self):
        fact_report, fact_integrity = self._fact_inputs()
        fact_integrity["status"] = "BLOCKED"
        fact_integrity["fact_kernel_integrity_verified"] = False
        article = compose_isj_article(fact_report, fact_integrity)
        self.assertEqual(article["state"], "BLOCKED")
        self.assertEqual(article["article_count"], 0)
        self.assertFalse(article["shadow_writer_executed"])

    def test_extra_unverified_registration_fact_fails_full_body_gate(self):
        fact_report, fact_integrity = self._fact_inputs()
        article = compose_isj_article(fact_report, fact_integrity)
        tampered = copy.deepcopy(article)
        package = tampered["articles"][0]["article_package"]
        package["body"] += "\n\nÎnscrierile se încheie la 30 septembrie 2026."
        integrity = verify_isj_article_integrity(fact_report, fact_integrity, tampered)
        self.assertEqual(integrity["status"], "BLOCKED")
        self.assertGreaterEqual(integrity["fabricated_claim_count"], 1)

    def test_claim_evidence_tamper_fails_closed(self):
        fact_report, fact_integrity = self._fact_inputs()
        article = compose_isj_article(fact_report, fact_integrity)
        tampered = copy.deepcopy(article)
        tampered["articles"][0]["article_package"]["claims"][0]["field_evidence_ids"] = ["invented-evidence"]
        integrity = verify_isj_article_integrity(fact_report, fact_integrity, tampered)
        self.assertEqual(integrity["status"], "BLOCKED")
        self.assertGreaterEqual(integrity["fabricated_claim_count"], 1)


if __name__ == "__main__":
    unittest.main()
