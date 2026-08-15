#!/usr/bin/env python3
"""Ensure every source object classified as a call/guide receives a dossier."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "build_decision_products.py"
text = PATH.read_text(encoding="utf-8")
changed = False

old_afir = '''def afir_page_class(item: dict[str, Any]) -> str:
    value = norm_text(f"{item.get('title')} {item.get('url')}")
'''
new_afir = '''def afir_page_class(item: dict[str, Any]) -> str:
    explicit = str(item.get("pageClass") or "").upper()
    if explicit in {"INTERVENTION_OR_CALL", "SESSION", "GUIDE", "CALL_CANDIDATE", "DOCUMENT"}:
        return explicit
    value = norm_text(f"{item.get('title')} {item.get('url')}")
'''

old_mipe = '''def mipe_call_like(item: dict[str, Any]) -> bool:
    if item.get("kind") in CALL_EVENT_KINDS:
        return True
    value = norm_text(f"{item.get('title')} {item.get('url')}")
    return any(token in value for token in ("apel", "ghid", "step lll", "step vet", "universitati deschise", "interventie"))
'''
new_mipe = '''def mipe_call_like(item: dict[str, Any]) -> bool:
    if str(item.get("pageClass") or "").upper() in {"CALL_OR_GUIDE", "INTERVENTION_OR_CALL", "SESSION", "GUIDE", "CALL_CANDIDATE"}:
        return True
    if item.get("kind") in CALL_EVENT_KINDS:
        return True
    value = norm_text(f"{item.get('title')} {item.get('url')}")
    return any(token in value for token in ("apel", "ghid", "step lll", "step vet", "universitati deschise", "interventie"))
'''

for old, new, label in ((old_afir, new_afir, "AFIR classification"), (old_mipe, new_mipe, "MIPE classification")):
    if new in text:
        print(f"{label}: already applied")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"{label}: applied")
    else:
        raise SystemExit(f"Expected block missing for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
