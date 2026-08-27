from __future__ import annotations

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class ControllerDeterminationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((HERE / "CONTROLLER_DETERMINATION_DRAFT.json").read_text(encoding="utf-8"))

    def test_unresolved_record_is_fail_closed(self):
        c = self.contract
        self.assertEqual(c["status"], "UNRESOLVED_BEFORE_COLLECTION")
        self.assertIsNone(c["controller"])
        self.assertEqual(c["joint_controller_assessment"], "PENDING_FACTS")
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

    def test_required_role_evidence_is_not_silently_skipped(self):
        required = "\n".join(self.contract["required_evidence_before_decision"]).lower()
        for phrase in (
            "research purpose",
            "questionnaire content",
            "lawful basis",
            "hosting-account holder",
            "processor/subprocessor",
            "joint-controller",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, required)

    def test_public_artifact_uses_controlled_reference_for_private_hosting_identity(self):
        rendered = json.dumps(self.contract, ensure_ascii=False)
        self.assertIn("HOSTING_ACCOUNT_HOLDER_PRIVATE_CONTROLLED_REFERENCE", rendered)
        self.assertIn("private billing", self.contract["privacy_boundary"].lower())

    def test_nf06_reference_requires_frozen_controller_determination(self):
        approvals = "\n".join(self.contract["approval_requirements"]).lower()
        self.assertIn("nf06 collection frame cites the frozen controller-determination record", approvals)


if __name__ == "__main__":
    unittest.main()
