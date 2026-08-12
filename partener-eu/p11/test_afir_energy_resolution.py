#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from opportunity_contract import validate_bundle  # noqa: E402


class AfirEnergyResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((HERE / "opportunity_bundle.json").read_text(encoding="utf-8"))
        cls.opportunity = next(x for x in cls.bundle["opportunities"] if x["opportunity_id"] == "afir-energy-2026")
        cls.task = next(x for x in cls.bundle["resolution_tasks"] if x["opportunity_id"] == "afir-energy-2026")

    def test_canonical_bundle_remains_valid(self):
        self.assertEqual(validate_bundle(self.bundle), {"opportunities": 6, "evidence": 10, "changesets": 1, "resolution_tasks": 6})

    def test_resolved_material_facts_match_guide_v7(self):
        facts = self.opportunity["material_facts"]
        self.assertEqual(facts["budget"]["session_total_eur"], 265_000_000)
        self.assertEqual(facts["grant"]["cap_eur_per_mw_le_1mw"], 650_000)
        self.assertEqual(facts["grant"]["cap_eur_per_mw_gt_1mw"], 550_000)
        self.assertEqual(facts["grant"]["cap_eur_per_beneficiary"], 20_000_000)
        self.assertEqual(facts["scoring"]["maximum_points"], 100)
        self.assertEqual([x["maximum_points"] for x in facts["scoring"]["criteria"]], [70, 10, 10, 10])
        self.assertEqual(len(facts["beneficiaries"]), 3)

    def test_eligibility_remains_unknown_and_blocked(self):
        self.assertEqual(self.opportunity["candidate_material_facts"], {"eligibility": "UNKNOWN_PENDING_FULL_CUMULATIVE_RULE_NORMALIZATION"})
        self.assertEqual(self.task["status"], "IN_REVIEW")
        self.assertEqual(self.task["blocked_fact_classes"], ["eligibility"])
        self.assertEqual(self.opportunity["publication_state"], "REVIEW_REQUIRED")

    def test_no_date_only_or_automatic_publication(self):
        self.assertEqual(self.opportunity["material_facts"]["deadline"]["time_of_day"], "UNKNOWN")
        self.assertFalse(self.opportunity["automatic_material_fact_update_allowed"])
        changeset = next(x for x in self.bundle["changesets"] if x["opportunity_id"] == "afir-energy-2026")
        self.assertFalse(changeset["automatic_publish_allowed"])

    def test_semantic_hashes_cover_the_recorded_assertions(self):
        rows = [x for x in self.bundle["evidence"] if x["evidence_id"].startswith("EV-AFIR-ENERGY-2026-")]
        for row in rows:
            digest = hashlib.sha256(row["semantic_assertion"].encode("utf-8")).hexdigest()
            self.assertEqual(row["semantic_sha256"], digest)


if __name__ == "__main__":
    unittest.main()
