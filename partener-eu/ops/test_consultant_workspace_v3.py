#!/usr/bin/env python3
"""Static contract regression for Consultant Workspace v3."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "partener-eu" / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
js = (WEB / "consultant-workspace-v3.js").read_text(encoding="utf-8")
css = (WEB / "consultant-workspace-v3.css").read_text(encoding="utf-8")
onboarding_js = (WEB / "consultant-onboarding-v3.js").read_text(encoding="utf-8")
onboarding_css = (WEB / "consultant-onboarding-v3.css").read_text(encoding="utf-8")

required_index = [
    'consultant-workspace-v3.css',
    'consultant-workspace-v3.js',
    'consultant-onboarding-v3.css',
    'consultant-onboarding-v3.js',
]
for token in required_index:
    assert token in index, f"index missing {token}"

# V2 is retained only as a migration data key inside v3. Loading both runtime
# modules creates competing MutationObservers and can replace the active view.
assert 'consultant-workspace-v2.js' not in index, 'v2 runtime must not be loaded beside v3'
assert 'consultant-workspace-v2.css' not in index, 'v2 styles must not override v3'

required_js = [
    "indexedDB",
    "Opportunity Radar",
    "Hard gates automate",
    "Verificare consultant",
    "Compară oportunități",
    "Documente client",
    "Plan de lucru",
    "Backup și portabilitate",
    "T1",
    "CANDIDAT DIRECT",
    "NEPOTRIVIRE CUNOSCUTĂ",
    "GO PENTRU PREGĂTIRE",
    "NO-GO / BLOCAT",
    "PARTENER.EU_CONSULTANT_WORKSPACE_V3",
    "demoClientsRemoved",
    "Termen expirat / status de reconciliat",
]
for token in required_js:
    assert token in js, f"workspace missing capability: {token}"

required_onboarding = [
    "De la client la decizia GO / NO-GO",
    "Creează profilul clientului",
    "Analizează Opportunity Radar",
    "Deschide dosarul apelului",
    "Transformă analiza în lucru",
    "Cum funcționează",
]
for token in required_onboarding:
    assert token in onboarding_js, f"onboarding missing: {token}"

assert "localStorage" in js and "documents" in js
assert "if(!dataGate(call.cofinancing).state==='PASS')" not in js
assert "state.tab='dashboard';persist();renderWorkspace()};\n root.querySelectorAll('[data-cw3-remove-demo]')" not in js
assert "cw3Root" in css and "cw3DossierGrid" in css and "cw3CompareTable" in css
assert "cw3OnboardingBackdrop" in onboarding_css and "cw3OnboardingSteps" in onboarding_css
assert len(js) > 20000, "workspace v3 unexpectedly small"
assert len(css) > 8000, "workspace v3 styles unexpectedly small"
assert len(onboarding_js) > 2500, "onboarding runtime unexpectedly small"
print("Consultant Workspace v3 static contract: PASS")
