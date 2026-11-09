from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from municipal_fact_kernel_shadow_lane import compose_bundle, compose_document_kernel  # noqa: E402


def ev(eid: str, kind: str, excerpt: str):
    return {"evidence_id": eid, "kind": kind, "excerpt": excerpt, "epistemic_status": "FIRST_PARTY_DOCUMENT_TEXT"}


def doc(number: int, *evidence):
    return {
        "decision_number": number,
        "decision_date": "2026-09-16",
        "state": "DOCUMENT_EVIDENCE_READY",
        "official_html_url": f"https://dm.primariavl.ro/dm/2026/hotarari.nsf/ABC{number}/$FILE/h{number}.htm",
        "evidence": list(evidence),
    }


def mat(number: int, category: str, ids: list[str], details=None):
    return {
        "decision_number": number,
        "decision_date": "2026-09-16",
        "state": "MATERIALITY_CANDIDATE",
        "materiality_candidates": [{"category": category, "evidence_ids": ids, "details": details or {}}],
    }


class MunicipalFactKernelShadowLaneTests(unittest.TestCase):
    def test_finance_kernel_is_evidence_bound_and_non_authorizing(self):
        d = doc(343, ev("a", "OPERATIVE_ARTICLE", "Art.1. Se rectifică bugetul creditelor interne prin majorarea cu 19.010.000 lei, ajungând la 30.000.000 lei și redistribuirea între obiective de investiții."))
        m = mat(343, "LOCAL_PUBLIC_FINANCE", ["a"], {"amounts_lei": [19010000, 30000000]})
        result = compose_document_kernel(d, m)
        self.assertEqual(result["state"], "FACT_KERNEL_VERIFIED_SHADOW")
        k = result["kernels"][0]["fact_kernel"]
        self.assertIn("19.010.000 lei", k["what"])
        self.assertIn("30.000.000 lei", k["what"])
        self.assertIn("nu este tratată ca dată a cheltuirii efective", k["when"])
        self.assertEqual(k["evidence_ids"], ["a"])
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["site_publish_allowed"])

    def test_education_kernel_extracts_school_from_document_not_title(self):
        excerpt = "Art.1. Se completează rețeaua școlară pentru anul școlar 2026–2027 în sensul introducerii unității de învățământ preuniversitar particular – Școala primară Licurici (PJ) la Învățământ Particular - poziția nr.10."
        result = compose_document_kernel(doc(344, ev("b", "OPERATIVE_ARTICLE", excerpt)), mat(344, "LOCAL_EDUCATION_ACCESS", ["b"]))
        self.assertEqual(result["state"], "FACT_KERNEL_VERIFIED_SHADOW")
        self.assertIn("Școala primară Licurici", result["kernels"][0]["fact_kernel"]["who"])

    def test_authorization_kernel_extracts_operator_workpoint_and_fee(self):
        operative = "Art.1. Se aprobă acordarea autorizației anuale de funcționare pentru jocuri de noroc (slot-machine) operatorului economic GEAR SLOT S.R.L., pentru punctul de lucru situat în Râmnicu-Vâlcea, str. Calea lui Traian nr.245A, SPAȚIU COMERCIAL, parter."
        money = "Taxa locală anuală pentru eliberarea autorizației este de 125.000 lei."
        d = doc(345, ev("c1", "OPERATIVE_ARTICLE", operative), ev("c2", "MONEY_CONTEXT", money))
        m = mat(345, "REGULATED_LOCAL_AUTHORIZATION", ["c1", "c2"], {"annual_local_fee_lei": 125000})
        result = compose_document_kernel(d, m)
        self.assertEqual(result["state"], "FACT_KERNEL_VERIFIED_SHADOW")
        k = result["kernels"][0]["fact_kernel"]
        self.assertIn("GEAR SLOT S.R.L.", k["who"])
        self.assertIn("Calea lui Traian nr. 245A", k["where"])
        self.assertEqual(len(k["claims"]), 2)
        self.assertTrue(result["kernels"][0]["integrity"]["all_claims_evidence_bound"])
        self.assertEqual(result["kernels"][0]["integrity"]["fabricated_claims"], 0)

    def test_missing_candidate_evidence_fails_closed(self):
        d = doc(343, ev("a", "OPERATIVE_ARTICLE", "Art.1. Se rectifică bugetul cu 19.010.000 lei până la 30.000.000 lei."))
        result = compose_document_kernel(d, mat(343, "LOCAL_PUBLIC_FINANCE", ["missing"], {"amounts_lei": [19010000, 30000000]}))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["writer_allowed"])

    def test_materiality_no_story_passes_through_without_kernel(self):
        d = doc(346, ev("x", "OPERATIVE_ARTICLE", "Art.1. Se comunică hotărârea."))
        materiality = {"decision_number": 346, "decision_date": "2026-09-16", "state": "NO_STORY", "reason": "no material consequence"}
        result = compose_document_kernel(d, materiality)
        self.assertEqual(result["state"], "NO_STORY")
        self.assertNotIn("kernels", result)

    def test_bundle_keeps_every_production_gate_closed(self):
        documents = {"rows": [doc(343, ev("a", "OPERATIVE_ARTICLE", "Art.1. Se rectifică bugetul cu 19.010.000 lei până la 30.000.000 lei."))]}
        materiality = {"rows": [mat(343, "LOCAL_PUBLIC_FINANCE", ["a"], {"amounts_lei": [19010000, 30000000]})]}
        result = compose_bundle(documents, materiality)
        self.assertEqual(result["verified_fact_kernel_row_count"], 1)
        self.assertEqual(result["fabricated_claim_count"], 0)
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
