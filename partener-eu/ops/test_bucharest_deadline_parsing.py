#!/usr/bin/env python3
"""Regression: Romanian human-readable filing deadlines follow IANA DST.

Source status and confidence gates are intentionally unchanged. Until the
production parser fix is merged, this test is expected to fail (RED).
"""
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

UTC = dt.timezone.utc
BASE = Path(__file__).resolve().parents[1]


def load(relative):
    path = BASE / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROJECTION = load("ingest/sync_decision_products_projection.py")
STATIC = load("ops/build_public_static_pages.py")
SANITIZER = load("ops/sanitize_public_prepare_cards.py")


class BucharestDeadlineTests(unittest.TestCase):
    def test_local_deadline_to_utc(self):
        cases = (
            ("15 iulie 2026, ora 16:00", dt.datetime(2026, 7, 15, 13, tzinfo=UTC)),
            ("15 noiembrie 2026, ora 16:00", dt.datetime(2026, 11, 15, 14, tzinfo=UTC)),
            ("31 octombrie 2026, ora 16:00", dt.datetime(2026, 10, 31, 14, tzinfo=UTC)),
            ("2026-11-15T16:00:00+02:00", dt.datetime(2026, 11, 15, 14, tzinfo=UTC)),
        )
        for module in (PROJECTION, STATIC):
            for value, expected in cases:
                with self.subTest(module=module.__name__, value=value):
                    self.assertEqual(module.parse_date(value), expected)

    def test_unknown_and_unqualified_dates_fail_closed(self):
        for module in (PROJECTION, STATIC):
            self.assertIsNone(module.parse_date("Neconfirmat"))
            self.assertIsNone(module.parse_date("Necunoscut"))

    def test_day_end_considers_season(self):
        self.assertEqual(
            SANITIZER.end_of_day(2026, 7, 15),
            dt.datetime(2026, 7, 15, 20, 59, 59, tzinfo=UTC),
        )
        self.assertEqual(
            SANITIZER.end_of_day(2026, 10, 31),
            dt.datetime(2026, 10, 31, 21, 59, 59, tzinfo=UTC),
        )
        self.assertIsNone(SANITIZER.end_of_day(2026, 2, 30))

    def test_open_keeps_confidence_guard(self):
        verified = {
            "status": "OPEN",
            "publicationState": "PUBLISHABLE",
            "quickFacts": [
                {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
                {"label": "Termen", "value": "15 noiembrie 2026, ora 16:00", "confidence": "CONFIRMED"},
            ],
        }
        before = dt.datetime(2026, 11, 15, 13, 30, tzinfo=UTC)
        after = dt.datetime(2026, 11, 15, 14, 1, tzinfo=UTC)
        for module in (PROJECTION, STATIC):
            self.assertTrue(module.current_open(verified, before))
            self.assertFalse(module.current_open(verified, after))
            withheld = {**verified, "publicationState": "PROVISIONAL_FAIL_CLOSED"}
            self.assertFalse(module.current_open(withheld, before))
            unknown = {**verified, "quickFacts": [
                verified["quickFacts"][0],
                {"label": "Termen", "value": "Necunoscut", "confidence": "UNKNOWN"},
            ]}
            self.assertFalse(module.current_open(unknown, before))


if __name__ == "__main__":
    unittest.main()
