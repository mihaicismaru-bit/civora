#!/usr/bin/env python3
"""Apply small, idempotent source corrections to Consultant Workspace v3."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        "if(!dataGate(call.cofinancing).state==='PASS')unknowns.push('Cofinanțare neextrasă');",
        "if(dataGate(call.cofinancing).state!=='PASS')unknowns.push('Cofinanțare neextrasă');",
        "cofinancing unknown-state comparison",
    ),
    (
        "state.selectedClientId=state.clients[0]?.id||null;state.tab='dashboard';persist();renderWorkspace()};\n root.querySelectorAll('[data-cw3-remove-demo]')",
        "state.selectedClientId=state.clients[0]?.id||null;state.tab='dashboard';persist();renderWorkspace()});\n root.querySelectorAll('[data-cw3-remove-demo]')",
        "delete-client forEach closure",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"Consultant v3 {label}: already fixed")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"Consultant v3 {label}: fixed")
    else:
        raise SystemExit(f"Expected Consultant v3 source pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
