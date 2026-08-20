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
            "source_url": "https://example.test/call",
            "observed_at": "2026-08-14T00:00:00Z",
            "supports_fact_classes": ["status"],
        }

    def build(self, opportunity=None, tasks=None, evidence=None):
        return self.build_projection(opportunity, tasks, evidence)["opportunities"][0]

    def build_projection(self, opportunity=None, tasks=None, evidence=None):
        evidence_rows = evidence if isinstance(evidence, list) else [evidence or self.evidence]
        return projection.build({
            "as_of": "2026-08-14T00:00:00Z",
            "opportunities": [opportunity or self.opportunity],
            "evidence": evidence_rows,
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
        self.assertEqual(row["verifiedEvidenceCount"], 1)
        self.assertEqual(row["verificationEvidence"], [{
            "evidenceId": "EV-1",
            "sourceTier": "T1",
            "sourceUrl": "https://example.test/call",
            "sourceHost": "example.test",
            "observedAt": "2026-08-14T00:00:00Z",
            "ageSecondsAtProjection": 0,
            "supportedFactClasses": ["status"],
        }])
        self.assertEqual(row["verificationEvidence"][0]["ageSecondsAtProjection"], 0)
        self.assertEqual(row["verificationSourceCoverage"], {
            "verifiedEvidenceLinkCount": 1,
            "uniqueSourceHostCount": 1,
            "sourceHosts": ["example.test"],
            "sourceTierCounts": {"T1": 1, "T1B": 0},
        })

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

    def test_integrity_gate_rejects_material_facts_on_blocked_record(self):
        result = self.build_projection()
        result["opportunities"][0]["publicationDecision"]["decision"] = "BLOCK_MATERIAL_FACTS"
        with self.assertRaisesRegex(ValueError, "blocked decision exposes material facts"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_summary_drift(self):
        result = self.build_projection()
        result["summary"]["publishableCount"] += 1
        with self.assertRaisesRegex(ValueError, "summary.publishableCount"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_unverified_allowed_fact(self):
        result = self.build_projection()
        result["opportunities"][0]["materialFacts"]["budget"] = {"total_eur": 1}
        with self.assertRaisesRegex(ValueError, "allowed decision exposes unverified material facts"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_unknown_decision(self):
        result = self.build_projection()
        result["opportunities"][0]["publicationDecision"]["decision"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "unknown publication decision"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_duplicate_opportunity_id(self):
        result = self.build_projection()
        result["opportunities"].append(copy.deepcopy(result["opportunities"][0]))
        with self.assertRaisesRegex(ValueError, "opportunity ids must be unique"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_unsafe_policy(self):
        result = self.build_projection()
        result["policy"]["automaticPublication"] = True
        with self.assertRaisesRegex(ValueError, "policy must disable automatic publication"):
            projection.assert_projection_integrity(result)

    def test_verification_provenance_is_deterministic_and_fact_scoped(self):
        opportunity = copy.deepcopy(self.opportunity)
        opportunity["material_facts"]["deadline"] = {"closes_at": "2026-08-31T12:00:00+03:00"}
        opportunity["fact_evidence"] = {"status": ["EV-1"], "deadline": ["EV-1"]}
        evidence = copy.deepcopy(self.evidence)
        evidence["supports_fact_classes"] = ["status", "deadline"]
        row = self.build(opportunity=opportunity, evidence=evidence)
        self.assertEqual(row["verifiedFactClasses"], ["deadline", "status"])
        self.assertEqual(row["verificationEvidence"][0]["supportedFactClasses"], ["deadline", "status"])

    def test_unresolved_evidence_is_not_exposed_as_verification_provenance(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["semantic_verdict"] = "UNRESOLVED"
        row = self.build(evidence=evidence)
        self.assertEqual(row["verifiedEvidenceCount"], 0)
        self.assertEqual(row["verificationEvidence"], [])

    def test_integrity_gate_rejects_provenance_fact_class_drift(self):
        result = self.build_projection()
        result["opportunities"][0]["verificationEvidence"][0]["supportedFactClasses"] = ["deadline"]
        with self.assertRaisesRegex(ValueError, "provenance does not match verified fact classes"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_non_authoritative_provenance(self):
        result = self.build_projection()
        result["opportunities"][0]["verificationEvidence"][0]["sourceTier"] = "T2"
        with self.assertRaisesRegex(ValueError, "verification evidence must be T1 or T1B"):
            projection.assert_projection_integrity(result)

    def test_verification_freshness_is_derived_from_projection_time(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["observed_at"] = "2026-08-13T22:00:00Z"
        result = self.build_projection(evidence=evidence)
        self.assertEqual(result["opportunities"][0]["verificationEvidence"][0]["ageSecondsAtProjection"], 7200)
        self.assertEqual(result["summary"]["verificationFreshness"], {
            "referenceTime": "2026-08-14T00:00:00Z",
            "verifiedEvidenceLinkCount": 1,
            "oldestObservedAt": "2026-08-13T22:00:00Z",
            "newestObservedAt": "2026-08-13T22:00:00Z",
            "maximumAgeSeconds": 7200,
            "minimumAgeSeconds": 7200,
        })

    def test_future_verified_evidence_is_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["observed_at"] = "2026-08-14T00:00:01Z"
        with self.assertRaisesRegex(ValueError, "cannot be observed after projection asOf"):
            self.build_projection(evidence=evidence)

    def test_integrity_gate_rejects_evidence_age_drift(self):
        result = self.build_projection()
        result["opportunities"][0]["verificationEvidence"][0]["ageSecondsAtProjection"] = 1
        with self.assertRaisesRegex(ValueError, "verification evidence age does not match timestamps"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_freshness_summary_drift(self):
        result = self.build_projection()
        result["summary"]["verificationFreshness"]["maximumAgeSeconds"] = 1
        with self.assertRaisesRegex(ValueError, "summary.verificationFreshness"):
            projection.assert_projection_integrity(result)

    def test_verification_source_coverage_is_derived_from_authoritative_hosts_and_tiers(self):
        opportunity = copy.deepcopy(self.opportunity)
        opportunity["fact_evidence"]["status"] = ["EV-2", "EV-1"]
        opportunity["evidence_refs"] = ["EV-1", "EV-2"]
        second_evidence = copy.deepcopy(self.evidence)
        second_evidence.update({
            "evidence_id": "EV-2",
            "source_tier": "T1B",
            "source_url": "https://other.example.test/notice",
        })
        result = self.build_projection(
            opportunity=opportunity,
            evidence=[second_evidence, self.evidence],
        )
        coverage = result["opportunities"][0]["verificationSourceCoverage"]
        self.assertEqual(coverage, {
            "verifiedEvidenceLinkCount": 2,
            "uniqueSourceHostCount": 2,
            "sourceHosts": ["example.test", "other.example.test"],
            "sourceTierCounts": {"T1": 1, "T1B": 1},
        })
        self.assertEqual(result["summary"]["verificationSourceCoverage"], {
            **coverage,
            "verifiedOpportunityCount": 1,
            "singleSourceHostOpportunityCount": 0,
            "multipleSourceHostOpportunityCount": 1,
        })

    def test_integrity_gate_rejects_source_host_drift(self):
        result = self.build_projection()
        result["opportunities"][0]["verificationEvidence"][0]["sourceHost"] = "wrong.test"
        with self.assertRaisesRegex(ValueError, "source host does not match URL"):
            projection.assert_projection_integrity(result)

    def test_integrity_gate_rejects_source_coverage_drift(self):
        result = self.build_projection()
        result["opportunities"][0]["verificationSourceCoverage"]["uniqueSourceHostCount"] = 2
        with self.assertRaisesRegex(ValueError, "source coverage does not match provenance"):
            projection.assert_projection_integrity(result)

    def test_source_coverage_telemetry_cannot_authorize_publication(self):
        result = self.build_projection()
        result["policy"]["sourceCoverageTelemetryAuthorizesPublication"] = True
        with self.assertRaisesRegex(ValueError, "source coverage telemetry must not authorize publication"):
            projection.assert_projection_integrity(result)


if __name__ == "__main__":
    unittest.main()
