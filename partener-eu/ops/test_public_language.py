#!/usr/bin/env python3
"""Public-language regression for PARTENER.EU decision products."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
UI = ROOT / "partener-eu" / "web" / "decision-intelligence-v2.js"

payload = json.loads(DATA.read_text(encoding="utf-8"))
assert payload.get("policy", {}).get("romanianPublicLanguage") is True
assert payload.get("policy", {}).get("rawStructuredObjectsVisible") is False

forbidden_phrases = (
    "Eligible applicant",
    "Eligible applicants",
    "Mandatory institutional partner",
    "Minimum quality points",
    "Number of criteria",
    "Decision usefulness",
    "Funding intelligence",
)
allowed_decisions = {
    "ACȚIONEAZĂ",
    "PREGĂTEȘTE",
    "ANALIZEAZĂ / PREGĂTEȘTE",
    "REFERINȚĂ",
    "AȘTEAPTĂ",
    "VERIFICĂ",
    "MONITORIZEAZĂ",
}

for dossier in payload.get("dossiers") or []:
    assert dossier.get("decision") in allowed_decisions, f"English/internal decision label in {dossier.get('id')}: {dossier.get('decision')}"
    public_chunks = [
        dossier.get("title", ""),
        dossier.get("standfirst", ""),
        dossier.get("decisionAction", ""),
        *(dossier.get("audience") or []),
    ]
    for fact in dossier.get("quickFacts") or []:
        value = str(fact.get("value") or "")
        public_chunks.extend([str(fact.get("label") or ""), value])
        assert not (value.lstrip().startswith("{") or value.lstrip().startswith("[")), f"raw structured fact in {dossier.get('id')}: {value[:120]}"
        assert "':" not in value and "{'" not in value, f"Python dict leaked in {dossier.get('id')}: {value[:120]}"
        assert len(value) <= 500, f"mobile fact too long in {dossier.get('id')}: {len(value)}"
    for section in dossier.get("sections") or []:
        public_chunks.extend(section.get("items") or [])
    joined = "\n".join(str(x) for x in public_chunks)
    for phrase in forbidden_phrases:
        assert phrase.lower() not in joined.lower(), f"English schema phrase {phrase!r} in {dossier.get('id')}"

    programme = str(dossier.get("programme") or "")
    region = str(dossier.get("region") or "")
    if re.search(r"Regiunea\s+Centru|Regional\s+Centru", programme, re.I):
        assert region == "Regiunea Centru", f"regional geography mismatch: {programme} / {region}"

ui = UI.read_text(encoding="utf-8")
for phrase in forbidden_phrases:
    assert phrase not in ui, f"English UI phrase remains: {phrase}"
for token in ("eventLabel", "statusText", "fundingFact", "Finanțări europene · decizie și acțiune", "Utilitate pentru decizie"):
    assert token in ui, f"localized UI helper missing: {token}"

print(json.dumps({
    "status": "PASS",
    "dossiersChecked": len(payload.get("dossiers") or []),
    "policy": payload.get("policy"),
}, ensure_ascii=False, indent=2))
