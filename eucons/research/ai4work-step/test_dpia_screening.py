from __future__ import annotations

import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "GDPR_DPIA_SCREENING_DRAFT.json"


class DpiaScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.screen = json.loads(PATH.read_text(encoding="utf-8"))

    def test_current_screening_is_fail_closed(self):
        self.assertEqual(
            self.screen.get("status"),
            "DRAFT_CONTROLLER_REVIEW_REQUIRED_BEFORE_COLLECTION",
        )
        self.assertFalse(self.screen.get("approved"))
        self.assertFalse(self.screen.get("collection_enabled"))
        self.assertEqual(
            self.screen.get("screening_conclusion"),
            "UNRESOLVED_BEFORE_CONTROLLER_AND_DPO_REVIEW",
        )
        self.assertFalse(self.screen.get("real_collection_authorized"))

    def test_current_design_forbids_high_risk_shortcuts(self):
        facts = self.screen["processing_design_facts"]
        self.assertEqual(facts["direct_identifiers"], "FORBIDDEN_BY_CONTRACT")
        self.assertEqual(facts["special_category_data"], "FORBIDDEN_BY_CONTRACT")
        self.assertEqual(facts["criminal_conviction_data"], "FORBIDDEN_BY_CONTRACT")
        self.assertFalse(facts["profiling_or_person_level_scoring"])
        self.assertFalse(facts["automated_decisions_with_legal_or_similarly_significant_effect"])
        self.assertEqual(facts["crm_or_contact_dataset_matching"], "FORBIDDEN")
        self.assertEqual(facts["device_fingerprinting"], "FORBIDDEN")
        self.assertEqual(facts["commercial_tracking"], "FORBIDDEN")
        self.assertEqual(facts["respondent_level_results_to_employers"], "FORBIDDEN")
        self.assertTrue(facts["research_store_separate_from_crm"])

    def test_unresolved_criteria_remain_explicit(self):
        criteria = self.screen["edpb_screening_criteria"]
        self.assertEqual(criteria["large_scale_processing"]["state"], "UNRESOLVED_CONTROLLER_JUDGMENT")
        self.assertEqual(
            criteria["vulnerable_data_subjects"]["state"],
            "POTENTIALLY_APPLICABLE_REQUIRES_SAFEGUARDS",
        )
        self.assertEqual(
            criteria["innovative_technology_or_organisational_solution"]["state"],
            "UNRESOLVED_CONTROLLER_JUDGMENT",
        )

    def test_mandatory_prod_decisions_are_unapproved(self):
        mandatory = self.screen["mandatory_before_prod"]
        self.assertFalse(mandatory["controller_determination_approved"])
        self.assertIsNone(mandatory["privacy_contact_or_dpo_review_reference"])
        self.assertIsNone(mandatory["final_large_scale_assessment"])
        self.assertFalse(mandatory["employee_power_imbalance_safeguards_approved"])
        self.assertFalse(mandatory["anspdcp_decision_174_2018_final_check"])
        self.assertIsNone(mandatory["final_dpia_decision"])
        self.assertIsNone(mandatory["if_dpia_required_completed_dpia_reference"])
        self.assertFalse(mandatory["if_residual_high_risk_prior_consultation_assessed"])

    def test_re_screen_triggers_cover_material_risk_changes(self):
        triggers = "\n".join(self.screen["re_screen_triggers"]).lower()
        for token in ("special-category", "profiling", "crm", "employer", "biometric", "retention", "security"):
            self.assertIn(token, triggers)


if __name__ == "__main__":
    unittest.main()
