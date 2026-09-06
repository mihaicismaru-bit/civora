from __future__ import annotations

import copy
import unittest

from prod_activation_gate import (
    COLLECTION_FRAME_PATH,
    CONTRACT_PATH,
    CONTROLLER_PATH,
    DPIA_SCREENING_PATH,
    LIA_PATH,
    MANIFEST_PATH,
    _load,
    activation_errors,
)


class ProdActivationLiaBindingTests(unittest.TestCase):
    def test_prod_claim_cannot_bypass_missing_live_lia_safeguards_after_controller_approval(self):
        contract = copy.deepcopy(_load(CONTRACT_PATH))
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        controller = _load(CONTROLLER_PATH)
        frame = _load(COLLECTION_FRAME_PATH)
        dpia = _load(DPIA_SCREENING_PATH)
        lia = _load(LIA_PATH)

        contract["production_enabled"] = True
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            lawful_basis_lia=lia,
        )

        self.assertIn("lawful_basis_lia:lia_not_approved_for_prod", errors)
        self.assertIn("lawful_basis_lia:lia_not_prod_eligible", errors)
        self.assertIn("lawful_basis_lia:lia_privacy_contact_missing", errors)
        self.assertIn("lawful_basis_lia:lia_prod_approval_state_invalid", errors)
        self.assertIn("lawful_basis_lia:lia_prod_approval_not_satisfied:right_to_object_operational", errors)
        self.assertIn("lawful_basis_lia:lia_prod_approval_not_satisfied:article13_basis_disclosure_confirmed", errors)
        self.assertNotIn("lawful_basis_lia:lia_controller_signoff_missing", errors)
        self.assertNotIn("lawful_basis_lia:lia_candidate_wording_not_finalized", errors)

    def test_controller_identity_drift_is_rejected_at_authoritative_activation_boundary(self):
        contract = _load(CONTRACT_PATH)
        manifest = _load(MANIFEST_PATH)
        controller = _load(CONTROLLER_PATH)
        frame = _load(COLLECTION_FRAME_PATH)
        dpia = _load(DPIA_SCREENING_PATH)
        lia = copy.deepcopy(_load(LIA_PATH))
        lia["controller"]["cui"] = "00000000"

        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            lawful_basis_lia=lia,
        )
        self.assertIn("lawful_basis_lia:lia_controller_identity_mismatch:cui", errors)


if __name__ == "__main__":
    unittest.main()
