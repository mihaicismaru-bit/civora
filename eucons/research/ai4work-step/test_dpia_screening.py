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

    def test_controller_accepted_screening_but_prod_still_fail_closed(self):
        self.assertEqual(self.screen.get("schema_version"), "eucons.ai4work_gdpr_dpia_screening.v0.3")
        self.assertEqual(
            self.screen.get("status"),
            "CONTROLLER_ACCEPTED_SCREENING_OPERATIONAL_GATES_PENDING",
        )
        self.assertEqual(self.screen.get("controller", {}).get("legal_name"), "EUROCONSULT SRL")
        self.assertTrue(self.screen.get("approved"))
        self.assertFalse(self.screen.get("collection_enabled"))
        self.assertEqual(self.screen.get("screening_conclusion"), "DPIA_NOT_REQUIRED_APPROVED")
        self.assertFalse(self.screen.get("real_collection_authorized"))
        assessment = self.screen.get("technical_assessment", {})
        self.assertEqual(assessment.get("recommendation"), "DPIA_NOT_REQUIRED_ON_CURRENT_DESIGN")
        self.assertTrue(assessment.get("controller_acceptance_required"))
        self.assertEqual(assessment.get("controller_identity_status"), "DETERMINED_CONTROLLER_ACCEPTED_SCREENING")
        acceptance = self.screen.get("controller_acceptance", {})
        self.assertTrue(acceptance.get("approved"))
        self.assertIsNone(acceptance.get("privacy_contact_or_dpo_review_reference"))

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
        self.assertEqual(facts["analytical_free_text"], "FORBIDDEN_BY_CONTRACT")

    def test_previously_unresolved_criteria_now_have_design_specific_findings(self):
        criteria = self.screen["edpb_screening_criteria"]
        self.assertEqual(criteria["large_scale_processing"]["state"], "NOT_TRIGGERED_BY_CURRENT_DOCUMENTED_METHOD_SCOPE")
        self.assertEqual(criteria["vulnerable_data_subjects"]["state"], "SAFEGUARDED_NOT_TRIGGERING_MANDATORY_DPIA_ON_CURRENT_DESIGN")
        self.assertEqual(criteria["innovative_technology_or_organisational_solution"]["state"], "NOT_TRIGGERED_BY_CURRENT_PROCESSING")

    def test_anspdcp_check_and_remaining_live_privacy_binding_are_explicit(self):
        check = self.screen["anspdcp_decision_174_2018_check"]
        self.assertTrue(check["technical_check_complete"])
        for key in (
            "systematic_automated_personal_evaluation_with_significant_effect",
            "large_scale_special_category_or_criminal_data",
            "large_scale_public_area_monitoring",
            "large_scale_vulnerable_person_data_with_systematic_monitoring_or_recording",
            "large_scale_innovative_technology_limiting_rights",
            "large_scale_iot_sensor_data",
            "large_scale_or_systematic_traffic_or_location_data",
        ):
            self.assertFalse(check[key])

        mandatory = self.screen["mandatory_before_prod"]
        self.assertTrue(mandatory["controller_determination_approved"])
        self.assertEqual(mandatory["controller_determination_reference"], "CONTROLLER_DETERMINATION_DRAFT.json v0.3")
        self.assertIsNone(mandatory["privacy_contact_or_dpo_review_reference"])
        self.assertIsInstance(mandatory["final_large_scale_assessment"], str)
        self.assertTrue(mandatory["final_large_scale_assessment"])
        self.assertTrue(mandatory["employee_power_imbalance_safeguards_approved"])
        self.assertTrue(mandatory["employee_power_imbalance_safeguards_technical_design_complete"])
        self.assertTrue(mandatory["anspdcp_decision_174_2018_final_check"])
        self.assertEqual(mandatory["final_dpia_decision"], "DPIA_NOT_REQUIRED_APPROVED")
        self.assertIsNone(mandatory["if_dpia_required_completed_dpia_reference"])
        self.assertTrue(mandatory["if_residual_high_risk_prior_consultation_assessed"])

    def test_re_screen_triggers_cover_material_risk_changes(self):
        triggers = "\n".join(self.screen["re_screen_triggers"]).lower()
        for token in ("special-category", "profiling", "crm", "employer", "biometric", "retention", "security"):
            self.assertIn(token, triggers)


if __name__ == "__main__":
    unittest.main()
