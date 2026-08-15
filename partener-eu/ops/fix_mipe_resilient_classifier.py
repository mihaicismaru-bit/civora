#!/usr/bin/env python3
"""Move explicit call-launch detection ahead of generic guide detection.

This fix is intentionally idempotent across later editorial extensions of the
classifier. Once the launch-priority marker and ordering are present, it exits
successfully without requiring the surrounding guide rules to remain byte-for-
byte identical.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")

marker = "# An explicit call launch outranks generic mentions of a guide."
launch = '    if any(token in text for token in ("apelul este deschis", "apel deschis", "lansarea apelului", "s-a lansat apelul", "se lansează apelul", "se lanseaza apelul")):\n        return "CALL_OPENED"'
consultation = '    if "consultare" in text and ("ghid" in text or "apel" in text):\n        return "CONSULTATION_OPENED"'

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

if marker in text and consultation in text and launch in text and text.index(consultation) < text.index(launch):
    print("MIPE classifier already patched")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("MIPE classifier patched")
else:
    raise SystemExit("Expected MIPE classifier ordering not found; refusing blind edit")
