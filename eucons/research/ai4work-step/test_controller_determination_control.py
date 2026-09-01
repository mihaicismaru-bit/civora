from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from controller_determination_control import controller_determination_errors

HERE = Path(__file__).resolve().parent


class ControllerDeterminationSemanticControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json").read_text(encoding="utf-8"))
        cls.controller = json.loads((HERE / "CONTROLLER_DETERMINATION_DRAFT.json").read_text(encoding="utf-8"))

    def errors(self, *, contract=None, manifest=None, controller=None):
        return controller_determination_errors(
            contract=copy.deepcopy(contract if contract is not None else self.contract),
            manifest=copy.deepcopy(manifest if manifest is not None else self.manifest),
            controller=copy.deepcopy(controller if controller is not None else self.controller),
        )

    def test_current_repository_controller_determination_is_semantically_valid_and_fail_closed(self):
        self.assertEqual(self.errors(), [])

    def test_controller_identity_drift_is_rejected(self):
        controller = copy.deepcopy(self.controller)
        controller["controller"]["legal_name"] = "OTHER ENTITY"
        self.assertIn("controller_identity_mismatch:legal_name", self.errors(controller=controller))

    def test_project_leader_cannot_be_silently_promoted_to_controller(self):
        controller = copy.deepcopy(self.controller)
        for row in controller["decision_matrix"]:
            if row["entity_reference"] == "MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE":
                row["purpose_decision_authority"] = True
        self.assertIn("project_leader_silently_promoted_to_controller", self.errors(controller=controller))

    def test_hosting_provider_cannot_be_silently_promoted_to_controller(self):
        controller = copy.deepcopy(self.controller)
        for row in controller["decision_matrix"]:
            if row["entity_reference"] == "CLAUS_WEB_SRL":
                row["purpose_decision_authority"] = True
        self.assertIn("hosting_provider_promoted_to_controller", self.errors(controller=controller))

    def test_hosting_history_cannot_be_collapsed_into_current_live_fact(self):
        controller = copy.deepcopy(self.controller)
        controller["known_evidence_boundaries"]["hosting_account_history"] = "EUROCONSULT SRL is the current hosting account."
        self.assertIn("hosting_account_history_collapse_guard_missing", self.errors(controller=controller))

    def test_prod_boolean_shortcut_without_controller_approval_receipt_is_rejected(self):
        contract = copy.deepcopy(self.contract)
        contract["production_enabled"] = True
        controller = copy.deepcopy(self.controller)
        controller.update(
            {
                "status": "APPROVED_FOR_PROD",
                "collection_enabled": True,
                "nf06_reference_eligible": True,
                "real_collection_authorized": True,
                "synthetic": False,
                "privacy_contact": "privacy@controller.invalid",
            }
        )
        errors = self.errors(contract=contract, controller=controller)
        self.assertIn("controller_prod_approval_missing", errors)
        self.assertIn("controller_prod_approval_false", errors)
        self.assertIn("controller_prod_approval_digest_invalid:method_lock_sha256", errors)
        self.assertIn("controller_prod_approval_digest_invalid:frame_lock_sha256", errors)

    def test_prod_approval_requires_nonfuture_approval_and_exact_dual_lock_digests(self):
        contract = copy.deepcopy(self.contract)
        contract["production_enabled"] = True
        controller = copy.deepcopy(self.controller)
        controller.update(
            {
                "status": "APPROVED_FOR_PROD",
                "collection_enabled": True,
                "nf06_reference_eligible": True,
                "real_collection_authorized": True,
                "synthetic": False,
                "privacy_contact": "privacy@example.invalid",
                "prod_approval": {
                    "approved": True,
                    "legal_entity_name": "EUROCONSULT SRL",
                    "approver_name_or_role": "Controller authorised representative",
                    "approved_at": "2099-01-01",
                    "approval_reference": "CONTROLLED_APPROVAL_REFERENCE",
                    "method_lock_sha256": "not-a-digest",
                    "frame_lock_sha256": "b" * 64,
                },
            }
        )
        errors = self.errors(contract=contract, controller=controller)
        self.assertIn("controller_prod_approval_date_invalid", errors)
        self.assertIn("controller_prod_approval_digest_invalid:method_lock_sha256", errors)
        self.assertNotIn("controller_prod_approval_digest_invalid:frame_lock_sha256", errors)

    def test_complete_semantic_controller_prod_approval_shape_is_accepted_by_this_control(self):
        contract = copy.deepcopy(self.contract)
        contract["production_enabled"] = True
        controller = copy.deepcopy(self.controller)
        controller.update(
            {
                "status": "APPROVED_FOR_PROD",
                "collection_enabled": True,
                "nf06_reference_eligible": True,
                "real_collection_authorized": True,
                "synthetic": False,
                "privacy_contact": "privacy@example.invalid",
                "prod_approval": {
                    "approved": True,
                    "legal_entity_name": "EUROCONSULT SRL",
                    "approver_name_or_role": "Controller authorised representative",
                    "approved_at": "2026-09-01",
                    "approval_reference": "CONTROLLED_APPROVAL_REFERENCE",
                    "method_lock_sha256": "a" * 64,
                    "frame_lock_sha256": "b" * 64,
                },
            }
        )
        self.assertEqual(self.errors(contract=contract, controller=controller), [])


if __name__ == "__main__":
    unittest.main()
