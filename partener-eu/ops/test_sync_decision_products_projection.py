#!/usr/bin/env python3
"""Regression: authoritative overlays must refresh projection quality counters."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "sync_decision_products_projection.py"

spec = importlib.util.spec_from_file_location("sync_decision_products_projection", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def dossier(dossier_id: str) -> dict:
    return {
        "id": dossier_id,
        "title": dossier_id,
        "status": "REVIEW",
        "publicationState": "PUBLISHABLE",
        "quality": {
            "completeness": 50,
            "applicantListPolicy": "GUIDE_EXPLICIT_ONLY",
            "executiveSummaryPresent": True,
        },
        "executiveSummary": {"status": "REVIEW"},
        "quickFacts": [
            {"label": "Completitudine critică", "value": "0%", "confidence": "SYSTEM"},
        ],
    }


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    products = root / "decision_products.json"
    out_js = root / "decision-products.js"
    payload = {
        "generatedAt": "2026-09-22T07:53:01+00:00",
        "dossiers": [dossier("base"), dossier("authoritative-overlay")],
        "news": [],
        "qualityPass": {
            # Simulate finalize_decision_products.py having run before the overlay.
            "executiveSummaryCoverage": 1,
            "strictApplicantListCoverage": 1,
        },
        "home": {},
    }
    products.write_text(json.dumps(payload), encoding="utf-8")
    module.PRODUCTS = products
    module.OUT_JS = out_js

    assert module.main() == 0
    refreshed = json.loads(products.read_text(encoding="utf-8"))
    assert refreshed["qualityPass"]["executiveSummaryCoverage"] == 2
    assert refreshed["qualityPass"]["strictApplicantListCoverage"] == 2
    assert refreshed["summary"]["dossierCount"] == 2
    assert all(
        row["quickFacts"][0]["value"] == "50%"
        for row in refreshed["dossiers"]
    )

print(json.dumps({"ok": True, "regression": "post-overlay-quality-counters"}))
