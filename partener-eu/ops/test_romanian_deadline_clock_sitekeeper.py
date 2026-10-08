#!/usr/bin/env python3
"""Regression: Romanian written deadlines use the stated clock and Bucharest DST.

This is a deterministic renderer contract, not evidence that a source is OPEN.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "partener_static_clock", ROOT / "partener-eu" / "ops" / "build_public_static_pages.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

CASES = {
    "31 octombrie 2026, ora 16:00": "2026-10-31T14:00:00+00:00",
    "2 decembrie 2026, ora 16:00": "2026-12-02T14:00:00+00:00",
    "28 martie 2027, ora 16:00": "2027-03-28T13:00:00+00:00",
    "28 februarie 2027, ora 16:00": "2027-02-28T14:00:00+00:00",
    "17 iulie 2027, ora 16:00": "2027-07-17T13:00:00+00:00",
    "31 octombrie 2026": "2026-10-31T21:59:00+00:00",
    "2026-10-31T16:00:00+02:00": "2026-10-31T14:00:00+00:00",
}
for text, expected in CASES.items():
    parsed = module.parse_date(text)
    assert parsed is not None and parsed.isoformat() == expected, (text, parsed, expected)
assert module.parse_date("Neconfirmat") is None

dossier = {
    "status": "OPEN",
    "publicationState": "PUBLISHABLE",
    "quickFacts": [
        {"label": "Status", "value": "OPEN", "confidence": "CONFIRMED"},
        {"label": "Termen", "value": "31 octombrie 2026, ora 16:00", "confidence": "CONFIRMED"},
    ],
}
before = dt.datetime.fromisoformat("2026-10-31T13:59:59+00:00")
after = dt.datetime.fromisoformat("2026-10-31T14:00:01+00:00")
assert module.current_open(dossier, before) is True
assert module.current_open(dossier, after) is False
assert module.requires_open_refresh(dossier, after) is True
print("PASS: Romanian deadline + DST + OPEN expiry (10 contracts)")
