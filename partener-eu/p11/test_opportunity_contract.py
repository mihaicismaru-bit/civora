#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from opportunity_contract import ContractViolation, validate_bundle  # noqa: E402


def valid_bundle():
    return {
        "schema_version": "1.0",
        "evidence": [{
            "schema_version": "1.0",
            "evidence_id": "EV-001",
            "source_tier": "T1",
            "source_url": "https://example.gov.ro/apel",
            "observed_at": "2026-08-12T10:00:00Z",
            "semantic_sha256": "a" * 64,
            "semantic_verdict": "VERIFIED",
            "supports_fact_classes": ["status", "deadline", "budget"],
        }],
        "opportunities": [{
            "schema_version": "1.0",
            "opportunity_id": "OPP-001",
            "title": "Apel demonstrativ",
            "status": "OPEN",
            "publication_state": "PUBLISHABLE",
            "automatic_material_fact_update_allowed": False,
            "evidence_refs": ["EV-001"],
            "fact_evidence": {"status": ["EV-001"], "deadline": ["EV-001"], "budget": ["EV-001"]},
        }],
        "changesets": [{
            "schema_version": "1.0",
            "changeset_id": "CS-001",
            "opportunity_id": "OPP-001",
            "automatic_publish_allowed": False,
            "resolution_state": "VERIFIED",
            "changes": [{"fact_class": "budget", "before": "1 EUR", "after": "2 EUR", "evidence_refs": ["EV-001"]}],
        }],
        "resolution_tasks": [{
            "schema_version": "1.0",
            "resolution_task_id": "RT-001",
            "opportunity_id": "OPP-001",
            "status": "RESOLVED",
            "automatic_material_fact_update_allowed": False,
            "blocked_fact_classes": ["budget"],
        }],
    }


class ContractTests(unittest.TestCase):
    def test_valid_authoritative_bundle_passes(self):
        self.assertEqual(validate_bundle(valid_bundle())["opportunities"], 1)

    def test_open_without_deadline_evidence_fails_closed(self):
        bundle = valid_bundle()
        bundle["opportunities"][0]["fact_evidence"].pop("deadline")
        with self.assertRaisesRegex(ContractViolation, "OPEN lacks authoritative deadline evidence"):
            validate_bundle(bundle)

    def test_t2_cannot_authorize_material_publication(self):
        bundle = valid_bundle()
        bundle["evidence"][0]["source_tier"] = "T2"
        with self.assertRaises(ContractViolation):
            validate_bundle(bundle)

    def test_unresolved_semantics_cannot_promote_status(self):
        bundle = valid_bundle()
        bundle["evidence"][0]["semantic_verdict"] = "UNRESOLVED"
        with self.assertRaises(ContractViolation):
            validate_bundle(bundle)

    def test_material_autopublish_is_rejected(self):
        bundle = valid_bundle()
        bundle["changesets"][0]["automatic_publish_allowed"] = True
        with self.assertRaisesRegex(ContractViolation, "automatic_publish_allowed must be false"):
            validate_bundle(bundle)

    def test_orphan_resolution_task_is_rejected(self):
        bundle = copy.deepcopy(valid_bundle())
        bundle["resolution_tasks"][0]["opportunity_id"] = "OPP-MISSING"
        with self.assertRaisesRegex(ContractViolation, "orphan ResolutionTask"):
            validate_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
