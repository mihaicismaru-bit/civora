#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from candidate_staging import candidate_id, normalize_url, stage_candidates, validate_staging_ledger  # noqa: E402


class CandidateStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))

    def test_url_normalization_removes_tracking_and_www(self):
        a = "http://www.afir.ro/x/?utm_source=a&b=2&a=1#fragment"
        self.assertEqual(normalize_url(a), "https://afir.ro/x?a=1&b=2")

    def test_candidate_id_is_stable_across_cosmetic_url_variants(self):
        a = {"source_url": "https://www.oirbi.ro/pids-2021-2027/?utm_source=x"}
        b = {"source_url": "http://oirbi.ro/pids-2021-2027"}
        self.assertEqual(candidate_id(a), candidate_id(b))

    def test_unique_url_matches_canonical(self):
        ledger = stage_candidates(self.bundle, [{"source_url": "https://www.oirbi.ro/pids-2021-2027/"}], "2026-08-12T12:00:00Z")
        self.assertEqual(ledger["rows"][0]["canonical_match_id"], "pids-supported-decision")
        self.assertEqual(ledger["rows"][0]["disposition"], "CANONICAL_MATCH")

    def test_duplicate_occurrences_collapse(self):
        item = {"source_url": "https://oirvest.ro/ghiduri-peo/"}
        ledger = stage_candidates(self.bundle, [item, dict(item)], "2026-08-12T12:00:00Z")
        self.assertEqual(len(ledger["rows"]), 1)
        self.assertEqual(ledger["rows"][0]["occurrence_count"], 2)

    def test_new_candidate_is_never_published(self):
        item = {"source_url": "https://example.gov.ro/new-call", "programme": "Program nou", "code": "X.1", "title": "Apel nou"}
        ledger = stage_candidates(self.bundle, [item], "2026-08-12T12:00:00Z")
        self.assertEqual(ledger["rows"][0]["disposition"], "NEW_CANDIDATE")
        self.assertFalse(ledger["rows"][0]["publication_allowed"])
        validate_staging_ledger(ledger)

    def test_conflicting_duplicate_payloads_require_review(self):
        items = [
            {"source_url": "https://example.gov.ro/new-call", "title": "Titlul A"},
            {"source_url": "https://example.gov.ro/new-call", "title": "Titlul B"},
        ]
        ledger = stage_candidates(self.bundle, items, "2026-08-12T12:00:00Z")
        self.assertEqual(ledger["rows"][0]["disposition"], "AMBIGUOUS_REVIEW")
        self.assertIsNone(ledger["rows"][0]["canonical_match_id"])
        self.assertFalse(ledger["rows"][0]["publication_allowed"])

    def test_input_order_does_not_change_ledger_hash(self):
        items = [{"source_url": "https://example.gov.ro/b"}, {"source_url": "https://example.gov.ro/a"}]
        left = stage_candidates(self.bundle, items, "2026-08-12T12:00:00Z")
        right = stage_candidates(self.bundle, list(reversed(items)), "2026-08-12T12:00:00Z")
        self.assertEqual(left["ledger_sha256"], right["ledger_sha256"])


if __name__ == "__main__":
    unittest.main()
