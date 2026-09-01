from __future__ import annotations

import copy
import unittest

from dpia_screening_control import (
    CONTRACT_PATH,
    CONTROLLER_PATH,
    DPIA_SCREENING_PATH,
    MANIFEST_PATH,
    _load,
    dpia_screening_errors,
    evaluate_repository_dpia,
)


class DpiaScreeningControlTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(DPIA_SCREENING_PATH),
        )

    def test_current_draft_is_structurally_valid_and_fail_closed(self):
        ready, errors = evaluate_repository_dpia()
        self.assertTrue(ready, errors)
        _, _, _, screening = self.load_artifacts()
        self.assertFalse(screening["approved"])
        self.assertFalse(screening["collection_enabled"])
        self.assertFalse(screening["real_collection_authorized"])
        self.assertEqual(screening["evidence_binding_key"], "dpia_screening_or_completed_dpia")
        self.assertFalse(screening["synthetic"])

    def test_crm_or_special_category_weakening_is_rejected(self):
        contract, manifest, controller, screening = self.load_artifacts()
        screening = copy.deepcopy(screening)
        screening["processing_design_facts"]["crm_or_contact_dataset_matching"] = "ALLOWED"
        screening["processing_design_facts"]["special_category_data"] = "ALLOWED"
        errors = dpia_screening_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            screening=screening,
        )
        self.assertIn("dpia_processing_safeguard_invalid:crm_or_contact_dataset_matching", errors)
        self.assertIn("dpia_processing_safeguard_invalid:special_category_data", errors)

    def test_prod_claim_requires_controller_acceptance_not_boolean_shortcut(self):
        contract, manifest, controller, screening = self.load_artifacts()
        contract = copy.deepcopy(contract)
        contract["production_enabled"] = True
        errors = dpia_screening_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            screening=screening,
        )
        self.assertIn("dpia_not_approved_for_prod", errors)
        self.assertIn("dpia_approval_missing", errors)
        self.assertIn("dpia_collection_not_enabled", errors)
        self.assertIn("dpia_conclusion_not_final", errors)
        self.assertIn("dpia_controller_acceptance_missing", errors)
        self.assertIn("dpia_controller_acceptance_not_approved", errors)
        self.assertIn("dpia_controller_approver_missing", errors)
        self.assertIn("dpia_controller_approval_date_invalid", errors)

    def test_test_twin_or_synthetic_screening_cannot_promote(self):
        contract, manifest, controller, screening = self.load_artifacts()
        screening = copy.deepcopy(screening)
        screening["synthetic"] = True
        screening["processing_design_facts"]["test_twin_policy"] = "TEST_TWIN_PROMOTABLE"
        errors = dpia_screening_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            screening=screening,
        )
        self.assertIn("dpia_must_not_be_synthetic", errors)
        self.assertIn("dpia_processing_safeguard_invalid:test_twin_policy", errors)

    def test_completed_dpia_path_requires_immutable_reference_hash(self):
        contract, manifest, controller, screening = self.load_artifacts()
        contract = copy.deepcopy(contract)
        screening = copy.deepcopy(screening)
        contract["production_enabled"] = True
        screening["status"] = "APPROVED_FOR_PROD"
        screening["approved"] = True
        screening["collection_enabled"] = True
        screening["screening_conclusion"] = "DPIA_REQUIRED_COMPLETED_AND_APPROVED"
        screening["mandatory_before_prod"]["privacy_contact_or_dpo_review_reference"] = "PRIVACY_REVIEW_REAL"
        screening["mandatory_before_prod"]["employee_power_imbalance_safeguards_approved"] = True
        screening["mandatory_before_prod"]["final_dpia_decision"] = "DPIA_REQUIRED_COMPLETED_AND_APPROVED"
        screening["controller_acceptance"] = {
            "approved": True,
            "legal_entity_name": "EUROCONSULT SRL",
            "approver_name_or_role": "CONTROLLER_AUTHORIZED_ROLE",
            "approved_at": "2026-09-01",
            "privacy_contact_or_dpo_review_reference": "PRIVACY_REVIEW_REAL",
        }
        screening["mandatory_before_prod"]["if_dpia_required_completed_dpia_reference"] = None
        errors = dpia_screening_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            screening=screening,
        )
        self.assertIn("completed_dpia_reference_missing", errors)
        self.assertIn("completed_dpia_sha256_missing_or_invalid", errors)


if __name__ == "__main__":
    unittest.main()
