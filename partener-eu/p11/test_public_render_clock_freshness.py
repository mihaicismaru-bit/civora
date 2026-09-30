#!/usr/bin/env python3
"""Regression for render-time expiry of public OPEN calls."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ops" / "build_public_static_pages.py"

spec = importlib.util.spec_from_file_location("build_public_static_pages", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class PublicRenderClockFreshnessTest(unittest.TestCase):
    def test_render_clock_overrides_stale_product_timestamp_for_expiry(self) -> None:
        dossier = {
            "id": "render-clock-expiry-probe",
            "title": "Render clock expiry probe",
            "programme": "TEST",
            "publicationState": "PUBLISHABLE",
            "status": "OPEN",
            "statusLabel": "DESCHIS",
            "standfirst": "Apel deschis până la termenul oficial.",
            "decisionLabel": "ACȚIONEAZĂ",
            "decisionAction": "Verifică și depune.",
            "quickFacts": [
                {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
                {"label": "Termen", "value": "30 septembrie 2026, 16:00", "confidence": "CONFIRMED"},
            ],
            "sections": [],
            "sources": [],
        }
        stale_clock = module.parse_date("2026-09-30T12:45:00Z")
        render_clock = module.parse_date("2026-09-30T13:05:00Z")
        self.assertIsNotNone(stale_clock)
        self.assertIsNotNone(render_clock)
        self.assertTrue(module.current_open(dossier, stale_clock))
        self.assertFalse(module.current_open(dossier, render_clock))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            products = root / "decision_products.json"
            output = root / "web"
            products.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-09-30T12:45:00Z",
                        "dossiers": [dossier],
                        "news": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest = module.build(products, output, as_of=render_clock)
            self.assertEqual(manifest["currentOpen"], 0)
            self.assertEqual(manifest["failClosedOpenRefresh"], 1)
            self.assertEqual(manifest["lifecycleEvaluatedAt"], render_clock.isoformat())
            html = (output / "finantari" / "deschise" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn('data-dossier-id="render-clock-expiry-probe"', html)


if __name__ == "__main__":
    unittest.main()
