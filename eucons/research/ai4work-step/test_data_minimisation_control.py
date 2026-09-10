from __future__ import annotations

import json
import unittest
from pathlib import Path

from data_minimisation_control import PRIMARY, ROOT, validate


class DataMinimisationControlTests(unittest.TestCase):
    def test_current_forms_are_fully_purpose_mapped_and_fail_closed(self) -> None:
        result = validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["classification"], "CONTROL_ONLY_NOT_EVIDENCE")
        self.assertEqual(result["total_fields"], 32)
        self.assertEqual(result["primary_rank_fields"], PRIMARY)
        self.assertTrue(result["all_fields_single_purpose_mapped"])
        self.assertFalse(result["free_text_present"])
        self.assertFalse(result["crm_linkage_allowed"])
        self.assertFalse(result["marketing_use_allowed"])
        self.assertFalse(result["test_twin_evidence_eligible"])
        self.assertFalse(result["collection_enabled"])

    def test_every_current_field_occurs_exactly_once_in_purpose_map(self) -> None:
        forms = json.loads((ROOT / "forms_definition.json").read_text(encoding="utf-8"))
        control = json.loads((ROOT / "GDPR_DATA_MINIMISATION_CONTROL.json").read_text(encoding="utf-8"))
        expected = {}
        for form in forms["forms"]:
            expected[form["id"]] = {
                field["id"] for section in ("profile", "questions") for field in form[section]
            }
        seen = {}
        for group in control["purpose_groups"]:
            for form_id, field_ids in group["fields"].items():
                for field_id in field_ids:
                    key = (form_id, field_id)
                    seen[key] = seen.get(key, 0) + 1
        for form_id, field_ids in expected.items():
            for field_id in field_ids:
                self.assertEqual(seen.get((form_id, field_id)), 1, f"purpose mapping drift: {form_id}:{field_id}")

    def test_no_free_text_or_direct_contact_capture_exists_in_reviewed_forms(self) -> None:
        forms = json.loads((ROOT / "forms_definition.json").read_text(encoding="utf-8"))
        for form in forms["forms"]:
            for section in ("profile", "questions"):
                for field in form[section]:
                    self.assertNotIn(field["type"], {"text", "textarea"})
                    self.assertNotIn(field["id"].lower(), {"name", "email", "phone", "address", "cnp", "cui"})
        employer = next(form for form in forms["forms"] if form["id"] == "AI4WORK_EMPLOYERS_V1")
        e10 = next(field for field in employer["questions"] if field["id"] == "E10")
        self.assertIn("Nu se colectează date de contact", e10.get("note", ""))

    def test_only_q10_and_e03_are_numeric_rank_inputs(self) -> None:
        control = json.loads((ROOT / "GDPR_DATA_MINIMISATION_CONTROL.json").read_text(encoding="utf-8"))
        numeric = {}
        for group in control["purpose_groups"]:
            if group["numeric_h1_h5_rank"] is True:
                for form_id, fields in group["fields"].items():
                    numeric.setdefault(form_id, []).extend(fields)
        self.assertEqual(numeric, {
            "AI4WORK_ADULTS_V1": ["Q10"],
            "AI4WORK_EMPLOYERS_V1": ["E03"],
        })


if __name__ == "__main__":
    unittest.main()
