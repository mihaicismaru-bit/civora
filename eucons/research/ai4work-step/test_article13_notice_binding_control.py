from __future__ import annotations

import copy
import html
import json
import unittest
from pathlib import Path

from article13_notice_binding_control import (
    CONTRACT_PATH,
    SNAPSHOT_PATH,
    binding_errors,
    evaluate_repository_notice_binding,
)
from build_research_pages import render_form

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "forms_definition.json"


class Article13NoticeBindingControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_repository_draft_is_consistent_and_fail_closed(self) -> None:
        ready, errors = evaluate_repository_notice_binding()
        self.assertTrue(ready, errors)
        self.assertFalse(self.contract.get("production_enabled"))
        self.assertFalse(self.snapshot.get("approved"))
        self.assertFalse(self.snapshot.get("collection_enabled"))

    def test_surface_drift_is_rejected(self) -> None:
        changed = copy.deepcopy(self.snapshot)
        changed["surface_fields"]["retention_summary"] += " changed"
        errors = binding_errors(contract=self.contract, snapshot=changed, require_approved=False)
        self.assertIn("surface_drift:retention_summary", errors)

    def test_synthetic_snapshot_is_rejected(self) -> None:
        changed = copy.deepcopy(self.snapshot)
        changed["synthetic"] = True
        errors = binding_errors(contract=self.contract, snapshot=changed, require_approved=False)
        self.assertIn("snapshot_must_be_non_synthetic_control_artifact", errors)

    def test_prod_requires_controller_approved_non_placeholder_snapshot(self) -> None:
        errors = binding_errors(contract=self.contract, snapshot=self.snapshot, require_approved=True)
        self.assertIn("snapshot_not_approved_for_prod", errors)
        self.assertIn("snapshot_approval_false", errors)
        self.assertIn("snapshot_collection_disabled", errors)
        self.assertIn("controller_approval_missing", errors)
        self.assertIn("approved_surface_placeholder:operator_contact_details", errors)
        self.assertIn("approved_surface_placeholder:privacy_contact", errors)
        self.assertIn("approved_surface_placeholder:legal_basis", errors)

    def test_both_rendered_forms_contain_exact_bound_surface_values(self) -> None:
        by_id = {form["id"]: form for form in self.schema["forms"]}
        for form_id in ("AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"):
            rendered = render_form(by_id[form_id], self.schema, self.contract, enabled=False)
            for value in self.snapshot["surface_fields"].values():
                self.assertIn(html.escape(str(value), quote=True), rendered)


if __name__ == "__main__":
    unittest.main()
