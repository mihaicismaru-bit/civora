#!/usr/bin/env python3
"""Derive targeted MIPE follow-up seeds from incomplete canonical dossiers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / "partener-eu/ingest/state/dossier_enrichment_queue.json"
CANONICAL = ROOT / "partener-eu/ingest/state/mipe_canonical_calls.json"
CORPUS = ROOT / "partener-eu/ingest/state/mipe_ro_corpus.json"
OUT = ROOT / "partener-eu/ingest/state/mipe_enrichment_seeds.json"

URL_RE = re.compile(r"https://(?:www\.)?mfe\.gov\.ro/[^\s\"'<>\]\[)]+", re.I)
DOC_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|zip|rar|7z)(?:\?.*)?$", re.I)
BARE_PATHS = {
    "/ghiduri", "/ghiduri/", "/ghiduri-", "/ghiduri_",
    "/ghiduri-ms", "/ghiduri-ms/", "/ghiduri_peos", "/ghiduri_peos/",
    "/ghiduri_pids", "/ghiduri_pids/",
}


def clean_url(value: str) -> str:
    return value.rstrip(".,;:!?)}]").replace("http://", "https://")


def useful(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = (parsed.path or "/").lower()
    low = url.lower()
    if host != "mfe.gov.ro" or DOC_RE.search(low):
        return False
    if path in BARE_PATHS or len(path.strip("/")) < 12:
        return False
    return any(token in low for token in (
        "/ghiduri_", "/ghiduri-", "/ghiduri/", "/ghiduri-ms/", "/pdds/",
        "/peo-", "/poids-", "/pids-", "/programul-sanatate-", "/pnrr-",
    ))


def main() -> int:
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    pages = {p.get("url"): p for p in corpus.get("pages") or [] if p.get("url")}
    docs = {d.get("url"): d for d in corpus.get("documents") or [] if d.get("url")}
    already = set(pages)
    by_id = {c.get("id"): c for c in canonical.get("calls") or []}
    rows = []
    seen = set()

    for q in queue.get("queue") or []:
        if not str(q.get("sourceType") or "").startswith("MIPE"):
            continue
        call = by_id.get(q.get("dossierId"))
        if not call:
            continue
        group = call.get("canonicalGroup") or {}
        texts = []
        for url in group.get("pageUrls") or []:
            page = pages.get(url)
            if page:
                texts.append(str(page.get("textPreview") or page.get("summary") or ""))
        for url in group.get("documentUrls") or []:
            doc = docs.get(url)
            if doc:
                texts.append(str(doc.get("textPreview") or ""))
        found = []
        for text in texts:
            for raw in URL_RE.findall(text):
                url = clean_url(raw)
                if url in already or url in seen or not useful(url):
                    continue
                seen.add(url)
                found.append(url)
        for url in found[:12]:
            rows.append({
                "url": url,
                "dossierId": q.get("dossierId"),
                "title": q.get("title"),
                "missing": q.get("missing") or [],
                "priority": q.get("priority") or 0,
                "reason": "EMBEDDED_OFFICIAL_GUIDE_OR_CALL_URL",
            })

    rows.sort(key=lambda r: (-int(r.get("priority") or 0), r.get("title") or "", r["url"]))
    payload = {
        "schemaVersion": 1,
        "generatedAt": queue.get("generatedAt"),
        "policy": {
            "officialHostOnly": True,
            "documentsAreFetchedFromParentPages": True,
            "unseenUrlsFirst": True,
            "rejectMalformedSeeds": True,
            "failClosed": True,
        },
        "summary": {
            "queuedDossiers": len(queue.get("queue") or []),
            "targetedSeeds": len(rows),
        },
        "seeds": rows[:120],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
