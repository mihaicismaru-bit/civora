#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from funding_tenders_programme_resolution import resolve_programmes  # noqa: E402


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_json(value):
    return hashlib.sha256(canon(value)).hexdigest()


class ProgrammeResolutionTests(unittest.TestCase):
    def fixtures(self):
        facet = {
            "apiVersion": "2.153",
            "facets": [
                {
                    "name": "frameworkProgramme",
                    "rawName": "frameworkProgramme",
                    "values": [
                        {"rawValue": "43108390", "value": "Horizon Europe (HORIZON)", "count": 972},
                        {"rawValue": "43152860", "value": "Digital Europe Programme (DIGITAL)", "count": 85},
                    ],
                },
                {"name": "status", "values": [{"rawValue": "31094502", "value": "Open for submission"}]},
            ],
        }
        facet_raw = canon(facet)
        evidence = {
            "schema": "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1",
            "source_family": "EU_DIRECT",
            "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
            "facet_receipts": {"broad": {"sha256": hashlib.sha256(facet_raw).hexdigest(), "http_status": 200}},
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "material_fact_use": False,
        }
        row = {
            "identifier": "HORIZON-CL5-2026-09-D4-03",
            "candidate_id": "CAND-1",
            "call_identifier": "HORIZON-CL5-2026-09",
            "authority_url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/HORIZON-CL5-2026-09-D4-03",
            "programme_reference": "43108390",
            "programme_label_authorized": False,
            "source_run_id": "RUN-1",
            "fetched_at": "2026-08-27T21:42:00+00:00",
            "raw_hash": "a" * 64,
            "semantic_fingerprint": "b" * 64,
            "material_facts_sha256": "c" * 64,
            "staging_admission": "PASS",
            "material_fact_use": True,
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "material_fact_action": "NONE",
            "missing_proofs": ["PUBLIC_PROJECTION_QUALITY_GATE"],
        }
        staging = {
            "schema": "PARTENER_EU_FUNDING_TENDERS_CANONICAL_STAGING_ADMISSION_V1",
            "source_evidence_hash": sha_json(evidence),
            "source_family": "EU_DIRECT",
            "programme_family": "BRUSSELS",
            "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
            "canonical_staging_admission": "PASS",
            "programme_label_authorized": False,
            "records": [row],
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "material_fact_action": "NONE",
            "missing_proofs": ["PUBLIC_PROJECTION_QUALITY_GATE"],
        }
        return staging, evidence, facet, facet_raw

    def test_resolves_only_from_bound_framework_programme_facet(self):
        staging, evidence, facet, facet_raw = self.fixtures()
        receipt = resolve_programmes(staging, evidence, facet, facet_raw_bytes=facet_raw)
        self.assertEqual(receipt["programme_resolution_gate"], "PASS")
        self.assertTrue(receipt["programme_label_authorized"])
        self.assertFalse(receipt["publish_authorized"])
        self.assertEqual(receipt["records"][0]["programme_identity"], "EU_DIRECT::43108390")
        self.assertEqual(receipt["records"][0]["programme_label"], "Horizon Europe (HORIZON)")
        self.assertEqual(receipt["stats"], {"staging_records": 1, "programme_resolved": 1, "unique_programmes": 1, "unresolved": 0})

    def test_unresolved_reference_fails_closed(self):
        staging, evidence, facet, facet_raw = self.fixtures()
        staging["records"][0]["programme_reference"] = "99999999"
        with self.assertRaisesRegex(ValueError, "unresolved"):
            resolve_programmes(staging, evidence, facet, facet_raw_bytes=facet_raw)

    def test_facet_hash_must_match_live_receipt(self):
        staging, evidence, facet, facet_raw = self.fixtures()
        evidence["facet_receipts"]["broad"]["sha256"] = "0" * 64
        staging["source_evidence_hash"] = sha_json(evidence)
        with self.assertRaisesRegex(ValueError, "Facet bytes"):
            resolve_programmes(staging, evidence, facet, facet_raw_bytes=facet_raw)

    def test_staging_must_bind_exact_evidence(self):
        staging, evidence, facet, facet_raw = self.fixtures()
        evidence["material_fact_use"] = True
        with self.assertRaisesRegex(ValueError, "source_evidence_hash"):
            resolve_programmes(staging, evidence, facet, facet_raw_bytes=facet_raw)

    def test_numeric_only_facet_label_cannot_authorize_programme(self):
        staging, evidence, facet, facet_raw = self.fixtures()
        facet["facets"][0]["values"][0]["value"] = "43108390"
        changed = canon(facet)
        evidence["facet_receipts"]["broad"]["sha256"] = hashlib.sha256(changed).hexdigest()
        staging["source_evidence_hash"] = sha_json(evidence)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            resolve_programmes(staging, evidence, facet, facet_raw_bytes=changed)

    def test_pre_authorized_programme_label_is_rejected(self):
        staging, evidence, facet, facet_raw = self.fixtures()
        staging["programme_label_authorized"] = True
        with self.assertRaisesRegex(ValueError, "still be unauthorized"):
            resolve_programmes(staging, evidence, facet, facet_raw_bytes=facet_raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
