#!/usr/bin/env python3
"""Enrich MIPE page items with text extracted from their official documents.

The dossier engine historically consumes mipe_state.json. The Windows v3 crawler
stores richer document evidence in mipe_ro_corpus.json. This bridge attaches a
bounded, source-labelled document evidence block to each page item so guide
PDF/DOCX content participates in the same downstream dossier extraction without
changing source provenance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "partener-eu/ingest/state/mipe_state.json"
CORPUS = ROOT / "partener-eu/ingest/state/mipe_ro_corpus.json"

MAX_DOC_TEXT_PER_PAGE = 100_000
MAX_DOCS_PER_PAGE = 12


def read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    state = read(STATE, {})
    corpus = read(CORPUS, {})
    docs = {d.get("url"): d for d in corpus.get("documents", []) if d.get("url")}
    pages = {p.get("url"): p for p in corpus.get("pages", []) if p.get("url")}
    enriched = 0
    extracted_docs = 0

    for item in state.get("items", []):
        page = pages.get(item.get("url"))
        if not page:
            continue
        evidence = []
        chunks = []
        used = 0
        for ref in (page.get("documents") or [])[:MAX_DOCS_PER_PAGE]:
            doc = docs.get(ref.get("url"))
            if not doc or not doc.get("sha256"):
                continue
            row = {
                "name": doc.get("name") or ref.get("name"),
                "url": doc.get("url"),
                "sha256": doc.get("sha256"),
                "bytes": doc.get("bytes"),
                "contentType": doc.get("contentType"),
                "extraction": doc.get("extraction"),
                "observedAt": doc.get("observedAt"),
                "tier": "T1",
                "verification": "CANONICAL_OFFICIAL_FETCH",
            }
            evidence.append(row)
            text = str(doc.get("textPreview") or "").strip()
            if text and used < MAX_DOC_TEXT_PER_PAGE:
                room = MAX_DOC_TEXT_PER_PAGE - used
                fragment = text[:room]
                chunks.append(f"\n\n[DOCUMENT OFICIAL: {row['name']}]\n{fragment}")
                used += len(fragment)
                extracted_docs += 1
        item["documentEvidence"] = evidence
        item["documentEvidenceHash"] = hashlib.sha256(
            "\n".join(f"{x.get('url')}|{x.get('sha256')}" for x in evidence).encode()
        ).hexdigest() if evidence else None
        if chunks:
            base = str(item.get("textPreview") or item.get("summary") or "")
            item["pageTextPreview"] = base
            item["textPreview"] = (base + "".join(chunks))[:180_000]
            enriched += 1

    run = state.setdefault("lastRun", {})
    run["documentEvidencePages"] = enriched
    run["extractedDocumentsUsedForDossiers"] = extracted_docs
    run["corpusPageCount"] = len(corpus.get("pages", []))
    run["corpusDocumentCount"] = len(corpus.get("documents", []))
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "enrichedPages": enriched,
        "extractedDocumentsUsed": extracted_docs,
        "corpusPages": run["corpusPageCount"],
        "corpusDocuments": run["corpusDocumentCount"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
