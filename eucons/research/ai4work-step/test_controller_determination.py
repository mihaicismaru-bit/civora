from __future__ import annotations

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class ControllerDeterminationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((HERE / "CONTROLLER_DETERMINATION_DRAFT.json").read_text(encoding="utf-8"))
        cls.forms = json.loads((HERE / "forms_definition.json").read_text(encoding="utf-8"))
        cls.form_contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        cls.storage_contract = json.loads((HERE / "PROVIDER_STORAGE_CONTRACT.json").read_text(encoding="utf-8"))

    def test_controller_is_determined_but_collection_remains_fail_closed(self):
        c = self.contract
        self.assertEqual(c["schema_version"], "eucons.ai4work_controller_determination.v0.3")
        self.assertEqual(c["status"], "CONTROLLER_DETERMINED_PROD_PREREQUISITES_PENDING")
        self.assertEqual(c["controller"]["legal_name"], "EUROCONSULT SRL")
        self.assertEqual(c["controller"]["cui"], "14250864")
        self.assertEqual(c["controller"]["role"], "GDPR_CONTROLLER")
        self.assertEqual(c["controller"]["site"], "eucons.ro")
        self.assertEqual(c["controller"]["determination_reference"], "AUTHENTICATED_FIRST_PARTY_USER_DECLARATION_2026_08_28")
        self.assertTrue(c["approved"])
        self.assertFalse(c["collection_enabled"])
        self.assertFalse(c["nf06_reference_eligible"])
        self.assertFalse(c["merge_authorized"])
        self.assertFalse(c["deploy_authorized"])
        self.assertFalse(c["real_collection_authorized"])

    def test_first_party_determination_does_not_overclaim_hosting_account_mapping(self):
        c = self.contract
        boundary = c["controller_source"]["boundary"].lower()
        for phrase in (
            "does not by itself prove",
            "claus web",
            "active cpanel configuration",
            "log retention",
            "backup execution",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, boundary)
        history = c["known_evidence_boundaries"]["hosting_account_history"].lower()
        self.assertIn("mixed", history)
        self.assertIn("must not be collapsed", history)

    def test_project_leader_is_not_silently_promoted_to_controller(self):
        matrix = {row["entity_reference"]: row for row in self.contract["decision_matrix"]}
        leader = matrix["MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE"]
        controller = matrix["EUROCONSULT_SRL_CONTROLLER"]
        self.assertEqual(leader["observed_legal_identity"], "FUNDAŢIA CENTRUL DE PREGĂTIRE PROFESIONALĂ VÂLCEA")
        self.assertFalse(leader["purpose_decision_authority"])
        self.assertFalse(leader["essential_means_authority"])
        self.assertEqual(leader["proposed_role"], "PROJECT_LEADER_NOT_CONTROLLER_FOR_THIS_RESEARCH")
        self.assertTrue(controller["purpose_decision_authority"])
        self.assertTrue(controller["essential_means_authority"])
        self.assertEqual(controller["proposed_role"], "GDPR_CONTROLLER")

    def test_withdrawn_outreach_remains_non_evidence(self):
        c = self.contract
        contact = c["external_contact_state"]
        self.assertEqual(contact["status"], "HOLD_WITHDRAWN_REQUESTS_NO_ACTIVE_AUTHORITY_REQUEST")
        self.assertEqual(contact["project_leader_role_request"], "WITHDRAWN_BY_AUTHENTICATED_USER_2026_08_28")
        self.assertEqual(contact["hosting_account_holder_role_request"], "WITHDRAWN_BY_AUTHENTICATED_USER_2026_08_28")
        self.assertIn("not used as evidence", contact["evidence_rule"].lower())

    def test_provider_documentary_package_is_closed_but_live_account_binding_stays_open(self):
        c = self.contract
        provider_boundary = c["known_evidence_boundaries"]["hosting_provider"].lower()
        self.assertIn("dpa v1.0 plus annex 4 and annex 5", provider_boundary)
        self.assertIn("account-specific cpanel raw access retention/access", provider_boundary)
        self.assertIn("provider-bound deletion/backup", provider_boundary)
        matrix = {row["entity_reference"]: row for row in c["decision_matrix"]}
        provider = matrix["CLAUS_WEB_SRL"]
        self.assertEqual(provider["status"], "ACCOUNT_CONFIGURATION_AND_BINDING_REQUIRED")
        self.assertFalse(provider["purpose_decision_authority"])
        self.assertFalse(provider["processor_instruction_authority"])

    def test_remaining_prod_facts_are_explicit(self):
        remaining = "\n".join(self.contract["remaining_decision_facts"]).lower()
        for phrase in (
            "privacy contact",
            "lawful basis/lia",
            "article 13",
            "dpia",
            "raw access",
            "research-only",
            "deletion/backup",
            "test twin",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, remaining)

    def test_public_artifact_excludes_actual_private_hosting_identifier_values(self):
        rendered = json.dumps(self.contract, ensure_ascii=False).lower()
        self.assertIn("private billing", self.contract["privacy_boundary"].lower())
        for forbidden in ("client id:", "cod client:", "invoice number:", "password:"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_controller_identity_is_propagated_without_fabricating_privacy_contact(self):
        notice = self.forms.get("common_notice") or {}
        self.assertEqual(notice.get("operator_status"), "CONTROLLER_DETERMINED_PRIVACY_CONTACT_OPEN")
        self.assertEqual(notice.get("operator"), "EUROCONSULT SRL")
        self.assertEqual(notice.get("operator_cui"), "14250864")
        self.assertIn("DE COMPLETAT", notice.get("privacy_contact", ""))

        pre_notice = self.form_contract.get("pre_form_notice") or {}
        self.assertEqual(pre_notice.get("operator_legal_name"), "EUROCONSULT SRL")
        self.assertEqual(pre_notice.get("operator_cui"), "14250864")
        self.assertEqual(pre_notice.get("operator_status"), "CONTROLLER_DETERMINED_PRIVACY_CONTACT_OPEN")
        self.assertEqual(pre_notice.get("privacy_contact"), "OPEN_BEFORE_PRODUCTION")
        self.assertEqual(pre_notice.get("operator_contact_details"), "TO_BE_BOUND_BEFORE_PRODUCTION")
        self.assertFalse(self.form_contract["production_enabled"])

        storage_controller = self.storage_contract.get("controller") or {}
        self.assertEqual(storage_controller.get("legal_name"), "EUROCONSULT SRL")
        self.assertEqual(storage_controller.get("cui"), "14250864")
        self.assertEqual(storage_controller.get("status"), "CONTROLLER_DETERMINED_PRIVACY_CONTACT_OPEN")
        self.assertEqual(storage_controller.get("privacy_contact"), "OPEN_BEFORE_PRODUCTION")
        self.assertFalse(self.storage_contract["production_enabled"])


if __name__ == "__main__":
    unittest.main()
