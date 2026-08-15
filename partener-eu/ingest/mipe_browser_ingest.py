#!/usr/bin/env python3
"""Compatibility entry point for the semantic-quality MIPE browser collector.

Before importing the collector, apply the small dossier-readiness extension
idempotently. This keeps the Windows runner workflow simple while ensuring every
future MIPE page carries enough page-specific evidence for the site engine to
build a useful news item and a universal funding dossier.
"""
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("mipe_browser_ingest_v2.py")


def ensure_decision_evidence() -> None:
    text = MODULE_PATH.read_text(encoding="utf-8")
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
        return
    if old not in text:
        raise RuntimeError("MIPE collector structure changed; refusing blind dossier-evidence patch")
    MODULE_PATH.write_text(text.replace(old, new, 1), encoding="utf-8")


ensure_decision_evidence()
from mipe_browser_ingest_v2 import main  # noqa: E402  (import after patch)


if __name__ == "__main__":
    raise SystemExit(main())
