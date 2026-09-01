#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INGEST = HERE.parent / "ingest"
sys.path.insert(0, str(INGEST))

from eu_direct_ft_coverage_receipt import build_coverage_receipt, validate_coverage_receipt  # noqa: E402


def watch(stop_reason: str, *, pages_captured: int = 8, max_pages: int = 8):
    return {
        "schema": "PARTENER_EU_FT_PROGRAMME_COVERAGE_WATCH_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "BRUSSELS",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "fetched_at": "2026-09-01T15:00:00+00:00",
        "run_id": "RUN-1",
        "pagination": {
            "page_size": 25,
            "max_pages": max_pages,
            "pages_captured": pages_captured,
            "stop_reason": stop_reason,
        },
        "stats": {"raw_search_records": 200, "accepted_candidates": 125},
        "programme_family_counts": {"HORIZON_EUROPE": 74},
        "status_candidate_counts": {"Open": 125},
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }


class CoverageReceiptTests(unittest.TestCase):
    def test_max_pages_is_explicitly_truncated(self):
        source = watch("MAX_PAGES_REACHED")
        receipt = build_coverage_receipt(source)
        validate_coverage_receipt(receipt, source)
        self.assertFalse(receipt["coverage_complete"])
        self.assertTrue(receipt["pagination_truncated"])
        self.assertTrue(receipt["more_results_possible"])
        self.assertEqual(receipt["coverage_scope"], "BOUNDED_QUERY_SAMPLE_NON_AUTHORIZING")
        self.assertIn("lower-bound sample", receipt["interpretation"])
        self.assertFalse(receipt["open_call_authorized"])

    def test_partial_last_page_can_mark_complete_query_result(self):
        source = watch("PARTIAL_LAST_PAGE", pages_captured=4, max_pages=8)
        receipt = build_coverage_receipt(source)
        validate_coverage_receipt(receipt, source)
        self.assertTrue(receipt["coverage_complete"])
        self.assertFalse(receipt["pagination_truncated"])
        self.assertFalse(receipt["more_results_possible"])
        self.assertEqual(receipt["coverage_scope"], "COMPLETE_QUERY_RESULT_NON_AUTHORIZING")

    def test_empty_page_can_mark_complete_query_result(self):
        source = watch("EMPTY_PAGE", pages_captured=5, max_pages=8)
        receipt = build_coverage_receipt(source)
        validate_coverage_receipt(receipt, source)
        self.assertTrue(receipt["coverage_complete"])

    def test_repeated_page_is_truncated_fail_safe(self):
        source = watch("REPEATED_PAGE_SHA_FAIL_SAFE_STOP", pages_captured=3, max_pages=8)
        receipt = build_coverage_receipt(source)
        validate_coverage_receipt(receipt, source)
        self.assertFalse(receipt["coverage_complete"])
        self.assertTrue(receipt["more_results_possible"])

    def test_unknown_stop_reason_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown pagination stop reason"):
            build_coverage_receipt(watch("MAGIC_COMPLETE"))

    def test_upstream_authorization_fails_closed(self):
        source = watch("MAX_PAGES_REACHED")
        source["open_call_authorized"] = True
        with self.assertRaisesRegex(ValueError, "unsafe upstream watch authorization"):
            build_coverage_receipt(source)

    def test_receipt_hash_binding_is_enforced(self):
        source = watch("MAX_PAGES_REACHED")
        receipt = build_coverage_receipt(source)
        mutated = json.loads(json.dumps(source))
        mutated["stats"]["accepted_candidates"] = 126
        with self.assertRaisesRegex(ValueError, "not bound"):
            validate_coverage_receipt(receipt, mutated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
