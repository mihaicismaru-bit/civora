import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from contracts import FactKernel
from editorial_integrity import validate_editorial_package
from acceptance_ledger import evaluate_consecutive


def kernel():
    return FactKernel(
        what="Ceva important s-a întâmplat.",
        who="Instituția X",
        where="Vâlcea",
        when="2026-09-18",
        why_it_matters="Afectează direct cititorii.",
        source="Sursa oficială",
        source_url="https://example.org/source",
        claims=("Faptul A este confirmat.", "Faptul B este confirmat."),
        evidence_ids=("ev-a", "ev-b"),
    )


class EditorialIntegrityTest(unittest.TestCase):
    def test_all_article_claims_must_bind_exactly_to_kernel_and_evidence(self):
        package = {
            "body": "A" * 200,
            "claims": [
                {"text": "Faptul A este confirmat.", "kernel_claim_index": 0, "evidence_ids": ["ev-a"]},
                {"text": "Faptul B este confirmat.", "kernel_claim_index": 1, "evidence_ids": ["ev-b"]},
            ],
        }
        result = validate_editorial_package(kernel(), package)
        self.assertTrue(result.pass_gate)
        self.assertEqual(result.bound_claims, 2)

    def test_untraceable_paraphrase_fails_closed(self):
        package = {
            "body": "A" * 200,
            "claims": [
                {"text": "Parafrază care nu există în kernel.", "kernel_claim_index": 0, "evidence_ids": ["ev-a"]}
            ],
        }
        result = validate_editorial_package(kernel(), package)
        self.assertFalse(result.pass_gate)
        self.assertEqual(result.fabricated_claims, 1)
        self.assertIn("claim_0_text_mismatch_kernel_claim", result.errors)

    def test_unbound_claim_fails_closed(self):
        package = {
            "body": "A" * 200,
            "claims": [{"text": "Afirmație nouă", "kernel_claim_index": 99, "evidence_ids": ["ev-a"]}],
        }
        result = validate_editorial_package(kernel(), package)
        self.assertFalse(result.pass_gate)
        self.assertEqual(result.fabricated_claims, 1)

    def test_ten_story_acceptance_is_strict(self):
        rows = []
        for i in range(10):
            rows.append({
                "story_id": f"s{i}",
                "material_signal": True,
                "state": "AUDITED",
                "article": "A" * 200,
                "visual": {
                    "kind": "photograph",
                    "synthetic": False,
                    "editor_approved": True,
                    "rights_basis": "cc",
                    "semantic_relevance": "exact",
                },
                "receipts": {
                    "site": {"status": "DELIVERED", "canonical_url": f"https://example.org/stiri/s{i}/", "readback_ok": True},
                    "facebook": {"status": "DELIVERED", "remote_id": f"fb{i}", "receipt_id": f"fbr{i}", "readback_ok": True},
                    "instagram": {"status": "DELIVERED", "remote_id": f"ig{i}", "receipt_id": f"igr{i}", "readback_ok": True},
                },
                "audit": {
                    "external_truth_ok": True,
                    "duplicates": 0,
                    "fabricated_claims": 0,
                    "manual_intervention": 0,
                    "unresolved_material_signals": 0,
                },
            })
        result = evaluate_consecutive(rows)
        self.assertTrue(result.ready)
        rows[-1]["receipts"]["instagram"]["readback_ok"] = False
        result = evaluate_consecutive(rows)
        self.assertFalse(result.ready)
        self.assertIn("s9:instagram_not_receipt_bound", result.failures)


if __name__ == "__main__":
    unittest.main()
