#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from funding_tenders_projection_gate import build_projection_quality_gate  # noqa: E402


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value):
    return hashlib.sha256(canon(value)).hexdigest()


class FundingTendersProjectionGateTests(unittest.TestCase):
    def fixtures(self):
        identifier = "HORIZON-CL5-2026-09-D2-01"
        authority_url = (
            "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"
            + identifier
        )
        facts = {
            "title": "Synthetic direct call title",
            "status": "OPEN",
            "deadline": "2026-09-30T17:00:00+00:00",
            "call_identifier": "HORIZON-CL5-2026-09",
            "budget_eur": 1234567,
        }
        evidence = {
            "schema": "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1",
            "source_family": "EU_DIRECT",
            "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
            "run_id": "FT-RUN-1",
            "fetched_at": "2026-08-28T00:10:00+00:00",
            "authority_readbacks": {
                identifier: {
                    "verified": True,
                    "url": authority_url,
                    "final_url": authority_url,
                    "http_status": 200,
                    "body_sha256": "d" * 64,
                }
            },
            "material_fact_use": False,
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
        }
        reconciliation = {
            "schema": "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1",
            "source_family": "EU_DIRECT",
            "programme_family": "BRUSSELS",
            "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
            "source_evidence_hash": sha(evidence),
            "records": [{
                "identifier": identifier,
                "call_identifier": "HORIZON-CL5-2026-09",
                "authority_url": authority_url,
                "source_run_id": "FT-RUN-1",
                "fetched_at": "2026-08-28T00:10:00+00:00",
                "raw_hash": "a" * 64,
                "semantic_fingerprint": "b" * 64,
                "reconciliation_status": "PASS",
                "ready_for_staging": True,
                "material_fact_use": True,
                "publish_authorized": False,
                "material_facts": facts,
            }],
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
        }
        staging = {
            "schema": "PARTENER_EU_FUNDING_TENDERS_CANONICAL_STAGING_ADMISSION_V1",
            "source_family": "EU_DIRECT",
            "programme_family": "BRUSSELS",
            "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
            "source_evidence_hash": sha(evidence),
            "source_reconciliation_hash": sha(reconciliation),
            "canonical_staging_admission": "PASS",
            "records": [{
                "identifier": identifier,
                "candidate_id": "CAND-1",
                "authority_url": authority_url,
                "source_run_id": "FT-RUN-1",
                "fetched_at": "2026-08-28T00:10:00+00:00",
                "raw_hash": "a" * 64,
                "semantic_fingerprint": "b" * 64,
                "material_facts_sha256": sha(facts),
                "staging_admission": "PASS",
                "publish_authorized": False,
                "missing_proofs": ["PUBLIC_PROJECTION_QUALITY_GATE"],
            }],
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "missing_proofs": ["PUBLIC_PROJECTION_QUALITY_GATE"],
        }
        programme = {
            "schema": "PARTENER_EU_FUNDING_TENDERS_PROGRAMME_RESOLUTION_V1",
            "source_family": "EU_DIRECT",
            "programme_family": "BRUSSELS",
            "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
            "source_evidence_hash": sha(evidence),
            "source_staging_hash": sha(staging),
            "programme_resolution_gate": "PASS",
            "records": [{
                "identifier": identifier,
                "candidate_id": "CAND-1",
                "authority_url": authority_url,
                "programme_identity": "EU_DIRECT::43108390",
                "programme_label": "Horizon Europe (HORIZON)",
                "programme_authority": "EC_FUNDING_TENDERS_FACET::frameworkProgramme",
                "programme_label_authorized": True,
                "source_run_id": "FT-RUN-1",
                "fetched_at": "2026-08-28T00:10:00+00:00",
                "raw_hash": "a" * 64,
                "semantic_fingerprint": "b" * 64,
                "material_facts_sha256": sha(facts),
                "programme_resolution": "PASS",
                "publish_authorized": False,
                "missing_proofs": ["PUBLIC_PROJECTION_QUALITY_GATE"],
            }],
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "missing_proofs": ["PUBLIC_PROJECTION_QUALITY_GATE"],
        }
        return evidence, reconciliation, staging, programme

    def gate(self, evidence, reconciliation, staging, programme):
        return build_projection_quality_gate(
            evidence,
            reconciliation,
            staging,
            programme,
            evaluated_at="2026-08-28T00:20:00+00:00",
        )

    def test_projection_gate_passes_without_publication(self):
        evidence, reconciliation, staging, programme = self.fixtures()
        receipt = self.gate(evidence, reconciliation, staging, programme)
        self.assertEqual(receipt["public_projection_quality_gate"], "PASS")
        self.assertTrue(receipt["projection_ready"])
        self.assertFalse(receipt["publish_authorized"])
        self.assertFalse(receipt["canonical_corpus_mutation"])
        self.assertEqual(receipt["publication_effect"], "NONE")
        self.assertEqual(receipt["missing_proofs"], [])
        row = receipt["records"][0]
        self.assertEqual(row["status"], "OPEN")
        self.assertEqual(row["programme_label"], "Horizon Europe (HORIZON)")
        self.assertEqual(row["confidence"], "HIGH")
        self.assertEqual(row["missing_to_confirm_call"], [])
        self.assertTrue(row["projection_id"].startswith("EU-PROJ-"))

    def test_elapsed_open_deadline_fails_closed(self):
        evidence, reconciliation, staging, programme = self.fixtures()
        reconciliation["records"][0]["material_facts"]["deadline"] = "2026-08-27T23:00:00+00:00"
        staging["source_reconciliation_hash"] = sha(reconciliation)
        staging["records"][0]["material_facts_sha256"] = sha(reconciliation["records"][0]["material_facts"])
        programme["source_staging_hash"] = sha(staging)
        programme["records"][0]["material_facts_sha256"] = staging["records"][0]["material_facts_sha256"]
        with self.assertRaisesRegex(ValueError, "deadline elapsed"):
            self.gate(evidence, reconciliation, staging, programme)

    def test_exact_topic_readback_drift_fails_closed(self):
        evidence, reconciliation, staging, programme = self.fixtures()
        identifier = reconciliation["records"][0]["identifier"]
        evidence["authority_readbacks"][identifier]["final_url"] += "?drift=1"
        reconciliation["source_evidence_hash"] = sha(evidence)
        staging["source_evidence_hash"] = sha(evidence)
        staging["source_reconciliation_hash"] = sha(reconciliation)
        programme["source_evidence_hash"] = sha(evidence)
        programme["source_staging_hash"] = sha(staging)
        with self.assertRaisesRegex(ValueError, "URL drift"):
            self.gate(evidence, reconciliation, staging, programme)

    def test_material_fact_hash_drift_fails_closed(self):
        evidence, reconciliation, staging, programme = self.fixtures()
        staging["records"][0]["material_facts_sha256"] = "0" * 64
        programme["source_staging_hash"] = sha(staging)
        with self.assertRaisesRegex(ValueError, "material_facts hash drift"):
            self.gate(evidence, reconciliation, staging, programme)

    def test_identity_set_drift_fails_closed(self):
        evidence, reconciliation, staging, programme = self.fixtures()
        extra = copy.deepcopy(programme["records"][0])
        extra["identifier"] = "HORIZON-EXTRA"
        programme["records"].append(extra)
        with self.assertRaisesRegex(ValueError, "identity set drift"):
            self.gate(evidence, reconciliation, staging, programme)

    def test_pipeline_status_cannot_enter_projection(self):
        evidence, reconciliation, staging, programme = self.fixtures()
        reconciliation["records"][0]["material_facts"]["status"] = "PLANNED"
        staging["source_reconciliation_hash"] = sha(reconciliation)
        staging["records"][0]["material_facts_sha256"] = sha(reconciliation["records"][0]["material_facts"])
        programme["source_staging_hash"] = sha(staging)
        programme["records"][0]["material_facts_sha256"] = staging["records"][0]["material_facts_sha256"]
        with self.assertRaisesRegex(ValueError, "not OPEN/FORTHCOMING"):
            self.gate(evidence, reconciliation, staging, programme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
