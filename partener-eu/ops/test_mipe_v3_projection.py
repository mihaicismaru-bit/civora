#!/usr/bin/env python3
"""Offline regression for the MIPE v3 corpus -> PARTENER state projection."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu/ingest/project_mipe_v3_corpus.py"
spec = importlib.util.spec_from_file_location("project_mipe_v3_corpus", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

OBS = "2026-08-22T13:00:00+00:00"
OLD = "2026-08-22T10:00:00+00:00"

corpus = {
    "schemaVersion": 3,
    "source": "MIPE",
    "generatedAt": OBS,
    "frontierVersion": 1,
    "frontier": [{"url": "https://mfe.gov.ro/next/", "depth": 1}],
    "lastRun": {
        "observedAt": OBS,
        "collectorVersion": "3.0",
        "sourceAvailable": True,
        "roots": [{"root": "https://mfe.gov.ro/", "ok": True}],
        "pagesVisited": 4,
        "acceptedPages": 1,
        "documentsObserved": 1,
        "runtimeSeconds": 12.5,
        "deadlineReached": False,
        "frontierVersion": 1,
        "frontierPersisted": 1,
        "resumedFrontier": 0,
        "transport": "playwright-edge-direct-romania-v3",
    },
    "pages": [
        {
            "id": "fresh",
            "url": "https://mfe.gov.ro/apel-test/",
            "title": "Apel test",
            "programme": "PEO",
            "pageClass": "CALL_OR_GUIDE",
            "kind": "CALL_OPENED",
            "summary": "Rezumat oficial",
            "textPreview": "Text oficial suficient pentru proiecție",
            "documents": [{"url": "https://mfe.gov.ro/doc.pdf", "name": "doc"}],
            "contentHash": "a" * 64,
            "tier": "T1",
            "source": "MIPE",
            "observedAt": OBS,
            "retrievalTransport": "playwright-edge-direct-romania-v3",
            "verification": "CANONICAL_OFFICIAL_FETCH",
        },
        {
            "id": "older-corpus-only",
            "url": "https://mfe.gov.ro/older/",
            "title": "Older corpus page",
            "programme": "MIPE",
            "pageClass": "OFFICIAL_UPDATE",
            "kind": "OFFICIAL_UPDATE",
            "summary": "Older",
            "textPreview": "Older official text",
            "documents": [],
            "contentHash": "b" * 64,
            "observedAt": OLD,
            "retrievalTransport": "playwright-edge-direct-romania-v3",
            "verification": "CANONICAL_OFFICIAL_FETCH",
        },
    ],
    "documents": [
        {
            "url": "https://mfe.gov.ro/doc.pdf",
            "sha256": "c" * 64,
            "verification": "CANONICAL_OFFICIAL_FETCH",
        }
    ],
}
previous = {
    "status": "OK",
    "items": [
        {
            "id": "previous-item",
            "url": "https://mfe.gov.ro/previous/",
            "title": "Previous",
            "observedAt": OLD,
            "verification": "CANONICAL_OFFICIAL_FETCH",
        }
    ],
    "runs": [
        {"observedAt": OLD, "collectorVersion": "3.0"},
        {"observedAt": OBS, "collectorVersion": "3.0", "replayDuplicate": True},
    ],
}

state, meta = module.build_projection(corpus, previous)
assert state["status"] == "OK"
assert state["lastRun"]["parsedRelevantCount"] == 1
assert state["lastRun"]["candidateCount"] == 4
assert state["lastRun"]["directSuccessCount"] == 1
assert state["lastRun"]["collectorVersion"] == "3.0"
assert len(state["items"]) == 2
assert state["items"][0]["url"] == "https://mfe.gov.ro/previous/"
fresh = next(x for x in state["items"] if x["url"] == "https://mfe.gov.ro/apel-test/")
assert fresh["tier"] == "T1"
assert fresh["verification"] == "CANONICAL_OFFICIAL_FETCH"
assert fresh["dateConfidence"] == "OBSERVED_ONLY"
assert not any(x["url"] == "https://mfe.gov.ro/older/" for x in state["items"])
assert sum(1 for x in state["runs"] if x.get("observedAt") == OBS) == 1
assert meta["corpusPages"] == 2 and meta["corpusDocuments"] == 1
feed = module.render_feed(state, meta)
assert "window.PARTENER_DATA.mipeIngestion=" in feed
assert "window.PARTENER_DATA.mipeNews=" in feed
assert "https://mfe.gov.ro/apel-test/" in feed

bad = dict(corpus)
bad["pages"] = [dict(corpus["pages"][0], url="https://example.com/not-official")]
try:
    module.build_projection(bad, previous)
except ValueError:
    pass
else:
    raise AssertionError("non-official corpus page must fail closed")

print("MIPE v3 corpus projection regression: PASS")
