from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from municipal_materiality_shadow_lane import adjudicate_bundle, adjudicate_document  # noqa: E402


def evidence(eid: str, kind: str, excerpt: str):
    return {
        "evidence_id": eid,
        "kind": kind,
        "excerpt": excerpt,
        "epistemic_status": "FIRST_PARTY_DOCUMENT_TEXT",
        "material_fact_status": "UNADJUDICATED",
    }


def document(number: int, *items):
    return {
        "decision_number": number,
        "decision_date": "2026-09-16",
        "registered_title": "metadata title must not authorize a story",
        "state": "DOCUMENT_EVIDENCE_READY",
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "evidence": list(items),
    }


class MunicipalMaterialityShadowLaneTests(unittest.TestCase):
    def test_budget_change_is_materiality_candidate_but_not_fact_kernel(self):
        row = document(343, evidence("e343", "OPERATIVE_ARTICLE", "Art.1. Se rectifică bugetul creditelor interne pe anul 2026 prin majorarea cu suma de 19.010.000 lei, ajungând la 30.000.000 lei."))
        result = adjudicate_document(row)
        self.assertEqual(result["state"], "MATERIALITY_CANDIDATE")
        self.assertEqual(result["materiality_candidates"][0]["category"], "LOCAL_PUBLIC_FINANCE")
        self.assertIn(19010000.0, result["materiality_candidates"][0]["details"]["amounts_lei"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertNotIn("fact_kernel", result)
        self.assertNotIn("article_package", result)

    def test_school_network_change_is_materiality_candidate(self):
        row = document(344, evidence("e344", "OPERATIVE_ARTICLE", "Art.1. Se completează rețeaua școlară pentru anul școlar 2026-2027 în sensul introducerii Școlii primare Licurici."))
        result = adjudicate_document(row)
        self.assertEqual(result["state"], "MATERIALITY_CANDIDATE")
        self.assertEqual(result["materiality_candidates"][0]["category"], "LOCAL_EDUCATION_ACCESS")
        self.assertEqual(result["materiality_candidates"][0]["evidence_ids"], ["e344"])

    def test_regulated_gambling_authorization_binds_fee_context(self):
        row = document(
            345,
            evidence("e345-op", "OPERATIVE_ARTICLE", "Art.1. Se aprobă acordarea autorizației anuale de funcționare pentru jocuri de noroc (slot-machine) operatorului economic GEAR SLOT S.R.L."),
            evidence("e345-money", "MONEY_CONTEXT", "Taxa locală anuală pentru eliberarea autorizației este de 125.000 lei."),
        )
        result = adjudicate_document(row)
        self.assertEqual(result["state"], "MATERIALITY_CANDIDATE")
        candidate = result["materiality_candidates"][0]
        self.assertEqual(candidate["category"], "REGULATED_LOCAL_AUTHORIZATION")
        self.assertEqual(candidate["details"]["annual_local_fee_lei"], 125000.0)
        self.assertEqual(candidate["evidence_ids"], ["e345-money", "e345-op"])

    def test_administrative_execution_clause_is_no_story(self):
        row = document(346, evidence("e346", "OPERATIVE_ARTICLE", "Art.2. Cu ducerea la îndeplinire a prezentei hotărâri se încredințează serviciul de specialitate."))
        result = adjudicate_document(row)
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["materiality_candidates"], [])

    def test_title_alone_never_proves_materiality(self):
        row = document(347, evidence("e347", "OPERATIVE_ARTICLE", "Art.1. Prezenta hotărâre se comunică instituțiilor interesate."))
        row["registered_title"] = "Rectificare buget de 999.000.000 lei și deschidere școală"
        result = adjudicate_document(row)
        self.assertEqual(result["state"], "NO_STORY")

    def test_non_ready_or_untrusted_evidence_is_blocked(self):
        blocked = document(348, evidence("e348", "OPERATIVE_ARTICLE", "Art.1. Se aprobă ceva."))
        blocked["state"] = "BLOCKED"
        self.assertEqual(adjudicate_document(blocked)["state"], "BLOCKED")
        untrusted = document(349, evidence("e349", "OPERATIVE_ARTICLE", "Art.1. Se aprobă ceva."))
        untrusted["evidence"][0]["epistemic_status"] = "SECOND_HAND"
        result = adjudicate_document(untrusted)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "operative_evidence_not_first_party")

    def test_bundle_remains_non_authorizing(self):
        bundle = {"status": "PASS_SHADOW", "latest_official_adopted_date": "2026-09-16", "rows": [
            document(343, evidence("e343", "OPERATIVE_ARTICLE", "Art.1. Se rectifică bugetul cu 19.010.000 lei.")),
            document(346, evidence("e346", "OPERATIVE_ARTICLE", "Art.2. Prezenta hotărâre se comunică.")),
        ]}
        result = adjudicate_bundle(bundle)
        self.assertEqual(result["materiality_candidate_count"], 1)
        self.assertEqual(result["no_story_count"], 1)
        self.assertEqual(result["fabricated_claim_count"], 0)
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
