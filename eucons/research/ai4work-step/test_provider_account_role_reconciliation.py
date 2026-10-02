from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ARTIFACT_PATH = HERE / "PROVIDER_ACCOUNT_ROLE_RECONCILIATION_DRAFT.json"
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"


class ProviderAccountRoleReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_documentary_facts_are_frozen_without_promoting_live_service_mapping(self):
        a = self.artifact
        self.assertEqual(a["schema_version"], "eucons.ai4work_provider_account_role_reconciliation.v0.1")
        self.assertEqual(a["status"], "FROZEN_DOCUMENTARY_FACTS_LIVE_SERVICE_MAPPING_OPEN")
        self.assertTrue(a["documentary_reconciliation_complete"])
        self.assertFalse(a["live_service_mapping_complete"])
        self.assertFalse(a["prod_ready"])
        self.assertFalse(a["real_collection_authorized"])

        r = a["reconciliation"]
        self.assertEqual(r["controller"], "EUROCONSULT SRL")
        self.assertEqual(r["domain_owner"], "EUROCONSULT SRL")
        self.assertEqual(r["march_2026_billing_or_restoration_account_entity"], "FUNDAȚIA ANTREPRENORIAT SOCIAL")
        self.assertIsNone(r["current_live_hosting_service_account"])
        self.assertIsNone(r["current_respondent_level_or_log_access_scope"])
        self.assertIsNone(r["current_controller_to_provider_instruction_binding"])

    def test_billing_customer_and_controller_roles_are_not_conflated(self):
        rendered = json.dumps(self.artifact, ensure_ascii=False).lower()
        self.assertIn("billing/account administration is not equivalent to domain ownership or controller status", rendered)
        self.assertIn("do not infer that fundația antreprenoriat social is a controller or joint controller", rendered)
        self.assertIn("do not infer that euroconsult srl's separate claus web customer account carries the current eucons.ro hosting service", rendered)

    def test_private_provider_identifiers_are_not_copied_into_repository_artifact(self):
        rendered = json.dumps(self.artifact, ensure_ascii=False).lower()
        for forbidden in ("client id", "password-reset link", "invoice token", "vizualizare-proforma", "schimbare-parola.html"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_manifest_binds_exact_artifact_hash_while_live_processor_chain_stays_open(self):
        evidence = self.manifest["required_external_or_operational_evidence"]
        gate = evidence["provider_account_role_reconciliation"]
        self.assertEqual(gate["status"], "FROZEN")
        self.assertEqual(gate["reference"], ARTIFACT_PATH.name)
        self.assertEqual(hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest(), gate["sha256"])
        self.assertEqual(evidence["processor_chain"]["status"], "OPEN")
        self.assertEqual(evidence["account_server_logging_binding"]["status"], "OPEN")


if __name__ == "__main__":
    unittest.main()
