from __future__ import annotations

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
EUCONS = HERE.parents[1]


class RightsRequestAuthenticationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(
            (HERE / "RIGHTS_REQUEST_AUTHENTICATION_CONTRACT_2026-09-03.json").read_text(
                encoding="utf-8"
            )
        )
        self.article15 = json.loads(
            (HERE / "ARTICLE15_CONTEXT_RESPONSE_TEMPLATE_2026-09-03.json").read_text(
                encoding="utf-8"
            )
        )
        self.procedure = json.loads(
            (HERE / "GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json").read_text(
                encoding="utf-8"
            )
        )
        self.client = (HERE / "research_form.js").read_text(encoding="utf-8")
        self.php = (EUCONS / "runtime" / "php" / "src" / "ResearchRightsAuth.php").read_text(
            encoding="utf-8"
        )

    def test_two_part_proof_is_bound_without_identity_registry(self):
        self.assertEqual(
            self.contract["status"],
            "IMPLEMENTED_CANDIDATE_PROVIDER_BOUND_VALIDATION_REQUIRED",
        )
        self.assertFalse(self.contract["minimisation"]["new_direct_identifier_collected"])
        self.assertFalse(self.contract["minimisation"]["identity_registry_created"])
        self.assertEqual(self.contract["minimisation"]["crm_lookup"], "FORBIDDEN")
        self.assertEqual(self.contract["minimisation"]["ip_lookup"], "FORBIDDEN")
        self.assertEqual(
            self.contract["minimisation"]["private_code_in_analytical_store"],
            "FORBIDDEN",
        )
        self.assertEqual(
            self.contract["minimisation"]["private_code_persistent_browser_storage"],
            "FORBIDDEN",
        )
        self.assertEqual(
            self.contract["test_twin"]["classification"],
            "TEST_TWIN_NON_EVIDENCE",
        )
        self.assertFalse(self.contract["test_twin"]["prod_promotion_eligible"])
        self.assertFalse(self.contract["collection_enabled"])
        self.assertFalse(self.contract["deploy_authorized"])

    def test_browser_shows_private_code_only_after_accepted_submission_without_persistence(self):
        accepted_index = self.client.index("if (!response.ok || result.accepted !== true)")
        receipt_index = self.client.index("Cod privat de verificare: ${idempotencyKey}")
        self.assertGreater(receipt_index, accepted_index)
        for forbidden in ("localStorage", "sessionStorage", "document.cookie"):
            self.assertNotIn(forbidden, self.client)
        self.assertIn('credentials: "omit"', self.client)
        self.assertIn('referrerPolicy: "no-referrer"', self.client)

    def test_php_verifier_uses_constant_time_match_and_no_logging(self):
        self.assertIn("hash_equals", self.php)
        self.assertIn("INVALID_RIGHTS_PRIVATE_CODE", self.php)
        self.assertIn("AI4WORK_ADULTS_V1", self.php)
        self.assertIn("AI4WORK_EMPLOYERS_V1", self.php)
        self.assertNotIn("error_log", self.php)
        self.assertNotIn("CRM", self.php.upper().replace("CREATING AN IDENTITY REGISTRY OR CONSULTING CRM/IP/DEVICE DATA", ""))

    def test_procedure_binds_auth_and_article15_context_but_stays_fail_closed(self):
        operations = self.procedure["research_store_operations"]
        self.assertEqual(
            operations["access_requester_authentication_reference_adapter"],
            "TWO_PART_OPAQUE_PROOF_RESPONSE_ID_PLUS_PRIVATE_UUIDV4_NO_IDENTITY_REGISTRY",
        )
        self.assertEqual(
            operations["access_controller_context_template"],
            "ARTICLE15_CONTEXT_RESPONSE_TEMPLATE_2026-09-03.json",
        )
        self.assertEqual(self.procedure["request_channel"]["privacy_contact"], "privacy@eucons.ro")
        self.assertFalse(self.procedure["controller_approval"])
        self.assertFalse(self.procedure["collection_enabled"])

    def test_article15_template_is_complete_candidate_not_prod_claim(self):
        context = self.article15["article15_context"]
        for key in (
            "processing_purposes",
            "categories_of_personal_data",
            "recipients_or_categories",
            "retention",
            "rights",
            "complaint",
            "source",
            "automated_decision_making",
            "international_transfer",
        ):
            self.assertTrue(context[key])
        self.assertEqual(
            self.article15["status"],
            "IMPLEMENTED_CANDIDATE_LIVE_BINDING_REQUIRED",
        )
        self.assertFalse(self.article15["collection_enabled"])
        self.assertFalse(self.article15["deploy_authorized"])


if __name__ == "__main__":
    unittest.main()
