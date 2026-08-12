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
        cls.batches = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(ROOT.glob("admission_batch_*.json"))]
        cls.admitted_ids = [opportunity_id for batch in cls.batches for opportunity_id in batch["opportunity_ids"]]

    def test_all_public_records_are_normalized_once(self):
        canonical = [x["opportunity_id"] for x in self.bundle["opportunities"]]
        public = public_opportunity_ids(self.bundle)
        self.assertEqual(canonical[: len(public)], public)
        self.assertEqual(canonical[len(public) :], self.admitted_ids)
        self.assertEqual(len(canonical), len(set(canonical)))

    def test_bundle_passes_contract(self):
        self.assertEqual(validate_bundle(self.bundle), {"opportunities": 16, "evidence": 16, "changesets": 0, "resolution_tasks": 16})

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
        for opportunity_id in self.admitted_ids:
            item = opportunities[opportunity_id]
            self.assertEqual(item["status"], "DISCOVERED")
            self.assertEqual(item["material_facts"], {})
            self.assertTrue(all(evidence[ref]["semantic_verdict"] == "UNRESOLVED" for ref in item["evidence_refs"]))
            self.assertTrue(all(evidence[ref]["supports_fact_classes"] == [] for ref in item["evidence_refs"]))

    def test_admitted_batch_has_no_publication_authority(self):
        for batch in self.batches:
            self.assertFalse(batch["publication_allowed"])
            self.assertFalse(batch["automatic_material_fact_update_allowed"])
            self.assertEqual(batch["material_fact_action"], "NONE")

    def test_batches_are_disjoint_and_fixed_size(self):
        self.assertTrue(all(len(batch["opportunity_ids"]) == 5 for batch in self.batches))
        self.assertEqual(len(self.admitted_ids), len(set(self.admitted_ids)))


if __name__ == "__main__":
    unittest.main()
