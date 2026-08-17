#!/usr/bin/env python3
"""Compatibility entry point for the semantic-quality MIPE browser collector.

Before importing the collector, apply the small dossier-readiness extension
idempotently. Then extend the Romanian browser frontier with the official MIPE
consolidated calls calendar while preserving the collector's existing semantic
quality and provenance gates.
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
import mipe_browser_ingest_v2 as collector  # noqa: E402  (import after patch)
from mipe_frontier_config import extend_frontier  # noqa: E402

extend_frontier(collector)
main = collector.main


if __name__ == "__main__":
    raise SystemExit(main())
