from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from data_subject_rights_control import EXPECTED_BASIS_CODE, data_subject_rights_errors


HERE = Path(__file__).resolve().parent


class DataSubjectRightsControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json").read_text(encoding="utf-8"))
        cls.procedure = json.loads((HERE / "GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json").read_text(encoding="utf-8"))

    def test_current_draft_is_structurally_safe_and_fail_closed(self):
        errors = data_subject_rights_errors(
            contract=self.contract,
            manifest=self.manifest,
            procedure=self.procedure,
        )
        self.assertEqual(errors, [])
        self.assertFalse(self.procedure["controller_approval"])
        self.assertFalse(self.procedure["collection_enabled"])
        self.assertEqual(self.procedure["test_twin"]["classification"], "TEST_TWIN_NON_EVIDENCE")
        self.assertFalse(self.procedure["test_twin"]["prod_promotion_eligible"])

    def test_activation_claim_cannot_bypass_unapproved_rights_procedure(self):
        contract = copy.deepcopy(self.contract)
        manifest = copy.deepcopy(self.manifest)
        contract["production_enabled"] = True
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["real_collection_authorized"] = True
        errors = data_subject_rights_errors(contract=contract, manifest=manifest, procedure=self.procedure)
        self.assertIn("rights_procedure_not_approved_for_prod", errors)
        self.assertIn("rights_controller_approval_missing", errors)
        self.assertIn("rights_request_channel_not_operational", errors)
        self.assertIn("rights_privacy_contact_missing", errors)
        self.assertIn("rights_final_lawful_basis_not_reconciled", errors)
        self.assertIn("rights_requester_authentication_not_operational", errors)
        self.assertIn("rights_prod_approval_shape_invalid", errors)

    def test_direct_identity_or_crm_lookup_weakening_fails_even_before_prod(self):
        procedure = copy.deepcopy(self.procedure)
        procedure["identification_policy"]["direct_identity_registry"] = "ALLOWED"
        procedure["identification_policy"]["crm_or_contact_cross_reference"] = "ALLOWED"
        errors = data_subject_rights_errors(
            contract=self.contract,
            manifest=self.manifest,
            procedure=procedure,
        )
        self.assertIn("identity_linkage_not_forbidden:direct_identity_registry", errors)
        self.assertIn("identity_linkage_not_forbidden:crm_or_contact_cross_reference", errors)

    def test_test_twin_can_never_be_promotable(self):
        procedure = copy.deepcopy(self.procedure)
        procedure["test_twin"]["prod_promotion_eligible"] = True
        errors = data_subject_rights_errors(
            contract=self.contract,
            manifest=self.manifest,
            procedure=procedure,
        )
        self.assertIn("rights_test_twin_promotable", errors)

    def test_fully_bound_shape_requires_final_legitimate_interest_and_operational_rights(self):
        contract = copy.deepcopy(self.contract)
        manifest = copy.deepcopy(self.manifest)
        procedure = copy.deepcopy(self.procedure)
        contract["production_enabled"] = True
        manifest["approved_for_prod"] = True
        manifest["collection_enabled"] = True
        manifest["real_collection_authorized"] = True
        procedure.update(
            {
                "evidence_binding_key": "data_subject_rights_procedure",
                "synthetic": False,
                "status": "APPROVED_FOR_PROD",
                "controller_approval": True,
                "collection_enabled": True,
            }
        )
        procedure["request_channel"] = {
            "privacy_contact": "privacy@example.invalid",
            "status": "OPERATIONAL_FOR_PROD",
        }
        procedure["rights_applicability"]["lawful_basis_status"] = EXPECTED_BASIS_CODE
        procedure["rights_applicability"]["objection"] = "APPLIES"
        procedure["rights_applicability"]["portability"] = "NOT_APPLICABLE_FINAL_LEGITIMATE_INTEREST_BASIS"
        procedure["rights_applicability"]["consent_withdrawal"] = "NOT_APPLICABLE_FINAL_LEGITIMATE_INTEREST_BASIS"
        procedure["research_store_operations"]["access_requester_authentication_reference_adapter"] = "CONTROLLER_APPROVED_OPERATIONAL_AUTHENTICATION"
        procedure["prod_approval"] = {
            "state": "APPROVED_FOR_PROD",
            "approved": True,
            "final_lawful_basis_code": EXPECTED_BASIS_CODE,
            "rights_applicability_reconciled": True,
            "article13_rights_text_reconciled": True,
            "requester_authentication_operational": True,
            "article15_confirmation_context_operational": True,
            "receipt_lookup_operational": True,
            "rectification_operational": True,
            "restriction_objection_hold_operational": True,
            "erasure_operational": True,
            "replay_marker_retention_approved": True,
            "provider_bound_test_twin_pass": True,
            "portability_decision": "NOT_APPLICABLE_FINAL_LEGITIMATE_INTEREST_BASIS",
            "consent_withdrawal_decision": "NOT_APPLICABLE_FINAL_LEGITIMATE_INTEREST_BASIS",
            "privacy_contact": "privacy@example.invalid",
            "approver_name_or_role": "Controller authorised role",
            "approved_at": "2026-09-01",
        }
        errors = data_subject_rights_errors(contract=contract, manifest=manifest, procedure=procedure)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
