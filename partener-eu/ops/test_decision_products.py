#!/usr/bin/env python3
"""Regression gate for automated PARTENER.EU decision products."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
JS = ROOT / "partener-eu" / "web" / "decision-products.js"
UI = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.js"
CSS = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.css"
P11 = ROOT / "partener-eu" / "web" / "p11-public-data.js"
CRITICAL = {"status", "deadline", "beneficiaries", "eligibility", "grant", "budget", "scoring"}

assert DATA.exists(), "decision_products.json missing"
assert JS.exists(), "decision-products.js missing"
assert UI.exists(), "decision-intelligence-v2.js missing"
assert CSS.exists(), "decision-intelligence-v2.css missing"

payload = json.loads(DATA.read_text(encoding="utf-8"))
assert payload.get("schemaVersion") == 1
assert payload.get("policy", {}).get("rawIngestionRowsAreNews") is False
assert payload.get("policy", {}).get("everyIdentifiedCallGetsDossier") is True
assert payload.get("policy", {}).get("failClosed") is True

dossiers = payload.get("dossiers") or []
news = payload.get("news") or []
assert dossiers, "no dossiers generated"
assert len({row["id"] for row in dossiers}) == len(dossiers), "duplicate dossier IDs"

match = re.search(r"window\.PARTENER_P11\s*=\s*(\{.*\})\s*;?\s*$", P11.read_text(encoding="utf-8"), re.S)
assert match, "cannot parse P11 projection"
p11 = json.loads(match.group(1))
p11_ids = {row["id"] for row in p11.get("opportunities") or []}
dossier_ids = {row["id"] for row in dossiers}
missing = sorted(p11_ids - dossier_ids)
assert not missing, f"P11 opportunities without dossiers: {missing[:10]}"

for dossier in dossiers:
    assert dossier.get("title"), dossier.get("id")
    assert dossier.get("decision"), dossier.get("id")
    assert dossier.get("decisionAction"), dossier.get("id")
    assert dossier.get("standfirst"), dossier.get("id")
    assert len(dossier.get("quickFacts") or []) >= 5, dossier.get("id")
    assert len(dossier.get("sections") or []) >= 9, dossier.get("id")
    quality = dossier.get("quality") or {}
    assert quality.get("failClosed") is True
    assert 0 <= quality.get("completeness", -1) <= 100

    sources = dossier.get("sources") or []
    verified = set(quality.get("verifiedFactClasses") or [])
    blocked = set(quality.get("blockedFactClasses") or [])
    if sources:
        for source in sources:
            assert source.get("url"), f"source without URL in {dossier.get('id')}"
    else:
        # A dossier may still exist as an explicit fail-closed shell when the
        # public projection does not expose its evidence links. In that state
        # no material fact may be presented as verified or actionable.
        assert dossier.get("publicationState") != "PUBLISHABLE", f"publishable dossier without provenance: {dossier.get('id')}"
        assert dossier.get("status") != "OPEN", f"OPEN dossier without provenance: {dossier.get('id')}"
        assert not (verified & CRITICAL), f"verified material facts without provenance: {dossier.get('id')}"
        assert blocked or quality.get("completeness", 100) == 0, f"unexplained provenance gap: {dossier.get('id')}"

    if dossier.get("status") == "OPEN":
        source_type = dossier.get("sourceType", "")
        assert sources, f"OPEN dossier without sources: {dossier.get('id')}"
        assert "status" in verified or source_type.endswith("PROVISIONAL"), f"OPEN without status evidence: {dossier.get('id')}"
    for section in dossier.get("sections") or []:
        assert section.get("title")
        assert section.get("items"), f"empty section in {dossier.get('id')}: {section.get('title')}"

for story in news:
    assert story.get("headline")
    assert story.get("standfirst")
    assert story.get("meaning")
    assert story.get("actions"), story.get("id")
    assert story.get("source", {}).get("url"), story.get("id")
    assert story.get("utilityScore", 0) >= 60, story.get("id")
    assert not re.fullmatch(r".*actualizare oficială.*", story.get("headline", ""), re.I), story.get("headline")

coverage = payload.get("coverage") or {}
for source in ("p11", "mipe", "afir"):
    assert source in coverage
if coverage.get("mipe", {}).get("candidates", 0):
    assert coverage["mipe"].get("matched", 0) + coverage["mipe"].get("provisional", 0) == coverage["mipe"]["candidates"]
if coverage.get("afir", {}).get("candidates", 0):
    assert coverage["afir"].get("matched", 0) + coverage["afir"].get("provisional", 0) == coverage["afir"]["candidates"]

js_text = JS.read_text(encoding="utf-8")
assert "window.PARTENER_DECISION_PRODUCTS=" in js_text
ui_text = UI.read_text(encoding="utf-8")
for token in ("Ce finanțare poți accesa", "Știri care explică", "Dosar complet", "Ce nu este confirmat"):
    assert token in ui_text, f"UI missing {token}"
css_text = CSS.read_text(encoding="utf-8")
for token in (".diDossierGrid", ".diNewsGrid", ".diDossierLayout", ".diQualityMeter"):
    assert token in css_text

print(json.dumps({
    "dossiers": len(dossiers),
    "news": len(news),
    "coverage": coverage,
}, ensure_ascii=False, indent=2))
