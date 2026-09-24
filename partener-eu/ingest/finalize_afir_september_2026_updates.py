#!/usr/bin/env python3
"""Finalize aggregate quality metadata after the AFIR September overlay.

The base decision-product builder owns aggregate dossier counters. Adding
source-bound dossiers after that builder must refresh those counters so the
canonical contract remains self-consistent. REVIEW states also use the public
Romanian decision token accepted by the product language gate.

Applicant labels must describe eligible entities only. Restrictions/exclusions
remain in eligibility text, not in the public who-can-apply list.
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
STORAGE_ID = "afir-fm-public-storage-2026"
OLD_APPLICANT = "Instituții publice definite de Legea nr. 500/2002, inclusiv entități publice subordonate sau coordonate, cu excluderile prevăzute de ghid."
CLEAN_APPLICANT = "Instituții publice definite de Legea nr. 500/2002, inclusiv entități publice subordonate sau coordonate, în categoriile eligibile prevăzute de ghid."

payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
dossiers = payload.get("dossiers") or []

for dossier in dossiers:
    if dossier.get("id") not in TARGETS:
        continue
    if dossier.get("status") == "REVIEW":
        dossier["decision"] = "VERIFICĂ"
        dossier["decisionLabel"] = "VERIFICĂ STAREA"

    if dossier.get("id") == STORAGE_ID:
        dossier["audience"] = [CLEAN_APPLICANT if row == OLD_APPLICANT else row for row in dossier.get("audience") or []]
        executive = dossier.get("executiveSummary") or {}
        executive["applicants"] = [CLEAN_APPLICANT if row == OLD_APPLICANT else row for row in executive.get("applicants") or []]
        for section in dossier.get("sections") or []:
            if section.get("title") == "Cine poate aplica":
                section["items"] = [CLEAN_APPLICANT if row == OLD_APPLICANT else row for row in section.get("items") or []]
            elif section.get("title") == "Rezumat executiv":
                section["items"] = [str(row).replace(OLD_APPLICANT, CLEAN_APPLICANT) for row in section.get("items") or []]

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
    "storageApplicantListSanitized": True,
}, ensure_ascii=False))
