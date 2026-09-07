#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

import eu_direct_esc_programme_intelligence as mod

REGISTRY_PATH = ROOT / "ingest" / "eu_direct_esc_programme_intelligence_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def healthy_fetch(url: str):
    rows = {row["url"]: row for row in registry()["sources"]}
    src = rows[url]
    body = (
        "<html><body>"
        + " ".join(src["required_markers"])
        + " OPEN deadline 31 December 2099 budget EUR 999 million eligible organisations Romania "
        + "</body></html>"
    )
    return body.encode("utf-8"), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


class EuropeanSolidarityCorpsProgrammeIntelligenceTests(unittest.TestCase):
    def test_healthy_registry_is_non_authorizing(self):
        snap = mod.collect(registry(), "test-run", fetcher=healthy_fetch)
        self.assertEqual(snap["schema"], "PARTENER_EU_ESC_PROGRAMME_INTELLIGENCE_V1")
        self.assertEqual(snap["programme_id"], "EUROPEAN_SOLIDARITY_CORPS")
        self.assertEqual(snap["source_count"], 3)
        self.assertEqual(snap["healthy_source_count"], 3)
        self.assertEqual(snap["degraded_source_count"], 0)
        self.assertEqual(snap["source_health_state"], "HEALTHY")
        self.assertTrue(snap["evidence_usable_for_reconciliation"])
        self.assertFalse(snap["current_material_truth_available"])
        self.assertEqual(
            {row["observation_state"] for row in snap["evidence"]},
            {"PROGRAMME_INTELLIGENCE", "CALL_INDEX_DISCOVERY"},
        )
        self.assertEqual(snap["programme_context"]["management_mode"], "DIRECT_AND_INDIRECT_MANAGEMENT")
        self.assertEqual(snap["programme_context"]["current_programming_period"], "2021-2027")
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)
        self.assertTrue(snap["market_intelligence_only"])
        self.assertTrue(snap["fit_score_is_not_eligibility"])
        self.assertTrue(snap["route_intelligence_is_not_call_eligibility"])
        self.assertEqual(snap["publication_effect"], "NONE")
        self.assertEqual(len(snap["semantic_fingerprint"]), 64)
        for row in snap["evidence"]:
            self.assertEqual(row["source_health"], "HEALTHY")
            self.assertFalse(row["lkg_required"])
            self.assertTrue(row["evidence_usable_for_reconciliation"])
            self.assertFalse(row["current_material_truth_available"])
            self.assertEqual(len(row["raw_sha256"]), 64)
            self.assertEqual(len(row["normalized_visible_text_sha256"]), 64)
            self.assertEqual(len(row["source_semantic_fingerprint"]), 64)

    def test_lexical_call_facts_never_authorize(self):
        snap = mod.collect(registry(), "open-words", fetcher=healthy_fetch)
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)
        self.assertFalse(snap["current_material_truth_available"])
        self.assertIn("exact_call_or_topic_identifier", snap["missing_for_open_confirmation"])
        self.assertIn("semantic_reconciliation", snap["missing_for_open_confirmation"])
        self.assertIn("field_scoped_material_admission", snap["missing_for_open_confirmation"])

    def test_call_index_cannot_become_open_call_state(self):
        broken = copy.deepcopy(registry())
        broken["sources"][1]["observation_state"] = "OPEN_CALL"
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-state", fetcher=healthy_fetch)

    def test_policy_cannot_authorize(self):
        broken = copy.deepcopy(registry())
        broken["policy"]["open_call_authorized"] = True
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-policy", fetcher=healthy_fetch)

    def test_programme_fit_cannot_become_eligibility(self):
        broken = copy.deepcopy(registry())
        broken["programme_context"]["programme_fit_is_not_call_eligibility"] = False
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-fit", fetcher=healthy_fetch)

    def test_authority_host_drift_fails_registry_validation(self):
        broken = copy.deepcopy(registry())
        broken["sources"][0]["url"] = "https://example.com/esc"
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-host", fetcher=healthy_fetch)

    def test_runtime_redirect_drift_degrades_without_truth(self):
        def redirected(url: str):
            raw, meta = healthy_fetch(url)
            meta["final_url"] = "https://example.com/not-authority"
            return raw, meta

        snap = mod.collect(registry(), "redirect-drift", fetcher=redirected)
        self.assertEqual(snap["healthy_source_count"], 0)
        self.assertEqual(snap["degraded_source_count"], 3)
        self.assertTrue(snap["lkg_required"])
        self.assertFalse(snap["evidence_usable_for_reconciliation"])
        for row in snap["evidence"]:
            self.assertEqual(row["source_health"], "DEGRADED")
            self.assertTrue(row["lkg_required"])
            self.assertFalse(row["evidence_usable_for_reconciliation"])
            self.assertIsNone(row["raw_sha256"])
            self.assertIsNone(row["source_semantic_fingerprint"])
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)

    def test_transport_failure_requires_lkg(self):
        calls = {"n": 0}

        def flaky(url: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("synthetic transport failure")
            return healthy_fetch(url)

        snap = mod.collect(registry(), "degraded", fetcher=flaky)
        self.assertEqual(snap["degraded_source_count"], 1)
        self.assertEqual(snap["source_health_state"], "DEGRADED")
        self.assertTrue(snap["lkg_required"])
        self.assertFalse(snap["evidence_usable_for_reconciliation"])
        bad = [row for row in snap["evidence"] if row["source_health"] == "DEGRADED"]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0]["lkg_required"])
        self.assertIsNone(bad[0]["raw_sha256"])
        self.assertIsNone(bad[0]["source_semantic_fingerprint"])
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)

    def test_marker_drift_degrades_without_material_truth(self):
        def missing_marker(url: str):
            return b"<html><body>unrelated content only</body></html>", {
                "requested_url": url,
                "final_url": url,
                "http_status": 200,
                "content_type": "text/html; charset=utf-8",
            }

        snap = mod.collect(registry(), "marker-drift", fetcher=missing_marker)
        self.assertEqual(snap["healthy_source_count"], 0)
        self.assertEqual(snap["degraded_source_count"], 3)
        self.assertTrue(snap["lkg_required"])
        self.assertFalse(snap["evidence_usable_for_reconciliation"])
        self.assertTrue(all(row["failure_class"] == "MARKER_DRIFT" for row in snap["evidence"]))
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)


if __name__ == "__main__":
    unittest.main()
