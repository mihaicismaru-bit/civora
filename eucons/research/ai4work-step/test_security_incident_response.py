from __future__ import annotations

import copy
import unittest

from security_incident_response_gate import (
    CONTRACT_PATH,
    MANIFEST_PATH,
    PROCEDURE_PATH,
    _load,
    evaluate_repository_incident_response,
    incident_response_errors,
)


class SecurityIncidentResponseGateTests(unittest.TestCase):
    def load_artifacts(self):
        return _load(CONTRACT_PATH), _load(MANIFEST_PATH), _load(PROCEDURE_PATH)

    def test_current_draft_is_structurally_complete_and_fail_closed(self):
        ready, errors = evaluate_repository_incident_response()
        self.assertTrue(ready, errors)
        contract, manifest, procedure = self.load_artifacts()
        self.assertFalse(contract.get("production_enabled"))
        self.assertFalse(manifest.get("approved_for_prod"))
        self.assertFalse(manifest.get("collection_enabled"))
        self.assertFalse(manifest.get("real_collection_authorized"))
        self.assertFalse(procedure.get("controller_approval"))
        self.assertFalse(procedure.get("prod_eligible"))
        self.assertFalse(procedure.get("collection_enabled"))

    def test_prod_claim_cannot_bypass_controller_and_live_incident_bindings(self):
        contract, manifest, procedure = self.load_artifacts()
        contract = copy.deepcopy(contract)
        manifest = copy.deepcopy(manifest)
        contract["production_enabled"] = True
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["real_collection_authorized"] = True
        errors = incident_response_errors(contract=contract, manifest=manifest, procedure=procedure)
        self.assertIn("incident_response_not_approved_for_prod", errors)
        self.assertIn("incident_response_controller_approval_missing", errors)
        self.assertIn("incident_response_not_prod_eligible", errors)
        self.assertIn("incident_response_binding_missing:privacy_contact", errors)
        self.assertIn("mandatory_before_prod_not_satisfied:anspdcp_notification_route_live_verified", errors)
        self.assertIn("mandatory_before_prod_not_satisfied:provider_breach_notification_contract_path_verified", errors)

    def test_hypothetical_approved_procedure_requires_all_bindings_and_can_pass(self):
        contract, manifest, procedure = self.load_artifacts()
        contract = copy.deepcopy(contract)
        manifest = copy.deepcopy(manifest)
        procedure = copy.deepcopy(procedure)
        contract["production_enabled"] = True
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["real_collection_authorized"] = True
        procedure["status"] = "APPROVED_FOR_PROD"
        procedure["controller_approval"] = True
        procedure["prod_eligible"] = True
        procedure["collection_enabled"] = True
        procedure["privacy_contact"] = "privacy@example.invalid"
        procedure["incident_owner"] = "CONTROLLER_APPROVED_ROLE"
        procedure["breach_register_location"] = "CONTROLLER_APPROVED_RESEARCH_SECURITY_REGISTER"
        procedure["anspdcp_notification_route"] = "CONTROLLER_VERIFIED_OFFICIAL_ROUTE"
        procedure["processor_escalation_route"] = "CONTROLLER_VERIFIED_PROCESSOR_ROUTE"
        for key in procedure["mandatory_before_prod"]:
            procedure["mandatory_before_prod"][key] = True
        errors = incident_response_errors(contract=contract, manifest=manifest, procedure=procedure)
        self.assertEqual(errors, [])

    def test_test_twin_must_remain_non_evidence(self):
        contract, manifest, procedure = self.load_artifacts()
        procedure = copy.deepcopy(procedure)
        procedure["scope"]["test_twin_policy"] = "PROMOTABLE"
        errors = incident_response_errors(contract=contract, manifest=manifest, procedure=procedure)
        self.assertIn("test_twin_incident_policy_not_non_evidence", errors)

    def test_automatic_external_notification_is_rejected(self):
        contract, manifest, procedure = self.load_artifacts()
        procedure = copy.deepcopy(procedure)
        procedure["external_communication_boundary"]["automatic_external_notification"] = True
        errors = incident_response_errors(contract=contract, manifest=manifest, procedure=procedure)
        self.assertIn("automatic_external_notification_not_forbidden", errors)

    def test_72_hour_clock_and_breach_register_are_mandatory(self):
        contract, manifest, procedure = self.load_artifacts()
        procedure = copy.deepcopy(procedure)
        procedure["awareness_and_clock"]["supervisory_authority_target"] = "WITHOUT_UNDUE_DELAY"
        procedure["breach_register_minimum"].remove("controller_awareness_at")
        errors = incident_response_errors(contract=contract, manifest=manifest, procedure=procedure)
        self.assertIn("supervisory_authority_72_hour_clock_missing", errors)
        self.assertTrue(any(item.startswith("breach_register_fields_missing:") for item in errors))


if __name__ == "__main__":
    unittest.main()
