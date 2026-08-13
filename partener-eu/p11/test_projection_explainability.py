#!/usr/bin/env python3
import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("projection", ROOT / "p11" / "build_public_projection.py")
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class ProjectionExplainabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.opportunity = {
            "opportunity_id": "test-call",
            "title": "Test call",
            "programme": "Test",
            "code": "T-1",
            "status": "OPEN",
            "publication_state": "PUBLISHABLE",
            "material_facts": {"status": "OPEN"},
            "fact_evidence": {"status": ["EV-1"]},
            "evidence_refs": ["EV-1"],
        }
        self.evidence = {
            "evidence_id": "EV-1",
            "semantic_verdict": "VERIFIED",
            "source_tier": "T1",
            "supports_fact_classes": ["status"],
        }

    def build(self, opportunity=None, tasks=None, evidence=None):
        return self.build_projection(opportunity, tasks, evidence)["opportunities"][0]

    def build_projection(self, opportunity=None, tasks=None, evidence=None):
        return projection.build({
            "as_of": "2026-08-14T00:00:00Z",
            "opportunities": [opportunity or self.opportunity],
            "evidence": [evidence or self.evidence],
            "resolution_tasks": tasks or [],
        })

    def test_verified_publishable_facts_are_allowed_with_reasons(self):
        row = self.build()
        self.assertEqual(row["materialFacts"], {"status": "OPEN"})
        self.assertEqual(row["publicationDecision"]["decision"], "ALLOW_VERIFIED_FACTS")
        self.assertEqual(
            row["publicationDecision"]["reasonCodes"],
            ["PUBLICATION_STATE_PUBLISHABLE", "VERIFIED_FACTS_ONLY"],
        )

    def test_active_resolution_task_blocks_even_publishable_state(self):
        task = {
            "opportunity_id": "test-call",
            "status": "IN_REVIEW",
            "blocked_fact_classes": ["status", "deadline"],
        }
        row = self.build(tasks=[task])
        self.assertEqual(row["materialFacts"], {})
        self.assertEqual(row["publicationDecision"]["decision"], "BLOCK_MATERIAL_FACTS")
        self.assertIn("ACTIVE_RESOLUTION_TASK", row["publicationDecision"]["reasonCodes"])
        self.assertEqual(row["publicationDecision"]["blockedFactClasses"], ["deadline", "status"])

    def test_unverified_material_fact_is_removed_fail_closed(self):
        opportunity = copy.deepcopy(self.opportunity)
        opportunity["material_facts"]["budget"] = {"total_eur": 1}
        row = self.build(opportunity=opportunity)
        self.assertEqual(row["materialFacts"], {})
        self.assertEqual(row["publicationDecision"]["decision"], "BLOCK_MATERIAL_FACTS")
        self.assertIn("UNVERIFIED_MATERIAL_FACTS", row["publicationDecision"]["reasonCodes"])
        self.assertEqual(row["publicationDecision"]["blockedFactClasses"], ["budget"])

    def test_summary_counts_effective_decisions_not_declared_state(self):
        task = {
            "opportunity_id": "test-call",
            "status": "OPEN",
            "blocked_fact_classes": ["status"],
        }
        result = self.build_projection(tasks=[task])
        self.assertEqual(result["summary"]["publishableCount"], 0)
        self.assertEqual(result["summary"]["reviewCount"], 1)
        self.assertEqual(result["summary"]["decisionCounts"], {
            "ALLOW_VERIFIED_FACTS": 0,
            "BLOCK_MATERIAL_FACTS": 1,
        })

    def test_blocked_record_cannot_inflate_open_verified_count(self):
        opportunity = copy.deepcopy(self.opportunity)
        opportunity["material_facts"]["deadline"] = {"closes_at": "2026-08-31T12:00:00+03:00"}
        opportunity["fact_evidence"]["deadline"] = ["EV-1"]
        evidence = copy.deepcopy(self.evidence)
        evidence["supports_fact_classes"] = ["status", "deadline"]
        task = {
            "opportunity_id": "test-call",
            "status": "IN_REVIEW",
            "blocked_fact_classes": ["deadline"],
        }
        result = self.build_projection(opportunity, [task], evidence)
        self.assertEqual(result["summary"]["openVerifiedCount"], 0)

    def test_block_reason_counts_are_deterministic_and_block_only(self):
        task = {
            "opportunity_id": "test-call",
            "status": "IN_REVIEW",
            "blocked_fact_classes": ["status"],
        }
        result = self.build_projection(tasks=[task])
        self.assertEqual(result["summary"]["blockReasonCounts"], {
            "ACTIVE_RESOLUTION_TASK": 1,
        })
        self.assertTrue(result["policy"]["summaryDerivedFromEffectiveDecisions"])


if __name__ == "__main__":
    unittest.main()
