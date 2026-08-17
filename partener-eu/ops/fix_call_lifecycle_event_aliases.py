#!/usr/bin/env python3
"""Teach the lifecycle registry the event names emitted by MIPE canonicalization."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "partener-eu/ingest/build_call_lifecycle.py"
text = PATH.read_text(encoding="utf-8")

replacements = {
    '    "CALL_CLOSED": "CLOSED",\n    "EVALUATION_STARTED": "EVALUATION",': '    "CALL_CLOSED": "CLOSED",\n    "EVALUATION_STARTED": "EVALUATION",\n    "EVALUATION_UPDATE": "EVALUATION",',
    '    "CONTRACTING_STARTED": "CONTRACTING",\n    "CONTRACTS_PUBLISHED": "CONTRACTING",': '    "CONTRACTING_STARTED": "CONTRACTING",\n    "CONTRACTING_UPDATE": "CONTRACTING",\n    "CONTRACTS_PUBLISHED": "CONTRACTING",',
    '    "CALL_OPENED": "OPEN",\n    "CALL_CLOSED": "CLOSED",': '    "CALL_OPENED": "OPEN",\n    "DEADLINE_EXTENDED": "OPEN",\n    "CALL_CLOSED": "CLOSED",',
}

changed = False
for old, new in replacements.items():
    if new in text:
        continue
    if old not in text:
        raise SystemExit(f"Lifecycle structure changed; missing patch anchor: {old!r}")
    text = text.replace(old, new, 1)
    changed = True

if changed:
    PATH.write_text(text, encoding="utf-8")
    print("Lifecycle event aliases added")
else:
    print("Lifecycle event aliases already present")
