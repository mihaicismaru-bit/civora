#!/usr/bin/env python3
"""Regression tests for AFIR URL normalization."""

import importlib.util
import pathlib
import unittest
import urllib.parse

MODULE_PATH = pathlib.Path(__file__).with_name("afir_ingest.py")
SPEC = importlib.util.spec_from_file_location("afir_ingest", MODULE_PATH)
afir_ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(afir_ingest)


class AfirUrlNormalizationTests(unittest.TestCase):
    def test_document_query_requires_url_safe_encoding(self):
        raw = "https://www.afir.ro/api/file?filename=Ghid Solicitant DR-12 – sesiune 2026.pdf"
        normalized = afir_ingest.norm(raw)
        self.assertIsNotNone(normalized)
        self.assertNotIn(" ", normalized)
        parsed = urllib.parse.urlsplit(normalized)
        self.assertEqual(parsed.scheme, "https")

    def test_authentication_surface_remains_rejected(self):
        raw = "https://www.afir.ro/umbraco/surface/authentication/LogIn?redirectUrl=%2Finfo-la-zi%2F"
        self.assertIsNone(afir_ingest.norm(raw))


if __name__ == "__main__":
    unittest.main()
