from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / "GDPR_ANONYMISATION_CLASSIFICATION_CONTROL.json"
NOTICE = ROOT / "RESEARCH_PRIVACY_NOTICE_DRAFT.md"


class AnonymisationClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(CONTROL.read_text(encoding="utf-8"))

    def test_raw_responses_are_not_declared_anonymous(self) -> None:
        policy = self.data["classification_policy"]
        self.assertEqual(
            policy["raw_and_normalised_respondent_records"],
            "PERSONAL_OR_POTENTIALLY_LINKABLE_DATA_FOR_GDPR_COMPLIANCE",
        )
        self.assertEqual(
            policy["direct_identifier_absence_claim"],
            "DE_IDENTIFIED_BY_DESIGN_NOT_ANONYMOUS_BY_ASSERTION",
        )
        self.assertFalse(self.data["current_ai4work_position"]["raw_anonymity_claim_relied_on_for_prod"])
        self.assertFalse(self.data["collection_enabled"])

    def test_output_anonymity_requires_three_edpb_criteria(self) -> None:
        output = self.data["output_anonymity_test"]
        self.assertEqual(
            output["required_criteria"],
            ["NO_RECORD_ISOLATION", "NO_LINKAGE", "NO_INFERENCE"],
        )
        self.assertTrue(output["means_reasonably_likely_test"])
        self.assertIn("reported n < 5", " ".join(output["required_controls"]))
        self.assertIn("final NEEDS_ANALYSIS", " ".join(output["required_controls"]))

    def test_guidance_is_not_misrepresented_as_final(self) -> None:
        authority = self.data["authority_context"]
        self.assertEqual(authority["reference"], "EDPB Guidelines 02/2026 on Anonymisation")
        self.assertEqual(authority["version"], "1.0")
        self.assertEqual(authority["consultation_state"], "ADOPTED_VERSION_FOR_PUBLIC_CONSULTATION")
        self.assertIn("edpb.europa.eu", authority["official_url"])

    def test_notice_does_not_call_raw_responses_anonymous(self) -> None:
        notice = NOTICE.read_text(encoding="utf-8")
        self.assertIn(
            "nu înseamnă că răspunsurile brute sau normalizate sunt declarate anonime",
            notice,
        )
        self.assertIn("No Record Isolation", notice)
        self.assertIn("No Linkage", notice)
        self.assertIn("No Inference", notice)


if __name__ == "__main__":
    unittest.main()
