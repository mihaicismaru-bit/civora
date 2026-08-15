#!/usr/bin/env python3
"""Move explicit call-launch detection ahead of generic guide detection.

This is intentionally idempotent. The MIPE workflow applies it before running
regressions and persists the patched source once, avoiding a manual full-file
replacement of a large generated adapter.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")

old = '''    if "consultare" in text and ("ghid" in text or "apel" in text):
        return "CONSULTATION_OPENED"
    if "ghid" in text and any(token in text for token in ("publicat", "aprobat", "final", "lansat")):
        return "GUIDE_PUBLISHED"
    if any(token in text for token in ("apelul este deschis", "apel deschis", "lansarea apelului", "s-a lansat apelul", "se lansează apelul", "se lanseaza apelul")):
        return "CALL_OPENED"
'''

new = '''    if "consultare" in text and ("ghid" in text or "apel" in text):
        return "CONSULTATION_OPENED"
    # An explicit call launch outranks generic mentions of a guide. Launch
    # pages commonly link the guide and would otherwise be misclassified as a
    # guide publication merely because both words appear in the same page.
    if any(token in text for token in ("apelul este deschis", "apel deschis", "lansarea apelului", "s-a lansat apelul", "se lansează apelul", "se lanseaza apelul")):
        return "CALL_OPENED"
    if "ghid" in text and any(token in text for token in ("publicat", "aprobat", "final", "lansat")):
        return "GUIDE_PUBLISHED"
'''

if new in text:
    print("MIPE classifier already patched")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("MIPE classifier patched")
else:
    raise SystemExit("Expected MIPE classifier block not found; refusing blind edit")
