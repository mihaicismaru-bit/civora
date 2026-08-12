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

    def test_all_five_public_records_are_normalized_once(self):
        canonical = [x["opportunity_id"] for x in self.bundle["opportunities"]]
        self.assertEqual(canonical, public_opportunity_ids())
        self.assertEqual(len(set(canonical)), 5)

    def test_bundle_passes_contract(self):
        self.assertEqual(validate_bundle(self.bundle), {"opportunities": 5, "evidence": 5, "changesets": 0, "resolution_tasks": 5})

    def test_normalization_has_no_publication_effect(self):
        self.assertTrue(all(x["publication_state"] == "REVIEW_REQUIRED" for x in self.bundle["opportunities"]))
        self.assertEqual(self.bundle["changesets"], [])

    def test_candidate_fact_without_resolution_block_is_rejected(self):
        bundle = json.loads(json.dumps(self.bundle))
        bundle["resolution_tasks"][0]["blocked_fact_classes"].remove("budget")
        with self.assertRaisesRegex(ContractViolation, "candidate facts lack open ResolutionTask"):
            validate_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
