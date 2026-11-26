from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_research_pages import build


HERE = Path(__file__).resolve().parent


class DirectIdentifierSurfaceControlTests(unittest.TestCase):
    def test_analytical_contract_forbids_direct_identifiers_and_crm_linkage(self) -> None:
        contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))

        forbidden = set(contract.get("direct_identifiers_forbidden") or [])
        required_forbidden = {
            "name",
            "surname",
            "cnp",
            "exact_address",
            "phone",
            "email",
            "employer_name",
            "organisation_name",
            "cui",
        }
        self.assertTrue(required_forbidden.issubset(forbidden))
        self.assertEqual(contract.get("crm_integration"), "FORBIDDEN")
        self.assertEqual(contract.get("commercial_analytics"), "FORBIDDEN")
        self.assertFalse(contract.get("tracking", {}).get("analytics_default"))

        separation = contract.get("separation_rules") or {}
        self.assertEqual(separation.get("analytical_responses_store"), "RESEARCH_ANALYTICS_ONLY")
        self.assertEqual(separation.get("optional_contact_store"), "RESEARCH_CONTACT_SEPARATE")
        self.assertIsNone(separation.get("link_key_between_response_and_contact"))
        self.assertEqual(separation.get("commercial_lead_store"), "NOT_USED")
        self.assertEqual(separation.get("eucons_leads_forms_json"), "MUST_NOT_BE_REUSED")

    def test_optional_contact_route_is_not_built_into_ai4work_analytical_surface(self) -> None:
        contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        optional_contact = str((contract.get("public_routes") or {}).get("optional_contact") or "").strip()
        self.assertTrue(optional_contact, "contract must make any future contact surface explicit")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = build(target)
            self.assertFalse(result["production_enabled"])
            self.assertEqual(result["status"], "PASS_FAIL_CLOSED")

            generated_pages = sorted(target.rglob("index.html"))
            self.assertEqual(len(generated_pages), 3)
            contact_page = target / optional_contact.strip("/") / "index.html"
            self.assertFalse(
                contact_page.exists(),
                "direct-identifier/contact collection must not be generated as part of the analytical research surface",
            )

    def test_employer_follow_up_answer_cannot_collect_contact_details(self) -> None:
        contract = json.loads((HERE / "form_contract.json").read_text(encoding="utf-8"))
        employer = contract.get("employer_form") or {}
        self.assertEqual(employer.get("free_text_fields"), [])
        rule = str(employer.get("contact_rule") or "").lower()
        self.assertIn("only yes/possible/no", rule)
        self.assertIn("separately approved", rule)
        self.assertIn("no such direct-identifier collection is enabled", rule)


if __name__ == "__main__":
    unittest.main()
