#!/usr/bin/env python3
"""Fix the cofinancing unknown-state comparison in Consultant Workspace v3."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
text = PATH.read_text(encoding="utf-8")
old = "if(!dataGate(call.cofinancing).state==='PASS')unknowns.push('Cofinanțare neextrasă');"
new = "if(dataGate(call.cofinancing).state!=='PASS')unknowns.push('Cofinanțare neextrasă');"
if new in text:
    print("Consultant v3 cofinancing gate already fixed")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Consultant v3 cofinancing gate fixed")
else:
    raise SystemExit("Expected Consultant v3 gate expression not found; refusing blind edit")
