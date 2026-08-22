#!/usr/bin/env python3
"""Project a raw Romanian MIPE v3 acquisition corpus into PARTENER runtime state.

SURFACEMC/Windows acquisition owns only the official corpus. This module belongs
to the PARTENER engine boundary: it converts that immutable handoff into the
legacy-compatible MIPE state/feed consumed by downstream canonicalization and
product code. Replay of the same observedAt is idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "partener-eu/ingest/state/mipe_ro_corpus.json"
STATE_PATH = ROOT / "partener-eu/ingest/state/mipe_state.json"
FEED_PATH = ROOT / "partener-eu/web/mipe-news.js"


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except Exception:
        return fallback


def validate_corpus(corpus: dict[str, Any]) -> None:
    if corpus.get("schemaVersion") != 3:
        raise ValueError("MIPE v3 corpus schemaVersion must be 3")
    if corpus.get("source") != "MIPE":
        raise ValueError("MIPE v3 corpus source must be MIPE")
    run = corpus.get("lastRun") or {}
    if run.get("collectorVersion") != "3.0":
        raise ValueError("MIPE v3 collectorVersion must be 3.0")
    for page in corpus.get("pages") or []:
        url = str(page.get("url") or "")
        if not url.startswith("https://mfe.gov.ro/"):
            raise ValueError(f"non-official MIPE page rejected: {url}")
        if page.get("verification") != "CANONICAL_OFFICIAL_FETCH":
            raise ValueError(f"unverified MIPE page rejected: {url}")
        if not page.get("textPreview"):
            raise ValueError(f"MIPE page without textPreview rejected: {url}")
    for doc in corpus.get("documents") or []:
        if not doc.get("sha256"):
            continue
        url = str(doc.get("url") or "")
        if not url.startswith("https://mfe.gov.ro/"):
            raise ValueError(f"non-official MIPE document rejected: {url}")
        if len(str(doc.get("sha256"))) != 64:
            raise ValueError(f"invalid MIPE document hash: {url}")


def item_from_page(page: dict[str, Any], observed_at: str) -> dict[str, Any]:
    return {
        "id": page.get("id"),
        "title": page.get("title"),
        "url": page.get("url"),
        "date": "",
        "dateLabel": "Observat direct",
        "dateConfidence": "OBSERVED_ONLY",
        "summary": page.get("summary"),
        "textPreview": page.get("textPreview"),
        "pageClass": page.get("pageClass"),
        "tag": page.get("programme"),
        "kind": page.get("kind"),
        "tier": "T1",
        "source": "MIPE",
        "observedAt": observed_at,
        "retrievalTransport": page.get("retrievalTransport") or "playwright-edge-direct-romania-v3",
        "verification": page.get("verification") or "CANONICAL_OFFICIAL_FETCH",
        "documents": page.get("documents") or [],
        "contentHash": page.get("contentHash"),
    }


def build_projection(corpus: dict[str, Any], previous_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_corpus(corpus)
    run = dict(corpus.get("lastRun") or {})
    observed_at = str(run.get("observedAt") or corpus.get("generatedAt") or "")
    if not observed_at:
        raise ValueError("MIPE v3 corpus has no observedAt")

    fresh_pages = [
        page for page in (corpus.get("pages") or [])
        if str(page.get("observedAt") or "") == observed_at
    ]
    expected_fresh = int(run.get("acceptedPages") or 0)
    if expected_fresh and len(fresh_pages) < expected_fresh:
        raise ValueError(
            f"MIPE corpus lost fresh pages: expected at least {expected_fresh}, found {len(fresh_pages)}"
        )

    prior_items = {
        item.get("url"): item
        for item in (previous_state.get("items") or [])
        if item.get("url")
    }
    for page in fresh_pages:
        prior_items[page["url"]] = item_from_page(page, observed_at)
    items = list(prior_items.values())[:300]

    source_available = bool(run.get("sourceAvailable"))
    if source_available and fresh_pages:
        status = "OK"
    elif source_available:
        status = "OK_NO_NEW_RELEVANT_ITEMS"
    else:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"

    previous_runs = [
        row for row in (previous_state.get("runs") or [])
        if str(row.get("observedAt") or "") != observed_at
    ]
    state_run = {
        "observedAt": observed_at,
        "roots": run.get("roots") or [],
        "sourceAvailable": source_available,
        "candidateCount": int(run.get("pagesVisited") or 0),
        "parsedRelevantCount": len(fresh_pages),
        "documentCount": int(run.get("documentsObserved") or 0),
        "transport": run.get("transport") or "playwright-edge-direct-romania-v3",
        "runtimeSeconds": run.get("runtimeSeconds"),
        "deadlineReached": bool(run.get("deadlineReached")),
        "status": status,
        "directSuccessCount": sum(1 for root in (run.get("roots") or []) if root.get("ok")),
        "collectorVersion": "3.0",
        "frontierVersion": int(run.get("frontierVersion") or corpus.get("frontierVersion") or 1),
        "frontierPersisted": int(run.get("frontierPersisted") or len(corpus.get("frontier") or [])),
        "resumedFrontier": int(run.get("resumedFrontier") or 0),
    }
    state = {
        "status": status,
        "lastRun": state_run,
        "items": items,
        "runs": previous_runs[-39:] + [run],
    }
    meta = {
        "status": status,
        "asOf": observed_at,
        "source": "MIPE official web properties",
        "roots": run.get("roots") or [],
        "itemCount": len(items),
        "transport": state_run["transport"],
        "sourceAvailable": source_available,
        "collectorVersion": "3.0",
        "frontierVersion": state_run["frontierVersion"],
        "frontierPersisted": state_run["frontierPersisted"],
        "corpusPages": len(corpus.get("pages") or []),
        "corpusDocuments": len(corpus.get("documents") or []),
    }
    return state, meta


def render_feed(state: dict[str, Any], meta: dict[str, Any]) -> str:
    return (
        "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.mipeIngestion="
        + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        + "window.PARTENER_DATA.mipeNews="
        + json.dumps(state.get("items") or [], ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )


def main() -> int:
    corpus = load_json(CORPUS_PATH, {})
    previous_state = load_json(STATE_PATH, {"items": [], "runs": []})
    state, meta = build_projection(corpus, previous_state)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    FEED_PATH.write_text(render_feed(state, meta), encoding="utf-8")
    print(json.dumps({
        "status": state["status"],
        "observedAt": state["lastRun"]["observedAt"],
        "freshPages": state["lastRun"]["parsedRelevantCount"],
        "items": len(state.get("items") or []),
        "corpusPages": meta["corpusPages"],
        "corpusDocuments": meta["corpusDocuments"],
    }, ensure_ascii=False, indent=2))
    return 0 if state["lastRun"]["sourceAvailable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
