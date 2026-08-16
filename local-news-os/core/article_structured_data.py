#!/usr/bin/env python3
"""Generic fail-closed NewsArticle structured-data helpers for LOCAL NEWS OS.

This module does not decide editorial eligibility. Callers must pass only stories
that have already passed their publication gate. Publication timestamps are
reconciled from a durable per-story ledger so a presentation rebuild cannot
silently rewrite datePublished.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse


def _https_url(value: object) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"expected absolute HTTPS URL, got {text!r}")
    return text


def _aware_iso8601(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text


def reconcile_publication_dates(
    story_ids: Iterable[object],
    previous_rows: Iterable[Mapping[str, object]],
    *,
    new_story_ids: Iterable[object] = (),
    published_at: object = None,
    bootstrap_event: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Return stable original publication timestamps for known stories.

    Priority is deliberately conservative: an existing per-story timestamp wins;
    the current publication decision may initialize newly published stories; a
    previous durable publication event may bootstrap a legacy manifest once.
    Unknown stories remain without a timestamp rather than receiving a guessed
    date.
    """
    wanted = [str(value) for value in story_ids if str(value or "").strip()]
    previous: dict[str, str] = {}
    for row in previous_rows:
        sid = str(row.get("id") or "").strip()
        stamp = _aware_iso8601(row.get("published_at"))
        if sid and stamp:
            previous[sid] = stamp

    current_new = {str(value) for value in new_story_ids if str(value or "").strip()}
    current_stamp = _aware_iso8601(published_at)

    event_new: set[str] = set()
    event_stamp: str | None = None
    if bootstrap_event and str(bootstrap_event.get("event") or "") == "story_publication":
        event_new = {
            str(value)
            for value in (bootstrap_event.get("new_story_ids") or [])
            if str(value or "").strip()
        }
        event_stamp = _aware_iso8601(bootstrap_event.get("published_at"))

    result: dict[str, str] = {}
    for sid in wanted:
        if sid in previous:
            result[sid] = previous[sid]
        elif sid in current_new and current_stamp:
            result[sid] = current_stamp
        elif sid in event_new and event_stamp:
            result[sid] = event_stamp
    return result


def build_newsarticle(
    *,
    headline: object,
    canonical_url: object,
    publisher_name: object,
    publisher_url: object,
    description: object = None,
    article_section: object = None,
    date_published: object = None,
    language: str = "ro-RO",
    author_name: object = None,
    author_url: object = None,
    image_urls: Sequence[object] | None = None,
) -> dict[str, object]:
    """Build a minimal provenance-safe Schema.org NewsArticle object."""
    title = str(headline or "").strip()
    publisher = str(publisher_name or "").strip()
    if not title:
        raise ValueError("headline is required")
    if not publisher:
        raise ValueError("publisher_name is required")

    canonical = _https_url(canonical_url)
    publisher_home = _https_url(publisher_url)
    doc: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "url": canonical,
        "publisher": {
            "@type": "Organization",
            "name": publisher,
            "url": publisher_home,
        },
        "inLanguage": str(language or "ro-RO"),
    }

    desc = str(description or "").strip()
    if desc:
        doc["description"] = desc
    section = str(article_section or "").strip()
    if section:
        doc["articleSection"] = section

    if date_published not in (None, ""):
        stamp = _aware_iso8601(date_published)
        if not stamp:
            raise ValueError("date_published must be timezone-aware ISO 8601")
        doc["datePublished"] = stamp

    author = str(author_name or "").strip()
    if author:
        node: dict[str, object] = {"@type": "Organization", "name": author}
        if author_url not in (None, ""):
            node["url"] = _https_url(author_url)
        doc["author"] = node

    if image_urls:
        images = [_https_url(value) for value in image_urls if str(value or "").strip()]
        if images:
            doc["image"] = images
    return doc


def serialize_jsonld(document: Mapping[str, object]) -> str:
    """Serialize JSON-LD safely for embedding inside an HTML script element."""
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _self_test() -> None:
    previous = [{"id": "old", "published_at": "2026-01-02T10:00:00+02:00"}]
    event = {
        "event": "story_publication",
        "published_at": "2026-01-03T11:00:00+02:00",
        "new_story_ids": ["legacy"],
    }
    dates = reconcile_publication_dates(
        ["old", "new", "legacy", "unknown"],
        previous,
        new_story_ids=["old", "new"],
        published_at="2026-01-04T12:00:00+02:00",
        bootstrap_event=event,
    )
    assert dates["old"] == "2026-01-02T10:00:00+02:00"
    assert dates["new"] == "2026-01-04T12:00:00+02:00"
    assert dates["legacy"] == "2026-01-03T11:00:00+02:00"
    assert "unknown" not in dates

    doc = build_newsarticle(
        headline="Local <news>",
        canonical_url="https://example.test/stiri/a/",
        publisher_name="Example News",
        publisher_url="https://example.test/",
        description="Verified story",
        article_section="LOCAL",
        date_published=dates["new"],
        author_name="Example News",
        author_url="https://example.test/",
    )
    assert doc["@type"] == "NewsArticle"
    assert doc["datePublished"] == dates["new"]
    assert "image" not in doc
    serialized = serialize_jsonld(doc)
    assert "<news>" not in serialized and "\\u003cnews\\u003e" in serialized

    try:
        build_newsarticle(
            headline="Bad",
            canonical_url="http://example.test/a",
            publisher_name="Example",
            publisher_url="https://example.test/",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("HTTP canonical must fail closed")
    print("ARTICLE_STRUCTURED_DATA_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
