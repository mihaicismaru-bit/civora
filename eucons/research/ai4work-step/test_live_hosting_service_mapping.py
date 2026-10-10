from __future__ import annotations

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class LiveHostingServiceMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads((HERE / "LIVE_HOSTING_SERVICE_MAPPING_DRAFT.json").read_text(encoding="utf-8"))

    def test_provider_and_service_family_are_frozen_without_enabling_collection(self):
        m = self.mapping
        self.assertEqual(m["schema_version"], "eucons.ai4work_live_hosting_service_mapping.v0.1")
        self.assertEqual(m["status"], "FROZEN_FIRST_PARTY_SERVICE_MAPPING_ACCOUNT_CONFIGURATION_OPEN")
        self.assertEqual(m["provider"], "CLAUS WEB SRL")
        self.assertEqual(m["service_family"], "Shared Hosting / cPanel")
        self.assertFalse(m["collection_enabled"])
        self.assertFalse(m["merge_authorized"])
        self.assertFalse(m["deploy_authorized"])
        self.assertFalse(m["real_collection_authorized"])

    def test_mapping_does_not_overclaim_account_configuration_or_gdpr_roles(self):
        open_facts = "\n".join(self.mapping["remaining_open_facts"]).lower()
        for phrase in (
            "raw access archive",
            "raw access retention",
            "authorised log",
            "controller-to-provider instruction chain",
            "active subprocessor",
            "annex 5 override",
            "research-only production store",
            "deletion/backup",
            "test twin",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, open_facts)
        rule = self.mapping["prod_gate_rule"].lower()
        self.assertIn("closes only the live provider/service-family mapping", rule)
        self.assertIn("cannot satisfy", rule)

    def test_first_party_evidence_boundaries_are_explicit(self):
        rows = self.mapping["first_party_evidence"]
        self.assertGreaterEqual(len(rows), 3)
        rendered = "\n".join((row["observed_fact"] + " " + row["boundary"]).lower() for row in rows)
        self.assertIn("provider/service association", rendered)
        self.assertIn("billing/customer identity is not treated as controller", rendered)
        self.assertIn("does not prove the current account-specific", rendered)

    def test_artifact_does_not_embed_private_account_identifiers(self):
        rendered = json.dumps(self.mapping, ensure_ascii=False).lower()
        for forbidden in (
            "client id",
            "cod client",
            "proforma=",
            "password",
            "cpanel username",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_test_twin_is_permanently_non_evidence(self):
        self.assertEqual(
            self.mapping["test_twin_policy"],
            "TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE",
        )


if __name__ == "__main__":
    unittest.main()
