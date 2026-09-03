#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

import eu_direct_easi_programme_intelligence as mod

REGISTRY_PATH = ROOT / "ingest" / "eu_direct_easi_programme_intelligence_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def healthy_fetch(url: str):
    rows = {r["url"]: r for r in registry()["sources"]}
    src = rows[url]
    body = "<html><body>" + " ".join(src["required_markers"]) + " Open 31 December 2099 EUR 999 million </body></html>"
    return body.encode("utf-8"), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


class EaSIProgrammeIntelligenceTests(unittest.TestCase):
    def test_healthy_registry_is_non_authorizing(self):
        snap = mod.collect(registry(), "test-run", fetcher=healthy_fetch)
        self.assertEqual(snap["schema"], "PARTENER_EU_EASI_PROGRAMME_INTELLIGENCE_V1")
        self.assertEqual(snap["source_count"], 4)
        self.assertEqual(snap["healthy_source_count"], 4)
        self.assertEqual(snap["degraded_source_count"], 0)
        self.assertEqual(snap["source_health_state"], "HEALTHY")
        self.assertEqual({r["observation_state"] for r in snap["evidence"]}, {
            "PROGRAMME_INTELLIGENCE", "APPLICATION_ROUTE_INTELLIGENCE",
            "PROGRAMMING_PIPELINE", "PARTNER_INTELLIGENCE",
        })
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)
        self.assertTrue(snap["market_intelligence_only"])
        self.assertTrue(snap["fit_score_is_not_eligibility"])
        self.assertTrue(snap["partner_intelligence_is_not_call_eligibility"])
        self.assertEqual(snap["publication_effect"], "NONE")
        self.assertEqual(len(snap["semantic_fingerprint"]), 64)
        for row in snap["evidence"]:
            self.assertEqual(row["source_health"], "HEALTHY")
            self.assertFalse(row["lkg_required"])
            self.assertEqual(len(row["raw_sha256"]), 64)
            self.assertEqual(len(row["normalized_visible_text_sha256"]), 64)
            self.assertEqual(len(row["source_semantic_fingerprint"]), 64)

    def test_lexical_open_deadline_budget_never_authorize(self):
        snap = mod.collect(registry(), "open-words", fetcher=healthy_fetch)
        self.assertFalse(snap["open_call_authorized"])
        self.assertFalse(snap["deadline_authorized"])
        self.assertFalse(snap["budget_authorized"])
        self.assertFalse(snap["eligibility_authorized"])
        self.assertFalse(snap["publish_authorized"])
        self.assertFalse(snap["distribution_authorized"])

    def test_programming_cannot_become_open_call(self):
        broken = copy.deepcopy(registry())
        broken["sources"][2]["observation_state"] = "OPEN_CALL"
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-state", fetcher=healthy_fetch)

    def test_policy_cannot_authorize(self):
        broken = copy.deepcopy(registry())
        broken["policy"]["open_call_authorized"] = True
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-policy", fetcher=healthy_fetch)

    def test_authority_host_drift_fails_closed(self):
        broken = copy.deepcopy(registry())
        broken["sources"][0]["url"] = "https://example.com/easi"
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-host", fetcher=healthy_fetch)

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
        bad = [r for r in snap["evidence"] if r["source_health"] == "DEGRADED"]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0]["lkg_required"])
        self.assertIsNone(bad[0]["raw_sha256"])
        self.assertIsNone(bad[0]["source_semantic_fingerprint"])
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)

    def test_marker_drift_degrades_without_material_truth(self):
        def missing_marker(url: str):
            return b"<html><body>unrelated content only</body></html>", {
                "requested_url": url, "final_url": url, "http_status": 200,
                "content_type": "text/html; charset=utf-8",
            }
        snap = mod.collect(registry(), "marker-drift", fetcher=missing_marker)
        self.assertEqual(snap["healthy_source_count"], 0)
        self.assertEqual(snap["degraded_source_count"], 4)
        self.assertTrue(snap["lkg_required"])
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)


if __name__ == "__main__":
    unittest.main()
