#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

import eu_direct_i3_programme_intelligence as mod

REGISTRY_PATH = ROOT / "ingest" / "eu_direct_i3_programme_intelligence_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def healthy_fetch(url: str):
    rows = {row["url"]: row for row in registry()["sources"]}
    source = rows[url]
    body = (
        "<html><body>"
        + " ".join(source["required_markers"])
        + " Open 12 November 2026 EUR 30.2 million eligibility SMEs Romania "
        + "</body></html>"
    )
    return body.encode("utf-8"), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


class I3ProgrammeIntelligenceTests(unittest.TestCase):
    def test_healthy_registry_is_non_authorizing(self):
        snap = mod.collect(registry(), "test-run", fetcher=healthy_fetch)
        self.assertEqual(snap["schema"], "PARTENER_EU_I3_PROGRAMME_INTELLIGENCE_V1")
        self.assertEqual(snap["programme_id"], "I3")
        self.assertEqual(snap["source_count"], 5)
        self.assertEqual(snap["healthy_source_count"], 5)
        self.assertEqual(snap["degraded_source_count"], 0)
        self.assertEqual(snap["source_health_state"], "HEALTHY")
        self.assertEqual(
            {row["observation_state"] for row in snap["evidence"]},
            {
                "PROGRAMME_INTELLIGENCE",
                "PROGRAMMING_PIPELINE",
                "PARTNER_INTELLIGENCE",
                "CALL_INDEX_DISCOVERY",
            },
        )
        hints = {
            row["call_reference_hint"]
            for row in snap["evidence"]
            if row.get("call_reference_hint")
        }
        self.assertEqual(hints, {"I3-2026-INV1", "I3-2026-INV2a"})
        for row in snap["evidence"]:
            if row.get("call_reference_hint"):
                self.assertEqual(
                    row["call_reference_hint_authority"],
                    "DISCOVERY_HINT_ONLY_NOT_CALL_IDENTIFIER",
                )
            self.assertEqual(row["source_health"], "HEALTHY")
            self.assertFalse(row["lkg_required"])
            self.assertEqual(len(row["raw_sha256"]), 64)
            self.assertEqual(len(row["normalized_visible_text_sha256"]), 64)
            self.assertEqual(len(row["source_semantic_fingerprint"]), 64)
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)
        self.assertTrue(snap["market_intelligence_only"])
        self.assertTrue(snap["fit_score_is_not_eligibility"])
        self.assertTrue(snap["geography_fit_is_not_eligibility"])
        self.assertTrue(snap["partner_intelligence_is_not_call_eligibility"])
        self.assertTrue(snap["structured_funding_tenders_reconciliation_required"])
        self.assertEqual(snap["publication_effect"], "NONE")

    def test_lexical_open_deadline_budget_eligibility_never_authorize(self):
        snap = mod.collect(registry(), "lexical-material-words", fetcher=healthy_fetch)
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)
        self.assertIn("fresh_structured_funding_tenders_status", snap["missing_for_open_confirmation"])
        self.assertIn("field_scoped_material_admission", snap["missing_for_open_confirmation"])

    def test_programming_or_discovery_cannot_become_open_call(self):
        for index in (1, 3):
            broken = copy.deepcopy(registry())
            broken["sources"][index]["observation_state"] = "OPEN_CALL"
            with self.assertRaises(ValueError):
                mod.collect(broken, "bad-state", fetcher=healthy_fetch)

    def test_policy_cannot_authorize(self):
        broken = copy.deepcopy(registry())
        broken["policy"]["open_call_authorized"] = True
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-policy", fetcher=healthy_fetch)

    def test_authority_host_drift_fails_closed(self):
        broken = copy.deepcopy(registry())
        broken["sources"][0]["url"] = "https://example.com/i3"
        with self.assertRaises(ValueError):
            mod.collect(broken, "bad-host", fetcher=healthy_fetch)

    def test_call_reference_hint_must_remain_discovery_only(self):
        broken = copy.deepcopy(registry())
        broken["sources"][3]["observation_state"] = "PROGRAMME_INTELLIGENCE"
        with self.assertRaises(ValueError):
            mod.collect(broken, "hint-widening", fetcher=healthy_fetch)

    def test_transport_failure_requires_lkg_and_no_partial_semantics(self):
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
        self.assertEqual(snap["degraded_source_count"], 5)
        self.assertTrue(snap["lkg_required"])
        for row in snap["evidence"]:
            self.assertIsNone(row["source_semantic_fingerprint"])
        for flag in mod.MATERIAL_FLAGS:
            self.assertFalse(snap[flag], flag)

    def test_visible_content_change_changes_semantic_fingerprint(self):
        counter = {"n": 0}

        def changing_fetch(url: str):
            raw, meta = healthy_fetch(url)
            counter["n"] += 1
            return raw.replace(b"</body>", f" content-{counter['n']} </body>".encode()), meta

        first = mod.collect(registry(), "first", fetcher=healthy_fetch)
        second = mod.collect(registry(), "second", fetcher=changing_fetch)
        self.assertNotEqual(first["semantic_fingerprint"], second["semantic_fingerprint"])
        self.assertNotEqual(
            first["evidence"][0]["source_semantic_fingerprint"],
            second["evidence"][0]["source_semantic_fingerprint"],
        )


if __name__ == "__main__":
    unittest.main()
