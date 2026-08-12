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
        cls.batch = json.loads((ROOT / "admission_batch_01.json").read_text(encoding="utf-8"))

    def test_all_public_records_are_normalized_once(self):
        canonical = [x["opportunity_id"] for x in self.bundle["opportunities"]]
        public = public_opportunity_ids(self.bundle)
        self.assertEqual(canonical[: len(public)], public)
        self.assertEqual(canonical[len(public) :], self.batch["opportunity_ids"])
        self.assertEqual(len(canonical), len(set(canonical)))

    def test_bundle_passes_contract(self):
        self.assertEqual(validate_bundle(self.bundle), {"opportunities": 11, "evidence": 11, "changesets": 0, "resolution_tasks": 11})

    def test_normalization_has_no_publication_effect(self):
        self.assertTrue(all(x["publication_state"] == "REVIEW_REQUIRED" for x in self.bundle["opportunities"]))
        self.assertEqual(self.bundle["changesets"], [])

    def test_candidate_fact_without_resolution_block_is_rejected(self):
        bundle = json.loads(json.dumps(self.bundle))
        bundle["resolution_tasks"][0]["blocked_fact_classes"].remove("budget")
        with self.assertRaisesRegex(ContractViolation, "candidate facts lack open ResolutionTask"):
            validate_bundle(bundle)

    def test_admitted_batch_is_semantically_unresolved(self):
        opportunities = {x["opportunity_id"]: x for x in self.bundle["opportunities"]}
        evidence = {x["evidence_id"]: x for x in self.bundle["evidence"]}
        for opportunity_id in self.batch["opportunity_ids"]:
            item = opportunities[opportunity_id]
            self.assertEqual(item["status"], "DISCOVERED")
            self.assertEqual(item["material_facts"], {})
            self.assertTrue(all(evidence[ref]["semantic_verdict"] == "UNRESOLVED" for ref in item["evidence_refs"]))
            self.assertTrue(all(evidence[ref]["supports_fact_classes"] == [] for ref in item["evidence_refs"]))

    def test_admitted_batch_has_no_publication_authority(self):
        self.assertFalse(self.batch["publication_allowed"])
        self.assertFalse(self.batch["automatic_material_fact_update_allowed"])
        self.assertEqual(self.batch["material_fact_action"], "NONE")


if __name__ == "__main__":
    unittest.main()
