from __future__ import annotations

import copy
import unittest

from prod_activation_gate import (
    COLLECTION_FRAME_PATH,
    CONTRACT_PATH,
    CONTROLLER_PATH,
    DPIA_SCREENING_PATH,
    MANIFEST_PATH,
    RIGHTS_PATH,
    _load,
    activation_errors,
)


class ProdActivationRightsBindingTests(unittest.TestCase):
    def test_prod_claim_cannot_bypass_unapproved_rights_procedure(self):
        contract = copy.deepcopy(_load(CONTRACT_PATH))
        manifest = copy.deepcopy(_load(MANIFEST_PATH))
        controller = _load(CONTROLLER_PATH)
        frame = _load(COLLECTION_FRAME_PATH)
        dpia = _load(DPIA_SCREENING_PATH)
        rights = _load(RIGHTS_PATH)

        contract["production_enabled"] = True
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            data_subject_rights=rights,
        )

        self.assertIn("data_subject_rights:rights_procedure_not_approved_for_prod", errors)
        self.assertIn("data_subject_rights:rights_controller_approval_missing", errors)
        self.assertIn("data_subject_rights:rights_request_channel_not_operational", errors)
        self.assertIn("data_subject_rights:rights_prod_privacy_contact_missing", errors)
        self.assertNotIn("data_subject_rights:rights_requester_authentication_not_operational", errors)

    def test_identity_linkage_weakening_is_rejected_at_authoritative_activation_boundary(self):
        contract = _load(CONTRACT_PATH)
        manifest = _load(MANIFEST_PATH)
        controller = _load(CONTROLLER_PATH)
        frame = _load(COLLECTION_FRAME_PATH)
        dpia = _load(DPIA_SCREENING_PATH)
        rights = copy.deepcopy(_load(RIGHTS_PATH))
        rights["identification_policy"]["crm_or_contact_cross_reference"] = "ALLOWED"

        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            data_subject_rights=rights,
        )
        self.assertIn(
            "data_subject_rights:identity_linkage_not_forbidden:crm_or_contact_cross_reference",
            errors,
        )

    def test_test_twin_rights_artifact_can_never_be_promoted(self):
        contract = _load(CONTRACT_PATH)
        manifest = _load(MANIFEST_PATH)
        controller = _load(CONTROLLER_PATH)
        frame = _load(COLLECTION_FRAME_PATH)
        dpia = _load(DPIA_SCREENING_PATH)
        rights = copy.deepcopy(_load(RIGHTS_PATH))
        rights["test_twin"]["prod_promotion_eligible"] = True

        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=dpia,
            data_subject_rights=rights,
        )
        self.assertIn("data_subject_rights:rights_test_twin_promotable", errors)


if __name__ == "__main__":
    unittest.main()
