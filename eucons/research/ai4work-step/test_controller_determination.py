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

    def test_unresolved_record_is_fail_closed(self):
        c = self.contract
        self.assertEqual(c["schema_version"], "eucons.ai4work_controller_determination.v0.2")
        self.assertEqual(c["status"], "UNRESOLVED_BEFORE_COLLECTION")
        self.assertIsNone(c["controller"])
        self.assertEqual(c["joint_controller_assessment"], "PENDING_AUTHORITY_CONFIRMATION")
        self.assertFalse(c["approved"])
        self.assertFalse(c["collection_enabled"])
        self.assertFalse(c["nf06_reference_eligible"])
        self.assertFalse(c["merge_authorized"])
        self.assertFalse(c["deploy_authorized"])

    def test_nondeterminative_facts_are_explicit(self):
        expected = {
            "website_branding",
            "project_leader_status",
            "domain_ownership",
            "hosting_billing",
            "technical_implementation",
        }
        self.assertEqual(set(self.contract["non_determinative_facts"]), expected)

    def test_verified_role_identities_are_bound_but_not_promoted_to_controller(self):
        matrix = {row["entity_reference"]: row for row in self.contract["decision_matrix"]}
        leader = matrix["MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE"]
        hosting = matrix["HOSTING_ACCOUNT_HOLDER_PRIVATE_CONTROLLED_REFERENCE"]

        self.assertEqual(leader["observed_legal_identity"], "FUNDAŢIA CENTRUL DE PREGĂTIRE PROFESIONALĂ VÂLCEA")
        self.assertEqual(leader["identity_status"], "VERIFIED_CURRENT_MYSMIS")
        self.assertEqual(hosting["observed_legal_identity"], "FUNDAȚIA ANTREPRENORIAT SOCIAL")
        self.assertEqual(hosting["identity_status"], "VERIFIED_FIRST_PARTY_PROVIDER_CORRESPONDENCE_2026_03_20")
        self.assertNotEqual(leader["observed_legal_identity"], hosting["observed_legal_identity"])

        for row in (leader, hosting):
            self.assertIsNone(row["purpose_decision_authority"])
            self.assertIsNone(row["essential_means_authority"])
            self.assertIsNone(row["access_to_respondent_level_data"])
            self.assertIsNone(row["processor_instruction_authority"])
            self.assertIsNone(row["proposed_role"])

        self.assertIsNone(self.contract["controller"])
        self.assertFalse(self.contract["approved"])

    def test_disavowed_role_outreach_is_never_treated_as_active_evidence(self):
        c = self.contract
        contact = c["external_contact_state"]
        self.assertEqual(contact["status"], "HOLD_WITHDRAWN_REQUESTS_NO_ACTIVE_AUTHORITY_REQUEST")
        self.assertEqual(contact["project_leader_role_request"], "WITHDRAWN_BY_AUTHENTICATED_USER_2026_08_28")
        self.assertEqual(contact["hosting_account_holder_role_request"], "WITHDRAWN_BY_AUTHENTICATED_USER_2026_08_28")
        self.assertIn("cannot satisfy", contact["evidence_rule"].lower())

        authority = c["known_evidence_boundaries"]["authority_request"].lower()
        for phrase in ("disavowed", "request_withdrawn", "not active evidentiary requests", "must not be treated as controller approval"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, authority)

        matrix = {row["entity_reference"]: row for row in c["decision_matrix"]}
        self.assertIn("WITHDRAWN", matrix["MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE"]["legal_binding_reference"])
        self.assertNotIn("REPLY_PENDING", matrix["MYSMIS_PROJECT_LEADER_CONTROLLED_REFERENCE"]["legal_binding_reference"])
        self.assertIn("WITHDRAWN", matrix["HOSTING_ACCOUNT_HOLDER_PRIVATE_CONTROLLED_REFERENCE"]["legal_binding_reference"])

    def test_provider_documentary_package_is_closed_but_account_binding_stays_open(self):
        c = self.contract
        provider_boundary = c["known_evidence_boundaries"]["hosting_provider"].lower()
        self.assertIn("dpa v1.0 plus annex 4 and annex 5", provider_boundary)
        self.assertIn("documentary annex 4/5", provider_boundary)
        self.assertIn("closed", provider_boundary)
        self.assertIn("account-specific cpanel raw access retention/access", provider_boundary)
        self.assertIn("provider-bound deletion/backup", provider_boundary)

        matrix = {row["entity_reference"]: row for row in c["decision_matrix"]}
        provider = matrix["CLAUS_WEB_SRL"]
        self.assertEqual(provider["identity_status"], "VERIFIED_FIRST_PARTY_SHARED_HOSTING_DPA_ANNEX4_ANNEX5_2026_08_28")
        self.assertEqual(provider["status"], "ACCOUNT_CONFIGURATION_AND_BINDING_REQUIRED")
        self.assertFalse(provider["purpose_decision_authority"])
        self.assertFalse(provider["processor_instruction_authority"])

    def test_remaining_decision_facts_cover_actual_controller_authority(self):
        remaining = "\n".join(self.contract["remaining_decision_facts"]).lower()
        for phrase in (
            "research purpose",
            "questionnaire content",
            "lawful basis",
            "respondent-level",
            "provider chain",
            "jointly determines",
            "privacy contact",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, remaining)

    def test_required_role_evidence_is_not_silently_skipped(self):
        required = "\n".join(self.contract["required_evidence_before_decision"]).lower()
        for phrase in (
            "authority record",
            "hosting account holder",
            "processor/subprocessor",
            "annex 4/5",
            "logging",
            "deletion/backup",
            "joint-controller",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, required)

    def test_public_artifact_excludes_private_hosting_account_identifiers(self):
        rendered = json.dumps(self.contract, ensure_ascii=False).lower()
        self.assertIn("hosting_account_holder_private_controlled_reference", rendered)
        self.assertIn("private billing", self.contract["privacy_boundary"].lower())
        for forbidden in ("client id", "cod client", "invoice number", "password"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_nf06_reference_requires_frozen_controller_determination(self):
        approvals = "\n".join(self.contract["approval_requirements"]).lower()
        self.assertIn("nf06 collection frame cites the frozen controller-determination record", approvals)

    def test_frozen_forms_do_not_hardcode_unproven_controller(self):
        notice = self.forms.get("common_notice") or {}
        self.assertEqual(notice.get("operator_status"), "UNRESOLVED_BEFORE_COLLECTION")
        self.assertIsNone(notice.get("operator"))
        rendered = json.dumps(self.forms, ensure_ascii=False)
        self.assertNotIn("EUROCONSULT SRL (CUI 14250864)", rendered)
        self.assertNotIn("FUNDAŢIA CENTRUL DE PREGĂTIRE PROFESIONALĂ VÂLCEA", rendered)
        self.assertNotIn("FUNDAȚIA ANTREPRENORIAT SOCIAL", rendered)


if __name__ == "__main__":
    unittest.main()
