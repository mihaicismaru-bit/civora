#!/usr/bin/env python3
"""Regression for public lifecycle freshness using the render clock."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ops" / "build_public_static_pages.py"
spec = importlib.util.spec_from_file_location("build_public_static_pages", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    products = root / "decision_products.json"
    out = root / "web"
    products.write_text(
        json.dumps(
            {
                "generatedAt": "2026-09-30T12:45:00Z",
                "dossiers": [
                    {
                        "id": "render-clock-expiry-probe",
                        "title": "Render clock expiry probe",
                        "programme": "TEST",
                        "publicationState": "PUBLISHABLE",
                        "status": "OPEN",
                        "statusLabel": "DESCHIS",
                        "standfirst": "Apel deschis pana la termenul oficial.",
                        "decisionLabel": "ACTION",
                        "decisionAction": "Verifica si depune.",
                        "quickFacts": [
                            {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
                            {"label": "Termen", "value": "30 septembrie 2026, 16:00", "confidence": "CONFIRMED"},
                        ],
                        "sections": [],
                        "sources": [],
                    }
                ],
                "news": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    clock = module.parse_date("2026-09-30T13:05:00Z")
    assert clock is not None
    manifest = module.build(products, out, as_of=clock)
    assert manifest["currentOpen"] == 0
    assert manifest["failClosedOpenRefresh"] == 1
    assert manifest["lifecycleEvaluatedAt"] == clock.isoformat()
    open_html = (out / "finantari" / "deschise" / "index.html").read_text(encoding="utf-8")
    assert 'data-dossier-id="render-clock-expiry-probe"' not in open_html

print("PASS public render-clock expiry regression")
