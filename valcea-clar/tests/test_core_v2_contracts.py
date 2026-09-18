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


if __name__ == "__main__":
    unittest.main()
