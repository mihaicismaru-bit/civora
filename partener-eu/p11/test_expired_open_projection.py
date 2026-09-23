#!/usr/bin/env python3
import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("projection", ROOT / "p11" / "build_public_projection.py")
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class ExpiredOpenProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = {
            "evidence_id": "EV-OPEN",
            "semantic_verdict": "VERIFIED",
            "source_tier": "T1",
            "source_url": "https://authority.example.test/call",
            "observed_at": "2026-08-01T08:00:00Z",
            "supports_fact_classes": ["deadline", "status"],
        }
        self.opportunity = {
            "opportunity_id": "expired-open",
            "title": "Expired historical OPEN",
            "programme": "Test programme",
            "code": "TEST-OPEN",
            "status": "OPEN",
            "publication_state": "PUBLISHABLE",
            "material_facts": {
                "status": "OPEN",
                "deadline": {"closes_at": "14 august 2026"},
            },
            "fact_evidence": {
                "status": ["EV-OPEN"],
                "deadline": ["EV-OPEN"],
            },
            "evidence_refs": ["EV-OPEN"],
        }

    def build(self, opportunity=None, as_of="2026-09-23T10:00:00Z"):
        return projection.build({
            "as_of": as_of,
            "opportunities": [opportunity or self.opportunity],
            "evidence": [self.evidence],
            "resolution_tasks": [],
        })

    def test_expired_verified_open_is_fail_closed_without_inventing_closed(self):
        result = self.build()
        row = result["opportunities"][0]
        self.assertEqual(row["status"], "DISCOVERED")
        self.assertEqual(row["publicationDecision"]["decision"], "BLOCK_MATERIAL_FACTS")
        self.assertEqual(
            row["publicationDecision"]["reasonCodes"],
            ["OPEN_DEADLINE_EXPIRED_REQUIRES_REFRESH"],
        )
        self.assertEqual(row["materialFacts"], {})
        self.assertEqual(row["verifiedFactClasses"], ["deadline", "status"])
        self.assertEqual(result["summary"]["openVerifiedCount"], 0)
        self.assertEqual(result["summary"]["publishableCount"], 0)
        self.assertTrue(result["policy"]["expiredOpenRequiresAuthorityRefresh"])

    def test_future_verified_open_remains_publishable(self):
        opportunity = copy.deepcopy(self.opportunity)
        opportunity["material_facts"]["deadline"] = {
            "closes_at": "16 octombrie 2026, ora 16:00"
        }
        result = self.build(opportunity)
        row = result["opportunities"][0]
        self.assertEqual(row["status"], "OPEN")
        self.assertEqual(row["publicationDecision"]["decision"], "ALLOW_VERIFIED_FACTS")
        self.assertEqual(row["materialFacts"]["status"], "OPEN")
        self.assertEqual(result["summary"]["openVerifiedCount"], 1)
        self.assertEqual(result["summary"]["publishableCount"], 1)

    def test_date_only_iso_deadline_uses_bucharest_end_of_day(self):
        opportunity = copy.deepcopy(self.opportunity)
        opportunity["material_facts"]["deadline"] = {"closes_at": "2026-09-23"}
        result = self.build(opportunity, as_of="2026-09-23T10:00:00Z")
        row = result["opportunities"][0]
        self.assertEqual(row["status"], "OPEN")
        self.assertEqual(row["publicationDecision"]["decision"], "ALLOW_VERIFIED_FACTS")


if __name__ == "__main__":
    unittest.main()
