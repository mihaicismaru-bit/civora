from __future__ import annotations

import copy
import unittest

from prod_activation_gate import (
    REQUIRED_EXTERNAL_KEYS,
    activation_errors,
    assert_repository_fail_closed_or_approved,
    evaluate_repository_activation,
    _load,
    CONTRACT_PATH,
    MANIFEST_PATH,
    CONTROLLER_PATH,
    COLLECTION_FRAME_PATH,
    DPIA_SCREENING_PATH,
)


class ProdActivationGateTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(COLLECTION_FRAME_PATH),
            _load(DPIA_SCREENING_PATH),
        )

    def test_current_repository_state_is_fail_closed_and_safe(self):
        ready, errors = evaluate_repository_activation()
        self.assertFalse(ready)
        self.assertIn("form_contract_production_disabled", errors)
        self.assertIn("activation_manifest_not_approved", errors)
        self.assertIn("explicit_user_approval_missing", errors)
        self.assertIn("controller_collection_disabled", errors)
        self.assertIn("controller_not_nf06_eligible", errors)
        self.assertIn("dpia_screening_not_approved", errors)
        self.assertIn("dpia_screening_conclusion_unresolved", errors)
        assert_repository_fail_closed_or_approved()

    def test_setting_only_production_enabled_cannot_activate_collection(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        contract = copy.deepcopy(contract)
        contract["production_enabled"] = True
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertNotIn("controller_unresolved", errors)
        self.assertIn("controller_collection_disabled", errors)
        self.assertIn("controller_not_nf06_eligible", errors)
        self.assertIn("activation_manifest_not_approved", errors)
        self.assertIn("collection_frame_not_approved", errors)
        self.assertIn("dpia_screening_not_approved", errors)
        self.assertTrue(any(item.startswith("external_evidence_not_frozen:") for item in errors))

    def test_external_reference_requires_immutable_sha256(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        contract = copy.deepcopy(contract)
        manifest = copy.deepcopy(manifest)
        contract["production_enabled"] = True
        manifest["state"] = "APPROVED_FOR_PROD"
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["explicit_user_approval_reference"] = "TEST_ONLY_APPROVAL"
        manifest["approval_timestamp"] = "2026-08-27T00:00:00Z"
        manifest["real_collection_authorized"] = True
        manifest["required_external_or_operational_evidence"]["privacy_notice"] = {
            "status": "APPROVED",
            "reference": "TEST_ONLY_NOTICE",
            "sha256": None,
        }
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertIn("external_evidence_not_frozen:privacy_notice", errors)

    def test_synthetic_complete_control_state_can_be_evaluated_without_becoming_evidence(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        contract = copy.deepcopy(contract)
        manifest = copy.deepcopy(manifest)
        controller = copy.deepcopy(controller)
        frame = copy.deepcopy(frame)
        dpia = copy.deepcopy(dpia)

        contract["production_enabled"] = True
        manifest["state"] = "APPROVED_FOR_PROD"
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["explicit_user_approval_reference"] = "TEST_ONLY_NOT_EVIDENCE"
        manifest["approval_timestamp"] = "2026-08-27T00:00:00Z"
        manifest["real_collection_authorized"] = True
        for key in REQUIRED_EXTERNAL_KEYS:
            manifest["required_external_or_operational_evidence"][key] = {
                "status": "PASS",
                "reference": f"TEST_ONLY_NON_EVIDENCE:{key}",
                "sha256": "0" * 64,
            }

        controller["status"] = "APPROVED_FOR_PROD"
        controller["controller"] = "TEST_ONLY_CONTROLLER_NON_EVIDENCE"
        controller["approved"] = True
        controller["collection_enabled"] = True
        controller["nf06_reference_eligible"] = True

        frame["frame_status"] = "APPROVED_FOR_PROD"
        frame["collection_enabled"] = True
        frame["approval"]["approved"] = True
        frame["approval"]["approved_for_prod"] = True
        frame["nf06_handoff"]["eligible_now"] = True

        dpia["status"] = "APPROVED_FOR_PROD"
        dpia["approved"] = True
        dpia["collection_enabled"] = True
        dpia["screening_conclusion"] = "DPIA_NOT_REQUIRED_APPROVED"
        mandatory = dpia["mandatory_before_prod"]
        mandatory["controller_determination_approved"] = True
        mandatory["privacy_contact_or_dpo_review_reference"] = "TEST_ONLY_NON_EVIDENCE"
        mandatory["final_large_scale_assessment"] = "TEST_ONLY_NOT_LARGE_SCALE_DECISION"
        mandatory["employee_power_imbalance_safeguards_approved"] = True
        mandatory["anspdcp_decision_174_2018_final_check"] = True
        mandatory["final_dpia_decision"] = "TEST_ONLY_DPIA_NOT_REQUIRED"
        mandatory["if_residual_high_risk_prior_consultation_assessed"] = True

        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertEqual(errors, [])

    def test_required_dpia_must_have_completed_reference(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        dpia = copy.deepcopy(dpia)
        dpia["approved"] = True
        dpia["collection_enabled"] = True
        dpia["screening_conclusion"] = "DPIA_REQUIRED_COMPLETED_AND_APPROVED"
        mandatory = dpia["mandatory_before_prod"]
        mandatory["controller_determination_approved"] = True
        mandatory["privacy_contact_or_dpo_review_reference"] = "TEST_ONLY"
        mandatory["final_large_scale_assessment"] = "TEST_ONLY"
        mandatory["employee_power_imbalance_safeguards_approved"] = True
        mandatory["anspdcp_decision_174_2018_final_check"] = True
        mandatory["final_dpia_decision"] = "TEST_ONLY_REQUIRED"
        mandatory["if_residual_high_risk_prior_consultation_assessed"] = True
        mandatory["if_dpia_required_completed_dpia_reference"] = None
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertIn("completed_dpia_reference_missing", errors)

    def test_unexpected_external_gate_key_fails_closed(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        manifest = copy.deepcopy(manifest)
        manifest["required_external_or_operational_evidence"]["unexpected_gate"] = {
            "status": "PASS",
            "reference": "TEST_ONLY",
            "sha256": "0" * 64,
        }
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertTrue(any(item.startswith("external_evidence_keys_unexpected:") for item in errors))


if __name__ == "__main__":
    unittest.main()
