from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_article_deadline_claim_gate import build_article_deadline_claim_gate  # noqa: E402
from isj_article_integrity import verify_isj_article_integrity  # noqa: E402
from isj_writer_deadline_consumption_shadow_lane import build_writer_deadline_consumption  # noqa: E402
from isj_writer_shadow_lane import compose_isj_article  # noqa: E402
from validate_isj_article_deadline_claim_gate import prove_tamper_regressions as prove_article_claim_tamper, validate as validate_article_claim_gate  # noqa: E402
from validate_isj_writer_deadline_consumption import prove_tamper_regressions, validate as validate_consumption  # noqa: E402


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


class ISJWriterDeadlineConsumptionGateTests(unittest.TestCase):
    def _inputs(self):
        claim = "Calendarul oficial verificat pentru sesiunea 2026 indică data de 2 octombrie 2026 ca termen-limită al perioadei de înscriere."
        identities = {
            "field_evidence_id": "isj-field-registration-deadline",
            "scope_field_evidence_id": "isj-calendar-scope-session-2026",
            "source_registration_window_field_evidence_id": "isj-calendar-registration-window",
            "document_text_evidence_id": "isj-calendar-document-text",
            "upstream_materiality_promotion_evidence_id": "isj-deadline-promotion-unit",
            "fact_kernel_promotion_evidence_id": "isj-fact-kernel-deadline-promotion-unit",
            "page_text_sha256": "a" * 64,
        }
        claim_evidence = [
            identities["field_evidence_id"],
            identities["scope_field_evidence_id"],
            identities["source_registration_window_field_evidence_id"],
            identities["document_text_evidence_id"],
            identities["fact_kernel_promotion_evidence_id"],
        ]
        promoted = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "claim": claim,
            **identities,
            "supporting_field_evidence_ids": [identities["scope_field_evidence_id"], identities["source_registration_window_field_evidence_id"]],
            "claim_evidence_ids": claim_evidence,
            "page_number": 1,
            "excerpt": "14 septembrie – 2 octombrie: depunerea dosarelor de înscriere",
        }
        boundary = {
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        fact_kernel = {
            **boundary,
            "state": "FACT_KERNEL_VERIFIED_SHADOW",
            "writer_allowed": False,
            "promoted_fact_claim_count": 1,
            "kernels": [{"promoted_fact_claims": [promoted]}],
        }
        fact_integrity = {
            **boundary,
            "status": "PASS_SHADOW",
            "fact_kernel_integrity_verified": True,
            "promoted_fact_verified_count": 1,
            "fabricated_claim_count": 0,
        }
        projection_id = "isj-writer-deadline-projection-unit"
        projection_candidate = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "claim": claim,
            "state": "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW",
            **identities,
            "supporting_field_evidence_ids": promoted["supporting_field_evidence_ids"],
            "claim_evidence_ids": claim_evidence,
            "page_number": 1,
            "excerpt": promoted["excerpt"],
            "writer_projection_evidence_id": projection_id,
            "writer_deadline_projection_allowed": True,
            "writer_allowed": False,
            "article_projection_allowed": False,
        }
        projection = {
            **boundary,
            "state": "WRITER_PROJECTION_VERIFIED_SHADOW",
            "registration_deadline": "2026-10-02",
            "writer_projection_evidence_id": projection_id,
            "writer_deadline_projection_allowed": True,
            "writer_allowed": False,
            "article_projection_allowed": False,
            "projection_candidate_count": 1,
            "projection_candidates": [projection_candidate],
        }
        projection_validation = {
            **boundary,
            "status": "PASS_SHADOW",
            "registration_deadline": "2026-10-02",
            "writer_projection_evidence_id": projection_id,
            "writer_deadline_projection_allowed": True,
            "article_projection_allowed": False,
            "verified_projection_candidate_count": 1,
            "fabricated_claim_count": 0,
            "tamper_regressions_passed": 3,
        }
        return fact_kernel, fact_integrity, projection, projection_validation

    def test_consumption_gate_and_independent_validator_pass_without_article_authority(self):
        fact_kernel, fact_integrity, projection, projection_validation = self._inputs()
        consumption = build_writer_deadline_consumption(fact_kernel, fact_integrity, projection, projection_validation)
        self.assertEqual(consumption["state"], "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW")
        self.assertTrue(consumption["shadow_writer_consumption_allowed"])
        self.assertFalse(consumption["writer_allowed"])
        self.assertFalse(consumption["article_projection_allowed"])
        summary = validate_consumption(fact_kernel, fact_integrity, projection, projection_validation, consumption)
        self.assertEqual(summary["status"], "PASS_SHADOW")
        self.assertTrue(summary["shadow_writer_consumption_allowed"])
        self.assertFalse(summary["article_projection_allowed"])
        self.assertEqual(
            prove_tamper_regressions(fact_kernel, fact_integrity, projection, projection_validation, consumption),
            4,
        )

    def test_consumption_gate_blocks_detached_projection_validation(self):
        fact_kernel, fact_integrity, projection, projection_validation = self._inputs()
        projection_validation["writer_projection_evidence_id"] = "isj-writer-deadline-projection-detached"
        consumption = build_writer_deadline_consumption(fact_kernel, fact_integrity, projection, projection_validation)
        self.assertEqual(consumption["state"], "BLOCKED")
        self.assertFalse(consumption["shadow_writer_consumption_allowed"])
        self.assertEqual(consumption["publication_authority"], "NONE")


class ISJArticleDeadlineClaimGateTests(unittest.TestCase):
    def _inputs(self):
        claim = "Calendarul oficial verificat pentru sesiunea 2026 indică data de 2 octombrie 2026 ca termen-limită al perioadei de înscriere."
        identities = {
            "field_evidence_id": "isj-field-registration-deadline",
            "scope_field_evidence_id": "isj-calendar-scope-session-2026",
            "source_registration_window_field_evidence_id": "isj-calendar-registration-window",
            "document_text_evidence_id": "isj-calendar-document-text",
            "upstream_materiality_promotion_evidence_id": "isj-deadline-promotion-unit",
            "fact_kernel_promotion_evidence_id": "isj-fact-kernel-deadline-promotion-unit",
            "page_text_sha256": "a" * 64,
        }
        claim_evidence = [
            identities["field_evidence_id"],
            identities["scope_field_evidence_id"],
            identities["source_registration_window_field_evidence_id"],
            identities["document_text_evidence_id"],
            identities["fact_kernel_promotion_evidence_id"],
        ]
        supporting = [
            identities["scope_field_evidence_id"],
            identities["source_registration_window_field_evidence_id"],
        ]
        promoted = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "claim": claim,
            **identities,
            "supporting_field_evidence_ids": supporting,
            "claim_evidence_ids": claim_evidence,
            "page_number": 2,
            "excerpt": "14 septembrie-2 octombrie Depunerea dosarelor de înscriere la concurs",
        }
        boundary = {
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        fact_kernel = {
            **boundary,
            "state": "FACT_KERNEL_VERIFIED_SHADOW",
            "writer_allowed": False,
            "promoted_fact_claim_count": 1,
            "kernels": [{"promoted_fact_claims": [promoted]}],
        }
        fact_integrity = {
            **boundary,
            "production_writer_ready": False,
            "status": "PASS_SHADOW",
            "fact_kernel_integrity_verified": True,
            "promoted_fact_verified_count": 1,
            "fabricated_claim_count": 0,
        }
        projection_id = "isj-writer-deadline-projection-unit"
        consumption_id = "isj-writer-deadline-consumption-unit"
        consumption_candidate = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "claim": claim,
            "state": "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW",
            **identities,
            "supporting_field_evidence_ids": supporting,
            "claim_evidence_ids": claim_evidence,
            "page_number": 2,
            "excerpt": promoted["excerpt"],
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "shadow_writer_consumption_allowed": True,
            "writer_allowed": False,
            "production_writer_ready": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "publication_authority": "NONE",
        }
        consumption = {
            **boundary,
            "production_writer_ready": False,
            "state": "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW",
            "registration_deadline": "2026-10-02",
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "shadow_writer_consumption_allowed": True,
            "writer_allowed": False,
            "article_projection_allowed": False,
            "consumption_candidate_count": 1,
            "consumption_candidates": [consumption_candidate],
        }
        consumption_validation = {
            **boundary,
            "production_writer_ready": False,
            "status": "PASS_SHADOW",
            "registration_deadline": "2026-10-02",
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "shadow_writer_consumption_allowed": True,
            "writer_allowed": False,
            "article_projection_allowed": False,
            "verified_consumption_candidate_count": 1,
            "fabricated_claim_count": 0,
            "tamper_regressions_passed": 4,
        }
        pending = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "text": claim,
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "claim_evidence_ids": claim_evidence,
            "supporting_field_evidence_ids": supporting,
            **identities,
            "page_number": 2,
            "excerpt": promoted["excerpt"],
            "state": "WRITER_RENDERED_SHADOW_PENDING_ARTICLE_CLAIM_INTEGRITY",
            "article_projection_allowed": False,
            "publication_authority": "NONE",
        }
        article_package = {
            "article_id": "isj-directori-2026-conducere-scoli",
            "headline": "Lista funcțiilor vacante pentru concursul de directori",
            "body": "Articol canonic cu două afirmații de bază, fără termenul de înscriere.",
            "claims": [
                {"text": "Afirmația de bază A", "field_evidence_ids": ["base-a"]},
                {"text": "Afirmația de bază B", "field_evidence_ids": ["base-b"]},
            ],
            "rendered_promoted_claims_pending_integrity": [pending],
            "writer_consumes_deadline_projection": True,
            "article_contains_registration_deadline": False,
            "publication_authority": "NONE",
            "production_writer_ready": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        article = {
            **boundary,
            "production_writer_ready": False,
            "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY",
            "shadow_writer_executed": True,
            "writer_consumes_deadline_projection": True,
            "rendered_promoted_claim_count": 1,
            "article_contains_registration_deadline": False,
            "article_count": 1,
            "articles": [{
                "article_id": article_package["article_id"],
                "article_package": article_package,
                "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY",
                "publication_authority": "NONE",
                "production_writer_ready": False,
                "article_projection_allowed": False,
                "site_publish_allowed": False,
                "social_publish_allowed": False,
            }],
        }
        return fact_kernel, fact_integrity, consumption, consumption_validation, article

    def test_article_deadline_claim_gate_and_independent_validator_pass_without_mutation_authority(self):
        fact_kernel, fact_integrity, consumption, consumption_validation, article = self._inputs()
        gate = build_article_deadline_claim_gate(
            fact_kernel, fact_integrity, consumption, consumption_validation, article
        )
        self.assertEqual(gate["state"], "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW")
        self.assertTrue(gate["shadow_article_claim_integrity_passed"])
        self.assertFalse(gate["canonical_article_mutation_allowed"])
        self.assertFalse(gate["article_projection_allowed"])
        summary = validate_article_claim_gate(
            fact_kernel, fact_integrity, consumption, consumption_validation, article, gate
        )
        self.assertEqual(summary["status"], "PASS_SHADOW")
        self.assertEqual(summary["verified_claim_candidate_count"], 1)
        self.assertEqual(summary["fabricated_claim_count"], 0)
        self.assertEqual(
            prove_article_claim_tamper(
                fact_kernel, fact_integrity, consumption, consumption_validation, article, gate
            ),
            5,
        )

    def test_article_deadline_claim_gate_blocks_detached_consumption_identity(self):
        fact_kernel, fact_integrity, consumption, consumption_validation, article = self._inputs()
        article = copy.deepcopy(article)
        article["articles"][0]["article_package"]["rendered_promoted_claims_pending_integrity"][0][
            "writer_consumption_evidence_id"
        ] = "isj-writer-deadline-consumption-detached"
        gate = build_article_deadline_claim_gate(
            fact_kernel, fact_integrity, consumption, consumption_validation, article
        )
        self.assertEqual(gate["state"], "BLOCKED")
        self.assertFalse(gate["shadow_article_claim_integrity_passed"])

    def test_article_deadline_claim_gate_blocks_premature_article_body_projection(self):
        fact_kernel, fact_integrity, consumption, consumption_validation, article = self._inputs()
        article = copy.deepcopy(article)
        pending = article["articles"][0]["article_package"]["rendered_promoted_claims_pending_integrity"][0]
        article["articles"][0]["article_package"]["body"] += "\n\n" + pending["text"]
        gate = build_article_deadline_claim_gate(
            fact_kernel, fact_integrity, consumption, consumption_validation, article
        )
        self.assertEqual(gate["state"], "BLOCKED")
        self.assertFalse(gate["canonical_article_mutation_allowed"])


if __name__ == "__main__":
    unittest.main()
