#!/usr/bin/env python3
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

import eu_direct_i3_programme_intelligence as intel
import eu_direct_i3_programme_reconcile as rec

REGISTRY_PATH = ROOT / "ingest" / "eu_direct_i3_programme_intelligence_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def healthy_fetch(url: str):
    rows = {row["url"]: row for row in registry()["sources"]}
    source = rows[url]
    raw = ("<html><body>" + " ".join(source["required_markers"]) + " stable evidence </body></html>").encode("utf-8")
    return raw, {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def snapshot(run_id: str, fetched_at: str):
    value = intel.collect(registry(), run_id, fetcher=healthy_fetch)
    value["fetched_at"] = fetched_at
    return value


class I3ProgrammeReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.previous = snapshot("previous", "2026-09-06T05:00:00+00:00")
        self.current = snapshot("current", "2026-09-06T06:00:00+00:00")

    def test_baseline_capture_is_non_authorizing(self):
        out = rec.reconcile(self.current)
        self.assertEqual(out["reconciliation_state"], "BASELINE_CAPTURED_NON_AUTHORIZING")
        self.assertTrue(out["semantic_reconciliation_passed"])
        self.assertEqual(out["semantic_change_count"], 0)
        self.assertFalse(out["market_watch_candidate"])
        self.assertFalse(out["pipeline_watch_candidate"])
        self.assertFalse(out["material_admission_ready_for_downstream_review"])
        for flag in rec.MATERIAL_FLAGS:
            self.assertFalse(out[flag], flag)

    def test_same_identity_healthy_no_change(self):
        out = rec.reconcile(self.current, self.previous)
        self.assertEqual(out["reconciliation_state"], "NO_CHANGE")
        self.assertTrue(out["previous_identity_match"])
        self.assertTrue(out["semantic_reconciliation_passed"])
        self.assertEqual(out["semantic_change_count"], 0)
        self.assertTrue(out["lkg_reference_available"])
        self.assertFalse(out["lkg_reference_is_current_truth"])
        self.assertFalse(out["market_watch_candidate"])
        self.assertFalse(out["pipeline_watch_candidate"])
        for flag in rec.MATERIAL_FLAGS:
            self.assertFalse(out[flag], flag)

    def test_semantic_change_is_watch_only(self):
        changed = copy.deepcopy(self.current)
        changed["evidence"][1]["source_semantic_fingerprint"] = hashlib.sha256(b"changed-programming").hexdigest()
        changed["semantic_fingerprint"] = hashlib.sha256(b"changed-snapshot").hexdigest()
        out = rec.reconcile(changed, self.previous)
        self.assertEqual(out["reconciliation_state"], "I3_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING")
        self.assertGreater(out["semantic_change_count"], 0)
        self.assertTrue(out["market_watch_candidate"])
        self.assertTrue(out["pipeline_watch_candidate"])
        self.assertFalse(out["material_admission_ready_for_downstream_review"])
        for flag in rec.MATERIAL_FLAGS:
            self.assertFalse(out[flag], flag)

    def test_non_pipeline_change_never_becomes_pipeline_or_call_alert(self):
        changed = copy.deepcopy(self.current)
        changed["evidence"][2]["source_semantic_fingerprint"] = hashlib.sha256(b"partner-change").hexdigest()
        changed["semantic_fingerprint"] = hashlib.sha256(b"partner-snapshot").hexdigest()
        out = rec.reconcile(changed, self.previous)
        self.assertTrue(out["market_watch_candidate"])
        self.assertFalse(out["pipeline_watch_candidate"])
        self.assertFalse(out["call_alert_authorized"])
        self.assertFalse(out["distribution_authorized"])

    def test_degraded_current_requires_lkg_and_no_semantic_change(self):
        degraded = copy.deepcopy(self.current)
        degraded["source_health_state"] = "DEGRADED"
        degraded["healthy_source_count"] = 4
        degraded["degraded_source_count"] = 1
        degraded["evidence"][0]["source_health"] = "DEGRADED"
        degraded["evidence"][0]["lkg_required"] = True
        degraded["evidence"][0]["raw_sha256"] = None
        degraded["evidence"][0]["normalized_visible_text_sha256"] = None
        degraded["evidence"][0]["source_semantic_fingerprint"] = None
        out = rec.reconcile(degraded, self.previous)
        self.assertEqual(out["reconciliation_state"], "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED")
        self.assertFalse(out["semantic_reconciliation_passed"])
        self.assertEqual(out["semantic_change_count"], 0)
        self.assertTrue(out["lkg_reference_required"])
        self.assertTrue(out["lkg_reference_available"])
        self.assertFalse(out["lkg_reference_is_current_truth"])
        self.assertFalse(out["market_watch_candidate"])
        self.assertFalse(out["pipeline_watch_candidate"])

    def test_recovery_from_degraded_previous_is_baseline_refresh(self):
        degraded_previous = copy.deepcopy(self.previous)
        degraded_previous["source_health_state"] = "DEGRADED"
        degraded_previous["healthy_source_count"] = 4
        degraded_previous["degraded_source_count"] = 1
        out = rec.reconcile(self.current, degraded_previous)
        self.assertEqual(out["reconciliation_state"], "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING")
        self.assertTrue(out["semantic_reconciliation_passed"])
        self.assertTrue(out["source_health_watch_candidate"])
        self.assertFalse(out["market_watch_candidate"])
        self.assertFalse(out["pipeline_watch_candidate"])

    def test_identity_drift_is_rejected(self):
        bad = copy.deepcopy(self.previous)
        bad["evidence"][0]["authority_url"] = "https://eismea.ec.europa.eu/drift"
        with self.assertRaises(ValueError):
            rec.reconcile(self.current, bad)

    def test_previous_must_be_strictly_older(self):
        newer = copy.deepcopy(self.previous)
        newer["fetched_at"] = "2026-09-06T07:00:00+00:00"
        with self.assertRaises(ValueError):
            rec.reconcile(self.current, newer)

    def test_open_or_material_flags_cannot_widen(self):
        bad = copy.deepcopy(self.current)
        bad["open_call_authorized"] = True
        with self.assertRaises(ValueError):
            rec.reconcile(bad, self.previous)


if __name__ == "__main__":
    unittest.main()
