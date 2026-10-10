import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from contracts import ContractViolation, FactKernel, PublicationReceipt, StoryState, StoryTransaction, Visual
from orchestrator import run_shadow
from audit import build_metrics


def kernel():
    return FactKernel(
        what="APAVIL a publicat un anunț privind posturi vacante.",
        who="APAVIL SA",
        where="județul Vâlcea",
        when="2026-09-18",
        why_it_matters="Anunțul poate afecta persoanele care caută locuri de muncă.",
        source="APAVIL",
        source_url="https://example.org/apavil",
        claims=("Există un anunț oficial.",),
        evidence_ids=("source-1",),
    )


def visual():
    return Visual(
        kind="photograph",
        synthetic=False,
        source_url="https://example.org/photo.jpg",
        rights_basis="creative_commons",
        semantic_relevance="direct_context",
        editor_approved=True,
    )


def full_article():
    return (
        "APAVIL SA a publicat un anunț oficial privind posturi vacante în județul Vâlcea. "
        "Documentul precizează condițiile de înscriere și calendarul procedurii. "
        "Pentru cititori, informația este relevantă deoarece indică o oportunitate concretă de angajare. "
        "Detaliile trebuie verificate în sursa oficială înainte de depunerea documentelor."
    )


class CoreV2ContractsTest(unittest.TestCase):
    def test_no_story_is_truthful_terminal(self):
        tx = StoryTransaction("x")
        tx.no_story("no material change")
        self.assertEqual(tx.state, StoryState.NO_STORY)
        self.assertIs(tx.material_signal, False)

    def test_site_success_requires_external_readback(self):
        tx = StoryTransaction("x")
        tx.verify(kernel())
        tx.write(full_article())
        bad = PublicationReceipt(channel="site", status="DELIVERED", canonical_url="https://example.org/x", readback_ok=False)
        with self.assertRaises(ContractViolation):
            tx.publish_site(bad)

    def test_social_is_fail_closed_without_photo(self):
        tx = StoryTransaction("x")
        tx.verify(kernel())
        tx.write(full_article())
        tx.publish_site(PublicationReceipt(channel="site", status="DELIVERED", canonical_url="https://example.org/x", readback_ok=True))
        receipt = PublicationReceipt(channel="facebook", status="DELIVERED", remote_id="remote-1", receipt_id="receipt-1", readback_ok=True)
        with self.assertRaises(ContractViolation):
            tx.deliver_social(receipt)

    def test_text_card_cannot_be_social_visual(self):
        tx = StoryTransaction("x")
        tx.verify(kernel())
        tx.write(full_article())
        with self.assertRaises(ContractViolation):
            tx.attach_visual(Visual(kind="text_card", synthetic=False, source_url="https://example.org/card.png", rights_basis="internal", semantic_relevance="exact", editor_approved=True))

    def test_social_failure_does_not_rollback_site(self):
        tx = StoryTransaction("x")
        tx.verify(kernel())
        tx.write(full_article())
        tx.attach_visual(visual())
        tx.publish_site(PublicationReceipt(channel="site", status="DELIVERED", canonical_url="https://example.org/x", readback_ok=True))
        tx.fail_distribution("facebook", "graph timeout")
        self.assertEqual(tx.state, StoryState.SITE_PUBLISHED)
        self.assertIn("site", tx.receipts)

    def test_delivered_social_requires_receipt_and_readback(self):
        tx = StoryTransaction("x")
        tx.verify(kernel())
        tx.write(full_article())
        tx.attach_visual(visual())
        tx.publish_site(PublicationReceipt(channel="site", status="DELIVERED", canonical_url="https://example.org/x", readback_ok=True))
        bad = PublicationReceipt(channel="instagram", status="DELIVERED", remote_id="media-1", readback_ok=True)
        with self.assertRaises(ContractViolation):
            tx.deliver_social(bad)

    def test_shadow_orchestrator_full_truth_path(self):
        k = kernel()
        payload = {
            "story_id": "apavil-test",
            "signal_id": "sig-1",
            "material_signal": True,
            "fact_kernel": {"what": k.what, "who": k.who, "where": k.where, "when": k.when, "why_it_matters": k.why_it_matters, "source": k.source, "source_url": k.source_url, "claims": list(k.claims), "evidence_ids": list(k.evidence_ids)},
            "article": full_article(),
            "visual": {"kind": "photograph", "synthetic": False, "source_url": "https://example.org/photo.jpg", "rights_basis": "creative_commons", "semantic_relevance": "exact", "editor_approved": True},
            "site_receipt": {"status": "DELIVERED", "canonical_url": "https://example.org/stiri/apavil-test/", "readback_ok": True},
            "social_receipts": {
                "facebook": {"status": "DELIVERED", "remote_id": "fb-1", "receipt_id": "fb-receipt-1", "readback_ok": True},
                "instagram": {"status": "DELIVERED", "remote_id": "ig-1", "receipt_id": "ig-receipt-1", "readback_ok": True},
            },
            "audit": {"status": "PASS", "external_truth_ok": True, "duplicates": 0, "fabricated_claims": 0, "manual_intervention": 0, "unresolved_material_signals": 0, "evidence": ["site-readback", "fb-readback", "ig-readback"]},
        }
        tx = run_shadow(payload)
        self.assertEqual(tx.state, StoryState.AUDITED)
        self.assertEqual(set(tx.receipts), {"site", "facebook", "instagram"})

    def test_metrics_are_receipt_bound(self):
        rows = [{
            "material_signal": True,
            "visual": {"editor_approved": True, "synthetic": False},
            "receipts": {
                "site": {"readback_ok": True},
                "facebook": {"status": "DELIVERED", "remote_id": "1", "receipt_id": "r1", "readback_ok": True},
                "instagram": {"status": "DELIVERED", "remote_id": "2", "receipt_id": "r2", "readback_ok": False},
            },
            "audit": {"duplicates": 0, "fabricated_claims": 0, "manual_intervention": 0, "unresolved_material_signals": 0},
            "discovery_to_publish_latency_seconds": 120,
        }]
        m = build_metrics(rows)
        self.assertEqual(m.stories_published, 1)
        self.assertEqual(m.photo_coverage, 1.0)
        self.assertEqual(m.facebook_delivery_rate_receipt_bound, 1.0)
        self.assertEqual(m.instagram_delivery_rate_receipt_bound, 0.0)
        self.assertTrue(m.acceptance_ready)

from copy import deepcopy

from promoted_claim_contract import build_promoted_claim_contract
from validate_promoted_claim_contract import validate_promoted_claim_contract


def promoted_lineage(claim_key="registration_deadline", value="2026-10-02"):
    return {
        "story_id": "isj-directori-2026",
        "source_kind": "isj_valcea",
        "claim_key": claim_key,
        "value": value,
        "claim_text": f"Termenul verificat este {value}.",
        "claim_evidence_ids": ["field-1", "calendar-scope-1", "raw-window-1", "document-1"],
        "supporting_evidence_ids": ["field-1", "calendar-scope-1"],
        "materiality_promotion_evidence_id": "materiality-promote-1",
        "fact_kernel_promotion_evidence_id": "fact-promote-1",
        "writer_projection_evidence_id": "writer-project-1",
        "writer_consumption_evidence_id": "writer-consume-1",
        "article_claim_evidence_id": "article-claim-1",
        "document_evidence_id": "document-1",
        "document_page": 2,
        "document_page_sha256": "a" * 64,
        "document_excerpt": "14 septembrie-2 octombrie Depunerea dosarelor de înscriere la concurs",
        "source_identity": {
            "official_source_url": "https://example.org/isj",
            "source_record_id": "isj-source-1",
        },
    }


def build_promoted(lineage):
    return build_promoted_claim_contract(**lineage)


class ReusablePromotedClaimContractTest(unittest.TestCase):
    def test_reusable_contract_accepts_independently_bound_isj_lineage(self):
        lineage = promoted_lineage()
        doc = build_promoted(lineage)
        result = validate_promoted_claim_contract(doc, lineage)
        self.assertEqual(result["status"], "PASS_SHADOW")
        self.assertEqual(result["verified_claim_count"], 1)
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])

    def test_reusable_contract_is_not_deadline_specific(self):
        lineage = promoted_lineage("effective_date", "2026-11-01")
        lineage["source_kind"] = "fixture_official_source"
        lineage["story_id"] = "fixture-effective-date"
        lineage["claim_text"] = "Măsura intră în vigoare la 1 noiembrie 2026."
        lineage["document_excerpt"] = "Data intrării în vigoare: 1 noiembrie 2026"
        lineage["document_page_sha256"] = "b" * 64
        doc = build_promoted(lineage)
        result = validate_promoted_claim_contract(doc, lineage)
        self.assertEqual(result["status"], "PASS_SHADOW")
        self.assertEqual(result["claim_key"], "effective_date")

    def test_reusable_contract_fails_closed_for_detached_lineage(self):
        lineage = promoted_lineage()
        original = build_promoted(lineage)
        cases = [
            ("claim_evidence_ids", ["field-1", "document-1"]),
            ("supporting_evidence_ids", ["calendar-scope-1"]),
            ("materiality_promotion_evidence_id", "materiality-promote-tampered"),
            ("fact_kernel_promotion_evidence_id", "fact-promote-tampered"),
            ("writer_projection_evidence_id", "writer-project-tampered"),
            ("writer_consumption_evidence_id", "writer-consume-tampered"),
            ("article_claim_evidence_id", "article-claim-tampered"),
            ("document_evidence_id", "document-tampered"),
            ("document_page", 3),
            ("document_page_sha256", "c" * 64),
            ("document_excerpt", "detached excerpt"),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                tampered = deepcopy(original)
                tampered[key] = value
                result = validate_promoted_claim_contract(tampered, lineage)
                self.assertEqual(result["status"], "BLOCKED")

        tampered = deepcopy(original)
        tampered["source_identity"]["source_record_id"] = "detached-source"
        self.assertEqual(validate_promoted_claim_contract(tampered, lineage)["status"], "BLOCKED")

        escalated = deepcopy(original)
        escalated["publication_authority"] = "PRODUCTION"
        self.assertEqual(validate_promoted_claim_contract(escalated, lineage)["status"], "BLOCKED")

    def test_recomputed_tampered_envelope_still_fails_against_upstream_truth(self):
        lineage = promoted_lineage()
        detached = deepcopy(lineage)
        detached["document_page_sha256"] = "d" * 64
        self_signed_detached = build_promoted(detached)
        result = validate_promoted_claim_contract(self_signed_detached, lineage)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("upstream_lineage_mismatch", result["detail"])


if __name__ == "__main__":
    unittest.main()
