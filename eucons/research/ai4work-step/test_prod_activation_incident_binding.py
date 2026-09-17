from __future__ import annotations

import copy
import unittest

from prod_activation_gate import (
    CONTRACT_PATH,
    MANIFEST_PATH,
    CONTROLLER_PATH,
    COLLECTION_FRAME_PATH,
    DPIA_SCREENING_PATH,
    INCIDENT_RESPONSE_PATH,
    _load,
    activation_errors,
)


class ProdActivationIncidentBindingTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(COLLECTION_FRAME_PATH),
            _load(DPIA_SCREENING_PATH),
            _load(INCIDENT_RESPONSE_PATH),
        )

    def _activation_claim(self):
        contract, manifest, controller, frame, dpia, incident = self.load_artifacts()
        contract = copy.deepcopy(contract)
        manifest = copy.deepcopy(manifest)
        contract["production_enabled"] = True
        manifest["state"] = "APPROVED_FOR_PROD"
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["real_collection_authorized"] = True
        return contract, manifest, controller, frame, dpia, incident

    def test_activation_claim_cannot_bypass_unapproved_incident_procedure(self):
        contract, manifest, controller, frame, dpia, incident = self._activation_claim()
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            incident_response=incident,
        )
        self.assertIn("incident_response:incident_response_not_approved_for_prod", errors)
        self.assertIn("incident_response:incident_response_controller_approval_missing", errors)
        self.assertIn("incident_response:incident_response_not_prod_eligible", errors)
        self.assertIn("incident_response:incident_response_binding_missing:privacy_contact", errors)
        self.assertIn("incident_response:mandatory_before_prod_not_satisfied:controller_approval", errors)

    def test_incident_semantic_errors_clear_only_when_operational_bindings_are_complete(self):
        contract, manifest, controller, frame, dpia, incident = self._activation_claim()
        incident = copy.deepcopy(incident)
        incident["status"] = "APPROVED_FOR_PROD"
        incident["controller_approval"] = True
        incident["prod_eligible"] = True
        incident["privacy_contact"] = "privacy@research.example.invalid"
        incident["incident_owner"] = "CONTROLLER_APPROVED_INCIDENT_OWNER"
        incident["breach_register_location"] = "RESEARCH_ONLY_BREACH_REGISTER"
        incident["anspdcp_notification_route"] = "LIVE_VERIFIED_CONTROLLER_ROUTE"
        incident["processor_escalation_route"] = "LIVE_VERIFIED_PROCESSOR_ROUTE"
        for key in incident["mandatory_before_prod"]:
            incident["mandatory_before_prod"][key] = True

        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            incident_response=incident,
        )
        self.assertFalse(any(item.startswith("incident_response:") for item in errors), errors)

    def test_current_repository_state_does_not_mislabel_draft_as_operational_failure(self):
        contract, manifest, controller, frame, dpia, incident = self.load_artifacts()
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            incident_response=incident,
        )
        self.assertFalse(any(item.startswith("incident_response:") for item in errors), errors)
        self.assertIn("form_contract_production_disabled", errors)


if __name__ == "__main__":
    unittest.main()
