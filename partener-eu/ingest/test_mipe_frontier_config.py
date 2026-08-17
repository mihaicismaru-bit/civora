#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path(__file__).with_name("mipe_frontier_config.py")
spec = importlib.util.spec_from_file_location("mipe_frontier_config", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class MipeFrontierConfigTests(unittest.TestCase):
    def fake_collector(self):
        collector = SimpleNamespace()
        collector.SCOPES = ("/pdds/", "/ghiduri_peos/")
        collector.SEEDS = ["https://mfe.gov.ro/"]
        collector.KW = ["apel", "ghid"]

        def is_listing_url(url: str) -> bool:
            return url in collector.SEEDS

        collector.is_listing_url = is_listing_url
        return collector

    def test_calendar_is_explicit_root_and_decision_useful_item(self):
        collector = self.fake_collector()
        module.extend_frontier(collector)

        self.assertIn(module.CALENDAR_SCOPE, collector.SCOPES)
        self.assertIn(module.CALENDAR_URL, collector.SEEDS)
        self.assertIn("calendar", collector.KW)
        self.assertIn("lansar", collector.KW)
        self.assertFalse(collector.is_listing_url(module.CALENDAR_URL))
        self.assertTrue(collector.is_listing_url("https://mfe.gov.ro/"))

    def test_extension_is_idempotent(self):
        collector = self.fake_collector()
        module.extend_frontier(collector)
        first_scopes = collector.SCOPES
        first_seeds = list(collector.SEEDS)
        first_keywords = list(collector.KW)
        first_listing = collector.is_listing_url

        module.extend_frontier(collector)

        self.assertEqual(first_scopes, collector.SCOPES)
        self.assertEqual(first_seeds, collector.SEEDS)
        self.assertEqual(first_keywords, collector.KW)
        self.assertIs(first_listing, collector.is_listing_url)


if __name__ == "__main__":
    unittest.main()
