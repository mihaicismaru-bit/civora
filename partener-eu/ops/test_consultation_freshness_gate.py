#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ops" / "build_public_static_pages.py"
spec = importlib.util.spec_from_file_location("build_public_static_pages", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

clock = module.parse_date("2026-09-23T15:20:00Z")
assert clock is not None

def dossier(deadline, confidence="CONFIRMED"):
    return {
        "id": "consultation-probe",
        "title": "Consultation probe",
        "programme": "TEST",
        "publicationState": "PUBLISHABLE",
        "status": "PUBLIC_CONSULTATION",
        "statusLabel": "ÎN CONSULTARE",
        "quickFacts": [
            {"label": "Status", "value": "PUBLIC_CONSULTATION", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": deadline, "confidence": confidence},
        ],
    }

expired = dossier("8 septembrie 2026")
assert module.current_consultation(expired, clock) is False
assert module.requires_consultation_refresh(expired, clock) is True
rendered = module.fail_closed_render_dossier(expired, clock)
assert rendered["status"] == "REVIEW"
assert rendered["statusLabel"] == "ÎN VERIFICARE"

unknown = dossier("Neconfirmat", "UNKNOWN")
assert module.current_consultation(unknown, clock) is False
assert module.requires_consultation_refresh(unknown, clock) is True

current = dossier("29 septembrie 2026")
assert module.current_consultation(current, clock) is True
assert module.requires_consultation_refresh(current, clock) is False
assert module.fail_closed_render_dossier(current, clock)["status"] == "PUBLIC_CONSULTATION"

print("PARTENER.EU consultation freshness gate regression: PASS")
