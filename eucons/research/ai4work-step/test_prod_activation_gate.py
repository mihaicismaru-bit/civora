from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

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
    HERE,
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

    def _temporary_attestation(self, payload: dict) -> tuple[Path, str]:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix=".tmp_prod_activation_evidence_",
            dir=HERE,
            delete=False,
        )
        try:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        finally:
            handle.close()
        path = Path(handle.name)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

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

    def test_provider_logging_profile_and_live_account_binding_are_distinct(self):
        _, manifest, _, _, _ = self.load_artifacts()
        evidence = manifest["required_external_or_operational_evidence"]
        self.assertIn("provider_server_logging_profile", REQUIRED_EXTERNAL_KEYS)
        self.assertIn("account_server_logging_binding", REQUIRED_EXTERNAL_KEYS)
        self.assertNotIn("server_logging_profile", REQUIRED_EXTERNAL_KEYS)
        self.assertEqual(evidence["provider_server_logging_profile"]["status"], "FROZEN")
        self.assertEqual(evidence["provider_server_logging_profile"]["reference"], "SERVER_LOGGING_BINDING_DRAFT.json")
        self.assertEqual(evidence["account_server_logging_binding"]["status"], "OPEN")
        self.assertIsNone(evidence["account_server_logging_binding"]["reference"])
        ready, errors = evaluate_repository_activation()
        self.assertFalse(ready)
        self.assertIn("external_evidence_status_or_binding_invalid:account_server_logging_binding", errors)
        self.assertFalse(any("provider_server_logging_profile" in item for item in errors))

    def test_live_commercial_privacy_surface_cannot_substitute_for_ai4work_research_chain(self):
        _, manifest, _, _, _ = self.load_artifacts()
        evidence = manifest["required_external_or_operational_evidence"]
        key = "live_public_privacy_surface_reconciliation"
        self.assertIn(key, REQUIRED_EXTERNAL_KEYS)
        self.assertIn(key, evidence)
        gate = evidence[key]
        self.assertEqual(gate["status"], "OPEN")
        self.assertEqual(gate["reference"], "LIVE_PRIVACY_SURFACE_RECONCILIATION_DRAFT.json")
        self.assertRegex(gate["sha256"], r"^[0-9a-f]{64}$")

        path = HERE / gate["reference"]
        self.assertTrue(path.is_file())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), gate["sha256"])
        reconciliation = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(reconciliation["status"], "OPEN_BEFORE_PROD")
        self.assertFalse(reconciliation["prod_reconciled"])
        self.assertFalse(reconciliation["ai4work_controlled_baseline"]["commercial_privacy_hosting_statement_inherited"])
        rendered = json.dumps(reconciliation, ensure_ascii=False).lower()
        self.assertIn("romania-webhosting.com", rendered)
        self.assertIn("claus web", rendered)
        self.assertIn("do not infer", rendered)

        ready, errors = evaluate_repository_activation()
        self.assertFalse(ready)
        self.assertIn(f"external_evidence_status_or_binding_invalid:{key}", errors)

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
        self.assertTrue(any(item.startswith("external_evidence_status_or_binding_invalid:") for item in errors))

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
        self.assertIn("external_evidence_status_or_binding_invalid:privacy_notice", errors)

    def test_operational_evidence_cannot_use_frozen_documentary_status(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        manifest = copy.deepcopy(manifest)
        key = "research_only_store_binding"
        path, digest = self._temporary_attestation(
            {
                "research_id": manifest["research_id"],
                "evidence_binding_key": key,
                "evidence_class": "OPERATIONAL_EVIDENCE",
                "synthetic": False,
            }
        )
        try:
            manifest["required_external_or_operational_evidence"][key] = {
                "status": "FROZEN",
                "reference": path.name,
                "sha256": digest,
            }
            errors = activation_errors(
                contract=contract,
                manifest=manifest,
                controller=controller,
                collection_frame=frame,
                dpia_screening=dpia,
            )
            self.assertIn(f"external_evidence_status_or_binding_invalid:{key}", errors)
        finally:
            path.unlink(missing_ok=True)

    def test_synthetic_complete_control_state_cannot_bypass_evidence_binding(self):
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
        self.assertFalse(any(item.startswith("external_evidence_status_or_binding_invalid:") for item in errors), errors)
        self.assertEqual(
            {item.removeprefix("external_evidence_binding_invalid:") for item in errors if item.startswith("external_evidence_binding_invalid:")},
            REQUIRED_EXTERNAL_KEYS,
        )

    def test_pass_with_correct_hash_but_wrong_semantic_key_is_rejected_by_activation_itself(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        manifest = copy.deepcopy(manifest)
        key = "privacy_notice"
        path, digest = self._temporary_attestation(
            {
                "research_id": manifest["research_id"],
                "evidence_binding_key": "lawful_basis_or_lia",
                "evidence_class": "OPERATIONAL_EVIDENCE",
                "synthetic": False,
            }
        )
        try:
            manifest["required_external_or_operational_evidence"][key] = {
                "status": "PASS",
                "reference": path.name,
                "sha256": digest,
            }
            errors = activation_errors(
                contract=contract,
                manifest=manifest,
                controller=controller,
                collection_frame=frame,
                dpia_screening=dpia,
            )
            self.assertIn("external_evidence_binding_invalid:privacy_notice", errors)
        finally:
            path.unlink(missing_ok=True)

    def test_pass_test_twin_attestation_is_rejected_by_activation_itself(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        manifest = copy.deepcopy(manifest)
        key = "privacy_notice"
        path, digest = self._temporary_attestation(
            {
                "research_id": manifest["research_id"],
                "evidence_binding_key": key,
                "evidence_class": "TEST_TWIN_NON_EVIDENCE",
                "synthetic": True,
            }
        )
        try:
            manifest["required_external_or_operational_evidence"][key] = {
                "status": "APPROVED",
                "reference": path.name,
                "sha256": digest,
            }
            errors = activation_errors(
                contract=contract,
                manifest=manifest,
                controller=controller,
                collection_frame=frame,
                dpia_screening=dpia,
            )
            self.assertIn("external_evidence_binding_invalid:privacy_notice", errors)
        finally:
            path.unlink(missing_ok=True)

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
