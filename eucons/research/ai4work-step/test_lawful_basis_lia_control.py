from __future__ import annotations

import copy
import unittest

from lawful_basis_lia_control import (
    CONTRACT_PATH,
    CONTROLLER_PATH,
    LIA_PATH,
    MANIFEST_PATH,
    _load,
    evaluate_repository_lia,
    lawful_basis_lia_errors,
)


class LawfulBasisLiaControlTests(unittest.TestCase):
    def load_artifacts(self):
        return (
            _load(CONTRACT_PATH),
            _load(MANIFEST_PATH),
            _load(CONTROLLER_PATH),
            _load(LIA_PATH),
        )

    def test_current_controller_approved_lia_is_structurally_safe_and_collection_stays_fail_closed(self):
        ready, errors = evaluate_repository_lia()
        self.assertTrue(ready, errors)
        _, _, _, lia = self.load_artifacts()
        self.assertEqual(lia["status"], "CONTROLLER_APPROVED_LEGAL_BASIS_OPERATIONAL_GATES_PENDING")
        self.assertTrue(lia["controller_signoff_fields"]["approved"])
        self.assertTrue(lia["prod_approval"]["purpose_test_approved"])
        self.assertTrue(lia["prod_approval"]["necessity_test_approved"])
        self.assertTrue(lia["prod_approval"]["balancing_test_approved"])
        self.assertFalse(lia["prod_approval"]["right_to_object_operational"])
        self.assertFalse(lia["prod_approval"]["article13_basis_disclosure_confirmed"])
        self.assertFalse(lia["prod_eligible"])
        self.assertFalse(lia["collection_enabled"])
        self.assertFalse(lia["real_collection_authorized"])
        self.assertEqual(lia["evidence_binding_key"], "lawful_basis_or_lia")
        self.assertEqual(lia["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")
        self.assertFalse(lia["synthetic"])

    def test_any_prod_activation_claim_still_requires_live_lia_operational_bindings(self):
        contract, manifest, controller, lia = self.load_artifacts()
        contract = copy.deepcopy(contract)
        contract["production_enabled"] = True
        errors = lawful_basis_lia_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            lia=lia,
        )
        self.assertIn("lia_not_approved_for_prod", errors)
        self.assertIn("lia_not_prod_eligible", errors)
        self.assertIn("lia_privacy_contact_missing", errors)
        self.assertIn("lia_prod_approval_state_invalid", errors)
        self.assertIn("lia_prod_approval_not_satisfied:right_to_object_operational", errors)
        self.assertIn("lia_prod_approval_not_satisfied:article13_basis_disclosure_confirmed", errors)
        self.assertIn("lia_prod_approval_not_satisfied:processor_chain_review_complete", errors)
        self.assertIn("lia_prod_approval_not_satisfied:logging_linkability_review_complete", errors)
        self.assertIn("lia_prod_approval_not_satisfied:retention_executable_confirmed", errors)
        self.assertIn("lia_prod_privacy_contact_missing", errors)

    def test_hashable_artifact_with_wrong_controller_identity_is_not_semantically_valid(self):
        contract, manifest, controller, lia = self.load_artifacts()
        lia = copy.deepcopy(lia)
        lia["controller"]["legal_name"] = "OTHER ENTITY"
        errors = lawful_basis_lia_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            lia=lia,
        )
        self.assertIn("lia_controller_identity_mismatch:legal_name", errors)

    def test_commercial_marketing_cannot_be_smuggled_into_lia(self):
        contract, manifest, controller, lia = self.load_artifacts()
        lia = copy.deepcopy(lia)
        lia["purpose_test"]["commercial_marketing_or_lead_generation"] = True
        errors = lawful_basis_lia_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            lia=lia,
        )
        self.assertIn("lia_commercial_marketing_not_forbidden", errors)

    def test_lia_itself_cannot_grant_collection_or_external_action_authority(self):
        contract, manifest, controller, lia = self.load_artifacts()
        lia = copy.deepcopy(lia)
        lia["real_collection_authorized"] = True
        lia["merge_authorized"] = True
        errors = lawful_basis_lia_errors(
            contract=contract,
            manifest=manifest,
            controller=controller,
            lia=lia,
        )
        self.assertIn("lia_must_not_independently_authorize_collection", errors)
        self.assertIn("lia_merge_authority_escalated", errors)


if __name__ == "__main__":
    unittest.main()
