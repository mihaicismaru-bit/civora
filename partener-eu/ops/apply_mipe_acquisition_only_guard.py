#!/usr/bin/env python3
"""One-time Phase 8 migration: stop MIPE v3 crawler after raw corpus handoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "partener-eu/ingest/mipe_windows_crawl_v3.py"

old = '''    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)\n    CORPUS_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")\n\n    prior_items = {i.get("url"): i for i in previous_state.get("items", []) if i.get("url")}\n'''
new = '''    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)\n    CORPUS_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")\n\n    if os.getenv("MIPE_ACQUISITION_ONLY", "").strip().lower() in {"1", "true", "yes"}:\n        print(json.dumps({\n            "status": corpus["status"], "acquisitionOnly": True,\n            "pagesVisited": len(seen), "freshPages": len(pages),\n            "corpusPages": len(corpus["pages"]), "documents": len(corpus["documents"]),\n            "frontierPersisted": len(frontier),\n        }, ensure_ascii=False, indent=2))\n        return 0 if source_available else 2\n\n    prior_items = {i.get("url"): i for i in previous_state.get("items", []) if i.get("url")}\n'''

text = TARGET.read_text(encoding="utf-8")
if new in text:
    print("MIPE acquisition-only guard already present")
    raise SystemExit(0)
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one crawler projection boundary, found {text.count(old)}")
TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
print("MIPE acquisition-only guard materialized")
