from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from contracts import FactKernel  # noqa: E402
from municipal_article_integrity import POLICY_NOTE, validate_municipal_article  # noqa: E402


def kernel() -> FactKernel:
    return FactKernel(
        what="Hotărârea nr. 343/2026-09-16 rectifică bugetul creditelor interne pe 2026.",
        who="Consiliul Local al Municipiului Râmnicu Vâlcea",
        where="Râmnicu Vâlcea",
        when="2026-09-16 — data adoptării; nu este data cheltuirii efective",
        why_it_matters="Decizia schimbă finanțarea locală; nu dovedește că sumele au fost deja cheltuite.",
        source="Consiliul Local — HCL 343",
        source_url="https://dm.primariavl.ro/dm/2026/hotarari.nsf/ABC/$FILE/h343.htm",
        claims=("Hotărârea nr. 343/2026-09-16 rectifică bugetul creditelor interne pe 2026.",),
        evidence_ids=("e343",),
    )


def package(k: FactKernel):
    segments = [
        {"kind": "kernel_claim", "kernel_claim_index": 0, "text": k.claims[0], "evidence_ids": ["e343"]},
        {"kind": "kernel_when", "text": f"Momentul documentat: {k.when}.", "evidence_ids": ["e343"]},
        {"kind": "kernel_why_it_matters", "text": f"De ce contează: {k.why_it_matters}", "evidence_ids": ["e343"]},
        {"kind": "kernel_source", "text": f"Sursa: {k.source} — {k.source_url}", "evidence_ids": ["e343"]},
        {"kind": "policy_note", "text": POLICY_NOTE, "evidence_ids": []},
    ]
    return {
        "headline": k.what,
        "dek": k.why_it_matters,
        "body": "\n\n".join(row["text"] for row in segments),
        "body_segments": segments,
        "claims": [{"text": k.claims[0], "kernel_claim_index": 0, "evidence_ids": ["e343"]}],
    }


class MunicipalArticleIntegrityTests(unittest.TestCase):
    def test_exact_controlled_body_passes(self):
        k = kernel()
        result = validate_municipal_article(k, package(k))
        self.assertTrue(result.pass_gate)
        self.assertEqual(result.fabricated_claims, 0)

    def test_uncontrolled_body_sentence_fails(self):
        k = kernel()
        p = package(k)
        p["body"] += "\n\nBanii au fost deja cheltuiți integral."
        result = validate_municipal_article(k, p)
        self.assertFalse(result.pass_gate)
        self.assertIn("body_contains_uncontrolled_or_missing_text", result.errors)
        self.assertGreater(result.fabricated_claims, 0)

    def test_changed_headline_fails_even_when_claim_binding_is_valid(self):
        k = kernel()
        p = package(k)
        p["headline"] = "Primăria a cheltuit deja banii"
        result = validate_municipal_article(k, p)
        self.assertFalse(result.pass_gate)
        self.assertIn("headline_not_exact_kernel_what", result.errors)

    def test_unknown_evidence_fails(self):
        k = kernel()
        p = copy.deepcopy(package(k))
        p["claims"][0]["evidence_ids"] = ["unknown"]
        result = validate_municipal_article(k, p)
        self.assertFalse(result.pass_gate)
        self.assertGreater(result.fabricated_claims, 0)


if __name__ == "__main__":
    unittest.main()
