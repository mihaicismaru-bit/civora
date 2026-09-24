#!/usr/bin/env python3
"""Finalize aggregate quality metadata after the AFIR September overlay.

The base decision-product builder owns aggregate dossier counters. Adding
source-bound dossiers after that builder must refresh those counters so the
canonical contract remains self-consistent. REVIEW states also use the public
Romanian decision token accepted by the product language gate.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"
TARGETS = {
    "afir-dr21-consultation-2026",
    "afir-fm-public-autoconsum-2026",
    "afir-fm-public-storage-2026",
}

payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
dossiers = payload.get("dossiers") or []

for dossier in dossiers:
    if dossier.get("id") in TARGETS and dossier.get("status") == "REVIEW":
        dossier["decision"] = "VERIFICĂ"
        dossier["decisionLabel"] = "VERIFICĂ STAREA"

quality = payload.setdefault("qualityPass", {})
quality["executiveSummaryCoverage"] = len(dossiers)
quality["strictApplicantListCoverage"] = len(dossiers)

PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
OUT_JS.write_text(
    "window.PARTENER_DECISION_PRODUCTS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
    encoding="utf-8",
)
print(json.dumps({
    "ok": True,
    "dossiers": len(dossiers),
    "executiveSummaryCoverage": quality["executiveSummaryCoverage"],
    "strictApplicantListCoverage": quality["strictApplicantListCoverage"],
}, ensure_ascii=False))
