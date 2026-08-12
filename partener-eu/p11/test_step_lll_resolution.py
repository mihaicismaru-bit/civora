#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from opportunity_contract import validate_bundle  # noqa: E402


class StepLllResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = HERE / "resolutions" / "step_lll_resolution.json"
        cls.bundle = json.loads(path.read_text(encoding="utf-8"))

    def test_resolution_bundle_satisfies_contract(self):
        counts = validate_bundle(self.bundle)
        self.assertEqual(counts, {
            "opportunities": 1,
            "evidence": 3,
            "changesets": 1,
            "resolution_tasks": 1,
        })

    def test_only_resolved_material_facts_are_projected(self):
        opportunity = self.bundle["opportunities"][0]
        self.assertEqual(set(opportunity["fact_evidence"]), {"status", "deadline"})
        self.assertEqual(opportunity["status"], "OPEN")
        self.assertEqual(opportunity["deadline_at"], "2026-09-30T16:00:00+03:00")

    def test_no_automatic_material_fact_update(self):
        self.assertFalse(self.bundle["policy"]["automatic_material_fact_update_allowed"])
        self.assertFalse(self.bundle["opportunities"][0]["automatic_material_fact_update_allowed"])
        self.assertFalse(self.bundle["changesets"][0]["automatic_publish_allowed"])
        self.assertFalse(self.bundle["resolution_tasks"][0]["automatic_material_fact_update_allowed"])

    def test_consultation_and_original_deadline_are_not_current(self):
        changes = self.bundle["changesets"][0]["changes"]
        by_class = {item["fact_class"]: item for item in changes}
        self.assertEqual(by_class["status"]["after"], "OPEN")
        self.assertEqual(by_class["deadline"]["after"], "2026-09-30T16:00:00+03:00")
        self.assertNotEqual(by_class["deadline"]["before"], by_class["deadline"]["after"])


if __name__ == "__main__":
    unittest.main()
