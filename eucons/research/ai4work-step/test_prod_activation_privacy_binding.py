from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from prod_activation_gate import (
    COLLECTION_FRAME_PATH,
    CONTRACT_PATH,
    CONTROLLER_PATH,
    DPIA_SCREENING_PATH,
    MANIFEST_PATH,
    _load,
    activation_errors,
)


class ProdActivationPrivacyBindingTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(COLLECTION_FRAME_PATH),
            _load(DPIA_SCREENING_PATH),
        )

    def _activation_claim(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        contract = copy.deepcopy(contract)
        manifest = copy.deepcopy(manifest)
        contract["production_enabled"] = True
        manifest["state"] = "APPROVED_FOR_PROD"
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["real_collection_authorized"] = True
        return contract, manifest, controller, frame, dpia

    def test_activation_claim_cannot_bypass_unpromoted_article13_notice(self):
        contract, manifest, controller, frame, dpia = self._activation_claim()
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertIn(
            "privacy_notice_binding:privacy_notice_not_promoted_before_prod_activation",
            errors,
        )

    def test_activation_itself_invokes_article13_nf06_semantic_validator(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        with patch(
            "prod_activation_gate.privacy_notice_binding_errors",
            return_value=["TEST_SENTINEL_PRIVACY_SEMANTIC_FAILURE"],
        ) as validator:
            errors = activation_errors(
                contract=contract,
                manifest=manifest,
                controller=controller,
                collection_frame=frame,
                dpia_screening=dpia,
            )
        validator.assert_called_once()
        self.assertIn(
            "privacy_notice_binding:TEST_SENTINEL_PRIVACY_SEMANTIC_FAILURE",
            errors,
        )

    def test_current_draft_state_does_not_create_false_privacy_operational_failure(self):
        contract, manifest, controller, frame, dpia = self.load_artifacts()
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
        )
        self.assertFalse(any(item.startswith("privacy_notice_binding:") for item in errors), errors)
        self.assertIn("form_contract_production_disabled", errors)


if __name__ == "__main__":
    unittest.main()
