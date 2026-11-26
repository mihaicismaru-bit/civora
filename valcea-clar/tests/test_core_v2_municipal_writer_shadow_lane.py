from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from municipal_writer_shadow_lane import compose_article, compose_bundle  # noqa: E402


def kernel_record():
    claim = (
        "Hotărârea nr. 345/2026-09-16 aprobă acordarea unei autorizații anuale de funcționare "
        "pentru jocuri de noroc (slot-machine) operatorului GEAR SLOT S.R.L., pentru punctul de lucru "
        "din Râmnicu-Vâlcea, str. Calea lui Traian nr. 245A."
    )
    fee_claim = "Documentul stabilește pentru această autorizație o taxă locală anuală de 125.000 lei."
    return {
        "category": "REGULATED_LOCAL_AUTHORIZATION",
        "fact_kernel": {
            "what": claim,
            "who": "Consiliul Local al Municipiului Râmnicu Vâlcea; operator economic: GEAR SLOT S.R.L.",
            "where": "Râmnicu-Vâlcea, str. Calea lui Traian nr. 245A",
            "when": "2026-09-16 — data adoptării hotărârii; nu este inferată data începerii efective a activității",
            "why_it_matters": "Decizia acordă o autorizare locală explicită pentru o activitate reglementată; nu dovedește singură funcționarea efectivă după adoptare.",
            "source": "Consiliul Local al Municipiului Râmnicu Vâlcea — Hotărârea nr. 345 din 2026-09-16",
            "source_url": "https://dm.primariavl.ro/dm/2026/hotarari.nsf/ABC345/$FILE/h345.htm",
            "claims": [claim, fee_claim],
            "evidence_ids": ["op", "money"],
        },
        "claim_evidence": [
            {"claim": claim, "evidence_ids": ["op"]},
            {"claim": fee_claim, "evidence_ids": ["money"]},
        ],
        "integrity": {"status": "PASS_SHADOW", "all_claims_evidence_bound": True, "fabricated_claims": 0},
    }


class MunicipalWriterShadowLaneTests(unittest.TestCase):
    def test_writer_preserves_exact_kernel_claims_and_uncertainty(self):
        result = compose_article(kernel_record(), decision_number=345, decision_date="2026-09-16")
        self.assertEqual(result["state"], "VERIFIED_WRITTEN_SHADOW")
        self.assertEqual(result["integrity"]["status"], "PASS")
        self.assertEqual(result["integrity"]["fabricated_claims"], 0)
        package = result["article_package"]
        self.assertEqual(package["writer_id"], "municipal_shadow_editorial_v1")
        self.assertIn("nu este inferată data începerii efective", package["body"])
        self.assertIn("nu ca dovadă că măsura a fost deja implementată", package["body"])
        self.assertFalse(package["site_publish_allowed"])
        self.assertFalse(package["social_publish_allowed"])

    def test_bundle_is_non_authorizing(self):
        source = {
            "rows": [{
                "decision_number": 345,
                "decision_date": "2026-09-16",
                "state": "FACT_KERNEL_VERIFIED_SHADOW",
                "kernels": [kernel_record()],
            }]
        }
        result = compose_bundle(source)
        self.assertEqual(result["verified_written_shadow_row_count"], 1)
        self.assertEqual(result["article_count"], 1)
        self.assertEqual(result["fabricated_claim_count"], 0)
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])
        self.assertFalse(result["production_writer_ready"])

    def test_nonverified_kernel_row_cannot_reach_writer(self):
        result = compose_bundle({"rows": [{"decision_number": 346, "decision_date": "2026-09-16", "state": "NO_STORY", "reason": "no material fact"}]})
        self.assertEqual(result["article_count"], 0)
        self.assertEqual(result["no_story_count"], 1)
        self.assertEqual(result["fabricated_claim_count"], 0)

    def test_missing_claim_evidence_fails_closed(self):
        bad = kernel_record()
        bad["fact_kernel"]["evidence_ids"] = []
        with self.assertRaises(Exception):
            compose_article(bad, decision_number=345, decision_date="2026-09-16")


if __name__ == "__main__":
    unittest.main()
