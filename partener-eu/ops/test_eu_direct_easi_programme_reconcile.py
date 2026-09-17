#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

import eu_direct_easi_programme_intelligence as source_mod
import eu_direct_easi_programme_reconcile as rec_mod

REGISTRY_PATH = ROOT / "ingest" / "eu_direct_easi_programme_intelligence_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def fetch_for(suffix: str = ""):
    rows = {r["url"]: r for r in registry()["sources"]}
    def _fetch(url: str):
        src = rows[url]
        body = "<html><body>" + " ".join(src["required_markers"]) + suffix + "</body></html>"
        return body.encode("utf-8"), {
            "requested_url": url, "final_url": url, "http_status": 200,
            "content_type": "text/html; charset=utf-8",
        }
    return _fetch


def snapshot(run_id: str, fetched_at: str, suffix: str = ""):
    snap = source_mod.collect(registry(), run_id, fetcher=fetch_for(suffix))
    snap["fetched_at"] = fetched_at
    return snap


class EaSIReconcileTests(unittest.TestCase):
    def test_baseline_non_authorizing(self):
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00")
        rec = rec_mod.reconcile(cur)
        self.assertEqual(rec["reconciliation_state"], "BASELINE_CAPTURED_NON_AUTHORIZING")
        self.assertTrue(rec["semantic_reconciliation_passed"])
        self.assertEqual(rec["semantic_change_count"], 0)
        self.assertFalse(rec["pipeline_watch_candidate"])
        for flag in rec_mod.MATERIAL_FLAGS:
            self.assertFalse(rec[flag], flag)

    def test_same_identity_no_change(self):
        prev = snapshot("prev", "2026-09-03T09:00:00+00:00")
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00")
        rec = rec_mod.reconcile(cur, prev)
        self.assertEqual(rec["reconciliation_state"], "NO_CHANGE")
        self.assertEqual(rec["semantic_change_count"], 0)
        self.assertTrue(rec["previous_identity_match"])
        self.assertTrue(rec["lkg_reference_available"])
        self.assertFalse(rec["lkg_reference_is_current_truth"])

    def test_semantic_change_becomes_watch_only(self):
        prev = snapshot("prev", "2026-09-03T09:00:00+00:00")
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00", " new official programme wording")
        rec = rec_mod.reconcile(cur, prev)
        self.assertEqual(rec["reconciliation_state"], "EASI_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING")
        self.assertGreater(rec["semantic_change_count"], 0)
        self.assertTrue(rec["pipeline_watch_candidate"])
        self.assertFalse(rec["material_admission_ready_for_downstream_review"])
        for flag in rec_mod.MATERIAL_FLAGS:
            self.assertFalse(rec[flag], flag)

    def test_degraded_current_requires_lkg_and_never_compares_as_truth(self):
        prev = snapshot("prev", "2026-09-03T09:00:00+00:00")
        calls = {"n": 0}
        healthy = fetch_for()
        def flaky(url: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("synthetic transport failure")
            return healthy(url)
        cur = source_mod.collect(registry(), "cur", fetcher=flaky)
        cur["fetched_at"] = "2026-09-03T10:00:00+00:00"
        rec = rec_mod.reconcile(cur, prev)
        self.assertEqual(rec["reconciliation_state"], "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED")
        self.assertFalse(rec["semantic_reconciliation_passed"])
        self.assertEqual(rec["semantic_change_count"], 0)
        self.assertTrue(rec["lkg_reference_required"])
        self.assertTrue(rec["lkg_reference_available"])
        self.assertFalse(rec["lkg_reference_is_current_truth"])
        self.assertTrue(rec["source_health_watch_candidate"])
        self.assertFalse(rec["pipeline_watch_candidate"])

    def test_recovery_from_degraded_previous_refreshes_baseline(self):
        calls = {"n": 0}
        healthy = fetch_for()
        def flaky(url: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("synthetic transport failure")
            return healthy(url)
        prev = source_mod.collect(registry(), "prev", fetcher=flaky)
        prev["fetched_at"] = "2026-09-03T09:00:00+00:00"
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00")
        rec = rec_mod.reconcile(cur, prev)
        self.assertEqual(rec["reconciliation_state"], "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING")
        self.assertEqual(rec["semantic_change_count"], 0)
        self.assertTrue(rec["baseline_captured"])
        self.assertFalse(rec["pipeline_watch_candidate"])

    def test_identity_drift_rejected(self):
        prev = snapshot("prev", "2026-09-03T09:00:00+00:00")
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00")
        prev["evidence"][0]["authority_url"] = "https://european-social-fund-plus.ec.europa.eu/drift"
        with self.assertRaises(ValueError):
            rec_mod.reconcile(cur, prev)

    def test_future_previous_rejected(self):
        prev = snapshot("prev", "2026-09-03T11:00:00+00:00")
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00")
        with self.assertRaises(ValueError):
            rec_mod.reconcile(cur, prev)

    def test_previous_authorization_drift_rejected(self):
        prev = snapshot("prev", "2026-09-03T09:00:00+00:00")
        cur = snapshot("cur", "2026-09-03T10:00:00+00:00")
        prev["open_call_authorized"] = True
        with self.assertRaises(ValueError):
            rec_mod.reconcile(cur, prev)


if __name__ == "__main__":
    unittest.main()
