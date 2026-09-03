#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

import eu_direct_rfcs_programme_intelligence as rfcs

REGISTRY_PATH = ROOT / "ingest" / "eu_direct_rfcs_programme_intelligence_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def fake_fetch(url: str):
    markers = {
        row["url"]: row["required_markers"] for row in registry()["sources"]
    }[url]
    body = " ".join(markers)
    if "annual-rfcs-call" in url:
        body += " Open 17 June 2026 deadline 16 September 2026 overall indicative budget EUR 40 million"
    return f"<html><body>{body}</body></html>".encode(), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


class RFCSProgrammeIntelligenceTests(unittest.TestCase):
    def test_happy_path_stays_non_authorizing_even_with_open_deadline_budget_words(self):
        snap = rfcs.collect(registry(), "test-run", fetcher=fake_fetch)
        self.assertEqual(snap["schema"], rfcs.SCHEMA)
        self.assertEqual(snap["programme_id"], "RFCS")
        self.assertEqual(snap["source_count"], 4)
        self.assertEqual(snap["healthy_source_count"], 4)
        self.assertEqual(snap["degraded_source_count"], 0)
        self.assertEqual(snap["source_health_state"], "HEALTHY")
        self.assertEqual({r["observation_state"] for r in snap["evidence"]}, {
            "PROGRAMME_INTELLIGENCE", "PROGRAMMING_PIPELINE",
            "CALL_INDEX_DISCOVERY", "APPLICANT_FIT_INTELLIGENCE",
        })
        for flag in rfcs.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)
        self.assertEqual(snap["publication_effect"], "NONE")
        self.assertTrue(snap["fit_score_is_not_eligibility"])
        self.assertTrue(snap["partner_intelligence_is_not_call_eligibility"])
        self.assertEqual(snap["romania_programme_fit"], "EU_MEMBER_STATE_APPLICANT_POOL_NON_AUTHORIZING")
        self.assertIn("field_scoped_material_admission", snap["missing_for_open_confirmation"])

    def test_registry_cannot_authorize_open(self):
        data = registry()
        data["policy"]["open_call_authorized"] = True
        with self.assertRaisesRegex(ValueError, "became authorizing"):
            rfcs.validate_registry(data)

    def test_programming_or_index_cannot_become_open_call_state(self):
        data = registry()
        data["sources"][1]["observation_state"] = "OPEN_CALL"
        with self.assertRaisesRegex(ValueError, "observation state became call state"):
            rfcs.validate_registry(data)

    def test_authority_host_drift_is_rejected(self):
        data = registry()
        data["sources"][0]["url"] = "https://example.com/rfcs"
        with self.assertRaisesRegex(ValueError, "authority URL drift"):
            rfcs.validate_registry(data)

    def test_transport_failure_is_degraded_and_requires_lkg(self):
        data = registry()
        failing_url = data["sources"][2]["url"]

        def flaky(url: str):
            if url == failing_url:
                raise TimeoutError("synthetic timeout")
            return fake_fetch(url)

        snap = rfcs.collect(data, "test-degraded", fetcher=flaky)
        self.assertEqual(snap["source_health_state"], "DEGRADED")
        self.assertEqual(snap["healthy_source_count"], 3)
        self.assertEqual(snap["degraded_source_count"], 1)
        self.assertTrue(snap["lkg_required"])
        failed = next(r for r in snap["evidence"] if r["source_id"] == "RFCS-REA-ANNUAL-CALL-INDEX")
        self.assertEqual(failed["source_health"], "DEGRADED")
        self.assertTrue(failed["lkg_required"])
        self.assertIsNone(failed["source_semantic_fingerprint"])
        for flag in rfcs.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)

    def test_marker_drift_is_degraded_not_material_change(self):
        data = registry()
        bad_url = data["sources"][0]["url"]

        def marker_drift(url: str):
            if url == bad_url:
                return b"<html><body>unrelated content Open EUR 999 million 31 December 2030</body></html>", {
                    "requested_url": url,
                    "final_url": url,
                    "http_status": 200,
                    "content_type": "text/html",
                }
            return fake_fetch(url)

        snap = rfcs.collect(data, "test-marker", fetcher=marker_drift)
        failed = next(r for r in snap["evidence"] if r["source_id"] == "RFCS-EC-PROGRAMME-ROOT")
        self.assertEqual(failed["source_health"], "DEGRADED")
        self.assertTrue(failed["lkg_required"])
        self.assertIn("MARKER_DRIFT", failed["error"])
        self.assertFalse(snap["material_fact_use"])
        self.assertFalse(snap["open_call_authorized"])
        self.assertFalse(snap["deadline_authorized"])
        self.assertFalse(snap["budget_authorized"])

    def test_fit_boundary_cannot_be_relabelled_as_eligibility(self):
        data = registry()
        data["applicant_fit"]["fit_is_not_eligibility"] = False
        with self.assertRaisesRegex(ValueError, "fit became eligibility"):
            rfcs.validate_registry(data)


if __name__ == "__main__":
    unittest.main()
