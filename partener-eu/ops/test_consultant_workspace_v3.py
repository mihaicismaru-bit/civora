#!/usr/bin/env python3
"""Static contract regression for Consultant Workspace v3."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "partener-eu" / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
js = (WEB / "consultant-workspace-v3.js").read_text(encoding="utf-8")
css = (WEB / "consultant-workspace-v3.css").read_text(encoding="utf-8")

required_index = [
    'consultant-workspace-v3.css',
    'consultant-workspace-v3.js',
]
for token in required_index:
    assert token in index, f"index missing {token}"

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
]
for token in required_js:
    assert token in js, f"workspace missing capability: {token}"

assert "localStorage" in js and "documents" in js
assert "cw3Root" in css and "cw3DossierGrid" in css and "cw3CompareTable" in css
assert len(js) > 20000, "workspace v3 unexpectedly small"
assert len(css) > 8000, "workspace v3 styles unexpectedly small"
print("Consultant Workspace v3 static contract: PASS")
