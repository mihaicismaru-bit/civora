#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from opportunity_contract import ContractViolation, validate_bundle  # noqa: E402
from validate_corpus import public_opportunity_ids  # noqa: E402


class CanonicalCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))

    def test_all_public_records_are_normalized_once(self):
        canonical = [x["opportunity_id"] for x in self.bundle["opportunities"]]
        self.assertEqual(canonical, public_opportunity_ids())
        self.assertEqual(len(set(canonical)), 6)

    def test_bundle_passes_contract(self):
        self.assertEqual(validate_bundle(self.bundle), {"opportunities": 6, "evidence": 10, "changesets": 1, "resolution_tasks": 6})

    def test_expired_regional_consultation_remains_fail_closed(self):
        opportunity = next(x for x in self.bundle["opportunities"] if x["opportunity_id"] == "pr-centru-digital-2")
        self.assertEqual(opportunity["status"], "DISCOVERED")
        self.assertEqual(opportunity["material_facts"], {})
        self.assertEqual(opportunity["candidate_material_facts"]["status"]["value"], "UNKNOWN")
        task = next(x for x in self.bundle["resolution_tasks"] if x["opportunity_id"] == "pr-centru-digital-2")
        self.assertEqual(task["status"], "IN_REVIEW")
        self.assertIn("status", task["blocked_fact_classes"])

    def test_resolutions_have_no_automatic_publication_effect(self):
        self.assertTrue(all(x["publication_state"] == "REVIEW_REQUIRED" for x in self.bundle["opportunities"]))
        self.assertTrue(all(x["automatic_publish_allowed"] is False for x in self.bundle["changesets"]))

    def test_candidate_fact_without_resolution_block_is_rejected(self):
        bundle = json.loads(json.dumps(self.bundle))
        task = next(x for x in bundle["resolution_tasks"] if len(x["blocked_fact_classes"]) > 1)
        task["blocked_fact_classes"].remove(task["blocked_fact_classes"][0])
        with self.assertRaisesRegex(ContractViolation, "candidate facts lack open ResolutionTask"):
            validate_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
