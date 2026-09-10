from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def flatten_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_strings(child)
    elif isinstance(value, str):
        yield value


class ScientificResearchClassificationControlTests(unittest.TestCase):
    def test_special_scientific_research_rules_are_not_claimed_by_default(self):
        control = load_json("GDPR_SCIENTIFIC_RESEARCH_CLASSIFICATION_CONTROL.json")
        classification = control["legal_classification"]

        self.assertEqual(control["evidence_class"], "CONTROL_ARTIFACT_NOT_EVIDENCE")
        self.assertEqual(control["status"], "NO_SCIENTIFIC_RESEARCH_SPECIAL_RULES_CLAIMED")
        self.assertFalse(control["collection_enabled"])
        self.assertEqual(classification["scientific_research_status"], "NOT_ASSERTED")
        self.assertFalse(classification["article_89_special_derogation_reliance"])
        self.assertFalse(classification["scientific_research_further_processing_compatibility_reliance"])
        self.assertFalse(classification["scientific_research_rights_limitation_reliance"])
        self.assertFalse(control["current_ai4work_control_position"]["special_research_privileges_needed_for_current_design"])
        self.assertEqual(
            control["change_control"]["default_if_missing"],
            "FAIL_CLOSED_NO_SPECIAL_SCIENTIFIC_RESEARCH_RELIANCE",
        )
        self.assertEqual(control["test_twin"]["classification"], "TEST_TWIN_NON_EVIDENCE")

    def test_guidance_factors_and_separate_approval_path_are_frozen(self):
        control = load_json("GDPR_SCIENTIFIC_RESEARCH_CLASSIFICATION_CONTROL.json")
        guidance = control["edpb_guidance_context"]
        self.assertEqual(guidance["reference"], "EDPB Guidelines 1/2026 on processing of personal data for scientific research purposes")
        self.assertEqual(guidance["adoption_date"], "2026-04-15")
        self.assertEqual(guidance["consultation_closed"], "2026-06-25")
        self.assertEqual(len(guidance["indicative_factors"]), 6)
        self.assertIn("methodical and systematic approach", guidance["indicative_factors"])
        self.assertIn("autonomy and independence", guidance["indicative_factors"])
        required = control["change_control"]["required_before_change"]
        self.assertTrue(any("controller" in item.lower() for item in required))
        self.assertTrue(any("six indicative" in item.lower() for item in required))
        self.assertTrue(any("exact legal provision" in item.lower() for item in required))
        self.assertTrue(any("sha-256" in item.lower() for item in required))

    def test_approved_lia_and_rights_policy_do_not_silently_claim_article_89_privileges(self):
        lia = load_json("GDPR_LIA_DRAFT.json")
        rights = load_json("GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json")
        control = load_json("GDPR_SCIENTIFIC_RESEARCH_CLASSIFICATION_CONTROL.json")

        self.assertIn("Article 6(1)(f)", lia["candidate_legal_basis"])
        self.assertTrue(lia["controller_signoff_fields"]["approved"])
        self.assertFalse(lia["prod_eligible"])
        self.assertFalse(lia["collection_enabled"])
        self.assertTrue(rights["controller_policy_acceptance"]["approved"])
        self.assertFalse(rights["controller_approval"])
        self.assertFalse(rights["collection_enabled"])
        self.assertFalse(control["legal_classification"]["article_89_special_derogation_reliance"])
        self.assertFalse(control["legal_classification"]["scientific_research_rights_limitation_reliance"])

        ordinary_rights_text = "\n".join(flatten_strings(rights)).lower()
        self.assertNotIn("article 89", ordinary_rights_text)
        self.assertNotIn("scientific research derogation", ordinary_rights_text)


if __name__ == "__main__":
    unittest.main()
