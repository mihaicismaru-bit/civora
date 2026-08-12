#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from opportunity_contract import validate_bundle  # noqa: E402


class PrCentruDigital2ResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = HERE / "resolutions" / "pr_centru_digital2_resolution.json"
        cls.bundle = json.loads(path.read_text(encoding="utf-8"))

    def test_resolution_bundle_satisfies_contract(self):
        self.assertEqual(validate_bundle(self.bundle), {
            "opportunities": 1,
            "evidence": 2,
            "changesets": 0,
            "resolution_tasks": 1,
        })

    def test_temporally_stale_consultation_is_not_materialized(self):
        opportunity = self.bundle["opportunities"][0]
        self.assertEqual(opportunity["status"], "DISCOVERED")
        self.assertEqual(opportunity["material_facts"], {})
        self.assertEqual(opportunity["fact_evidence"], {})
        self.assertEqual(opportunity["candidate_material_facts"]["status"]["value"], "UNKNOWN")

    def test_all_material_classes_remain_blocked(self):
        task = self.bundle["resolution_tasks"][0]
        self.assertEqual(task["status"], "IN_REVIEW")
        self.assertEqual(set(task["blocked_fact_classes"]), {
            "status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"
        })

    def test_consultation_documents_are_not_admitted_as_final(self):
        self.assertTrue(all(row["semantic_verdict"] == "UNRESOLVED" for row in self.bundle["evidence"]))
        self.assertFalse(self.bundle["opportunities"][0]["automatic_material_fact_update_allowed"])


if __name__ == "__main__":
    unittest.main()
