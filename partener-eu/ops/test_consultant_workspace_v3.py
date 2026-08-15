#!/usr/bin/env python3
"""Static and data-contract regression for Consultant Workspace v3."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "partener-eu" / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
js = (WEB / "consultant-workspace-v3.js").read_text(encoding="utf-8")
css = (WEB / "consultant-workspace-v3.css").read_text(encoding="utf-8")
onboarding_js = (WEB / "consultant-onboarding-v3.js").read_text(encoding="utf-8")
onboarding_css = (WEB / "consultant-onboarding-v3.css").read_text(encoding="utf-8")
mysmis_js = (WEB / "consultant-mysmis-v1.js").read_text(encoding="utf-8")
mysmis_css = (WEB / "consultant-mysmis-v1.css").read_text(encoding="utf-8")
registry_text = (WEB / "mysmis-registry.js").read_text(encoding="utf-8")

required_index = [
    'consultant-workspace-v3.css','consultant-workspace-v3.js',
    'consultant-onboarding-v3.css','consultant-onboarding-v3.js',
    'consultant-mysmis-v1.css','consultant-mysmis-v1.js','mysmis-registry.js',
]
for token in required_index:
    assert token in index, f"index missing {token}"

assert 'consultant-workspace-v2.js' not in index
assert 'consultant-workspace-v2.css' not in index
assert index.index('mipe-news.js') < index.index('mysmis-registry.js')
assert index.index('mysmis-registry.js') < index.index('consultant-mysmis-v1.js')
assert index.index('consultant-workspace-v3.js') < index.index('consultant-mysmis-v1.js')

required_js = [
    "indexedDB","Opportunity Radar","Hard gates automate","Verificare consultant",
    "Compară oportunități","Documente client","Plan de lucru","Backup și portabilitate",
    "T1","CANDIDAT DIRECT","NEPOTRIVIRE CUNOSCUTĂ","GO PENTRU PREGĂTIRE",
    "NO-GO / BLOCAT","PARTENER.EU_CONSULTANT_WORKSPACE_V3","demoClientsRemoved",
    "deletedClientIds","Termen expirat / status de reconciliat",
    "await persistNow();await renderWorkspace()","Document cleanup skipped during client deletion",
    "Ștergi din portofoliu","Consultant client save failed","Consultant client delete failed",
    "＋ Adaugă firmă / organizație",
]
for token in required_js:
    assert token in js, f"workspace missing capability: {token}"

assert "form.onsubmit=async" in js
assert "state.deletedClientIds=[...new Set" in js
assert "idbListDocuments(removedId)" in js
assert "state.clients=state.clients.filter(c=>c.id!==removedId)" in js
assert "deleted.has(raw.id)" in js

required_onboarding = [
    "De la client la decizia de pregătire sau renunțare","Creează profilul clientului",
    "Vezi oportunitățile potrivite","Deschide dosarul apelului",
    "Transformă analiza în plan de lucru","Cum funcționează","SESSION_KEY",
]
for token in required_onboarding:
    assert token in onboarding_js, f"onboarding missing: {token}"
assert "sessionStorage.setItem(SESSION_KEY,'1')" in onboarding_js
assert "close(false);setTimeout(()=>el.click(),0)" in onboarding_js
assert "Opportunity Radar" not in onboarding_js
assert "GO / NO-GO" not in onboarding_js
assert "hard-gates" not in onboarding_js

required_mysmis = [
    "D.mysmisRegistry","Evidență directă MySMIS","Verificare directă MySMIS",
    "Absența nu este dovadă că apelul nu există",
    "nu înlocuiește automat statusul canonic PARTENER.EU","source?.canonicalUrl",
]
for token in required_mysmis:
    assert token in mysmis_js, f"MySMIS Consultant adapter missing: {token}"

marker = 'window.PARTENER_DATA.mysmisRegistry='
assert marker in registry_text
payload = json.loads(registry_text.split(marker, 1)[1].rsplit(';', 1)[0])
assert payload.get('directOnly') is True
assert payload.get('status') in {'OK_DIRECT', 'UNAVAILABLE_FAIL_CLOSED'}
source = payload.get('source') or {}
assert urlparse(source.get('canonicalUrl', '')).hostname == 'reporting.mysmis2021.gov.ro'
assert source.get('trustClass') == 'T1'
if payload.get('status') == 'OK_DIRECT':
    assert source.get('retrieval') == 'CANONICAL_OFFICIAL_FETCH'
    assert payload.get('visibleRowCount') == len(payload.get('calls') or [])
    assert payload.get('calls')
    for row in payload['calls']:
        assert row.get('programme') and row.get('call') and row.get('officialStatus')
else:
    assert payload.get('calls') == []

assert "localStorage" in js and "documents" in js
assert "if(!dataGate(call.cofinancing).state==='PASS')" not in js
assert "cw3Root" in css and "cw3DossierGrid" in css and "cw3CompareTable" in css
assert ".cw3AddClient{" in css
assert "cw3OnboardingBackdrop" in onboarding_css and "cw3OnboardingSteps" in onboarding_css
assert "cw3MySMISSnapshot" in mysmis_css and "cw3MySMISEvidence" in mysmis_css
assert len(js) > 20000
assert len(css) > 8000
assert len(onboarding_js) > 2500
print("Consultant Workspace v3 CRUD + direct MySMIS evidence contract: PASS")
