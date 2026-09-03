from __future__ import annotations

import copy
import unittest

from prod_activation_gate import (
    COLLECTION_FRAME_PATH,
    CONTRACT_PATH,
    CONTROLLER_PATH,
    DPIA_SCREENING_PATH,
    MANIFEST_PATH,
    _load,
    activation_errors,
)


class ProdActivationDpiaBindingTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(COLLECTION_FRAME_PATH),
            _load(DPIA_SCREENING_PATH),
        )

    def test_prod_claim_cannot_bypass_missing_live_privacy_binding_after_controller_acceptance(self):
        contract, manifest, controller, frame, screening = self.load_artifacts()
        contract = copy.deepcopy(contract)
        contract["production_enabled"] = True
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=screening,
        )
        self.assertIn("dpia_screening:dpia_not_approved_for_prod", errors)
        self.assertIn("dpia_screening:dpia_collection_not_enabled", errors)
        self.assertIn("dpia_screening:dpia_privacy_review_reference_missing", errors)
        self.assertIn("dpia_screening:dpia_controller_privacy_review_binding_missing", errors)
        self.assertNotIn("dpia_screening:dpia_controller_acceptance_missing", errors)
        self.assertNotIn("dpia_screening:dpia_controller_acceptance_not_approved", errors)

    def test_risk_design_weakening_is_rejected_at_authoritative_activation_boundary(self):
        contract, manifest, controller, frame, screening = self.load_artifacts()
        screening = copy.deepcopy(screening)
        screening["processing_design_facts"]["crm_or_contact_dataset_matching"] = "ALLOWED"
        screening["processing_design_facts"]["profiling_or_person_level_scoring"] = True
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=screening,
        )
        self.assertIn(
            "dpia_screening:dpia_processing_safeguard_invalid:crm_or_contact_dataset_matching",
            errors,
        )
        self.assertIn(
            "dpia_screening:dpia_high_risk_feature_not_forbidden:profiling_or_person_level_scoring",
            errors,
        )

    def test_synthetic_dpia_artifact_is_rejected_at_authoritative_activation_boundary(self):
        contract, manifest, controller, frame, screening = self.load_artifacts()
        screening = copy.deepcopy(screening)
        screening["synthetic"] = True
        errors = activation_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            collection_frame=frame,
            dpia_screening=screening,
        )
        self.assertIn("dpia_screening:dpia_must_not_be_synthetic", errors)


if __name__ == "__main__":
    unittest.main()
