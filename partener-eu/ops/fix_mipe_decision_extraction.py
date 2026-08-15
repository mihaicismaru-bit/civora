#!/usr/bin/env python3
"""Idempotently preserve page-specific MIPE text for dossier automation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_browser_ingest_v2.py"
text = PATH.read_text(encoding="utf-8")
changed = False

old = '''                            "summary": summary,
                            "tag": classify_tag(f"{final} {title} {summary}"),
                            "kind": classify_kind(title, article_text),
                            "tier": "T1",
'''
new = '''                            "summary": summary,
                            "textPreview": article_text[:80000],
                            "pageClass": "CALL_OR_GUIDE" if classify_kind(title, article_text) != "OFFICIAL_UPDATE" else "OFFICIAL_UPDATE",
                            "tag": classify_tag(f"{final} {title} {summary}"),
                            "kind": classify_kind(title, article_text),
                            "tier": "T1",
'''
if new in text:
    print("MIPE decision text already retained")
elif old in text:
    text = text.replace(old, new, 1)
    changed = True
else:
    raise SystemExit("MIPE fresh item block not found")

if changed:
    PATH.write_text(text, encoding="utf-8")
    print("MIPE decision extraction patch applied")
