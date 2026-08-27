import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class CollectionFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = json.loads((ROOT / "COLLECTION_FRAME_DRAFT.json").read_text(encoding="utf-8"))
        cls.nf06_contract = json.loads((ROOT / "NF06_PREINGEST_CONTRACT.json").read_text(encoding="utf-8"))

    def test_draft_is_fail_closed_and_non_evidence(self):
        f = self.frame
        self.assertEqual(f["research_id"], "AI4WORK-STEP-NF-RUN-001")
        self.assertEqual(f["frame_status"], "DRAFT_NOT_APPROVED_FOR_PROD")
        self.assertEqual(f["evidence_class"], "METHOD_PLAN_NOT_EVIDENCE")
        self.assertFalse(f["collection_enabled"])
        self.assertFalse(f["approval"]["approved"])
        self.assertFalse(f["approval"]["approved_for_prod"])
        self.assertFalse(f["nf06_handoff"]["eligible_now"])

    def test_privacy_boundary_is_preserved(self):
        p = self.frame["privacy_and_separation"]
        self.assertFalse(p["direct_identifiers_collected"])
        self.assertEqual(p["crm_linkage"], "FORBIDDEN")
        self.assertEqual(p["commercial_tracking"], "FORBIDDEN")
        self.assertEqual(p["storage_class"], "RESEARCH_ONLY_SEPARATE_FROM_CRM")
        self.assertFalse(p["raw_ip_in_analytic_dataset"])
        self.assertFalse(p["user_agent_in_analytic_dataset"])
        self.assertFalse(p["free_text_in_analytic_forms"])

    def test_method_does_not_claim_representativeness(self):
        s = self.frame["sampling_design"]
        self.assertFalse(s["representativeness_claim_allowed"])
        self.assertFalse(s["weighting_allowed"])
        self.assertFalse(s["project_activity_as_need_evidence"])
        self.assertFalse(s["synthetic_records_allowed_in_prod"])
        forbidden = " ".join(self.frame["analysis_claims"]["forbidden"]).lower()
        self.assertIn("representative", forbidden)
        self.assertIn("project activities", forbidden)
        self.assertIn("test twin", forbidden)

    def test_both_populations_and_all_three_regions_are_covered(self):
        expected = {"Sud-Vest Oltenia", "Sud-Muntenia", "Centru"}
        pops = self.frame["populations"]
        self.assertEqual(set(pops), {"adults", "employers"})
        self.assertEqual(set(pops["adults"]["eligibility_alignment"]["geography"]), expected)
        self.assertEqual(set(pops["employers"]["geography"]), expected)
        self.assertEqual(pops["adults"]["eligibility_alignment"]["age"], "over 29 years")

    def test_collection_stop_rules_require_real_coverage_and_nf06_preflight(self):
        rules = " ".join(self.frame["qa_stop_rules"]["may_close_collection_only_if"]).lower()
        self.assertIn("both instruments have real valid responses", rules)
        self.assertIn("all three regions", rules)
        self.assertIn("adversarial qa", rules)
        self.assertIn("nf06 pre-ingest", rules)

    def test_duplicate_boundary_does_not_smuggle_identity_tracking(self):
        d = self.frame["duplicate_and_fraud_boundary"]
        self.assertIn("idempotency", d["transport_retry_duplicates"].lower())
        self.assertIn("cannot be reliably detected", d["same_person_multiple_independent_submissions"].lower())
        mitigation = " ".join(d["mitigation"]).lower()
        self.assertIn("without using fingerprinting", mitigation)

    def test_approval_placeholders_cover_nf06_prod_provenance(self):
        required = set(self.nf06_contract["prod_only_required_fields"])
        approval = self.frame["approval"]
        self.assertTrue(required.issubset(set(approval)))
        for field in required:
            self.assertIsNone(approval[field])
        self.assertIsNone(approval["controller_determination_reference"])


if __name__ == "__main__":
    unittest.main()
