#!/usr/bin/env python3
"""Regression: Romania-local explicit deadlines follow Europe/Bucharest DST."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "sync_decision_products_projection.py"
spec = importlib.util.spec_from_file_location("partener_projection_sync", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RomanianDeadlineTimezoneTests(unittest.TestCase):
    def check_utc(self, original: str, expected: str) -> None:
        parsed = module.parse_date(original)
        self.assertIsNotNone(parsed, original)
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed, datetime.fromisoformat(expected.replace("Z", "+00:00")))

    def test_romanian_local_winter_time(self) -> None:
        self.check_utc("2 noiembrie 2026, 16:00", "2026-11-02T14:00:00Z")

    def test_romanian_local_summer_time(self) -> None:
        self.check_utc("2 iulie 2026, 16:00", "2026-07-02T13:00:00Z")

    def test_naive_iso_in_winter_is_romanian_local(self) -> None:
        self.check_utc("2026-11-02T16:00:00", "2026-11-02T14:00:00Z")

    def test_naive_iso_in_summer_is_romanian_local(self) -> None:
        self.check_utc("2026-07-02T16:00:00", "2026-07-02T13:00:00Z")

    def test_explicit_offset_is_respected(self) -> None:
        self.check_utc("2026-11-02T16:00:00+02:00", "2026-11-02T14:00:00Z")
        self.check_utc("2026-07-02T16:00:00+03:00", "2026-07-02T13:00:00Z")

    def test_unknown_dates_never_become_open(self) -> None:
        for value in ("", "necunoscut", "neconfirmat", "unknown", "invalid date"):
            self.assertIsNone(module.parse_date(value))

    def test_open_gate_preserves_status_confidence(self) -> None:
        clock = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
        row = {"status": "OPEN", "publicationState": "PUBLISHABLE",
               "quickFacts": [{"label": "Status", "confidence": "CONFIRMED", "value": "DESCHIS"},
                              {"label": "Termen", "confidence": "CONFIRMED", "value": "2 noiembrie 2026, 16:00"}]}
        self.assertTrue(module.current_open(row, clock))
        row["quickFacts"][1]["confidence"] = "UNKNOWN"
        self.assertFalse(module.current_open(row, clock))


if __name__ == "__main__":
    unittest.main()
