#!/usr/bin/env python3
"""Persist a bounded, sanitized structural diagnostic for the official HCL view.

This is a development/health artifact only. It has zero editorial authority and
never changes fact registries. The diagnostic answers a narrow question needed
by the Council Fact Kernel resolver: where do parsed HCL identities sit relative
to official links in the actual Lotus/DocManager DOM?

The artifact deliberately stores no cookies, headers, credentials, scripts,
styles or full HTML. It records only:
- source URL + body hash;
- aggregate tag/link counts;
- target HCL number/date/title hashes;
- a bounded ±N parser-event neighborhood around exact HCL title text;
- canonical official href shapes found in that neighborhood.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import council_watch_rm_valcea as council

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
OUTPUT = ROOT / "editorial" / "council_docmanager_structure.json"
TZ_RO = timezone(timedelta(hours=3))
MAX_EVENTS = 6000
MAX_TARGETS = 25
WINDOW = 10


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).replace("\u00a0", " ")).strip()


def href_shape(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parsed.path)
    low = path.lower()
    return {
        "host": parsed.netloc.lower(),
        "path_sha256": sha(path),
        "path_suffix": path[-120:],
        "query_keys": sorted(urllib.parse.parse_qs(parsed.query, keep_blank_values=True).keys()),
        "is_file_attachment": "$file" in low,
        "is_open_document": "opendocument" in parsed.query.lower() or "opendocument" in low,
    }


class EventParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.stack: list[str] = []
        self.events: list[dict[str, Any]] = []
        self.tag_counts: dict[str, int] = {}
        self.official_link_count = 0
        self.external_link_count = 0
        self._skip = 0

    def _append(self, event: dict[str, Any]) -> None:
        if len(self.events) < MAX_EVENTS:
            self.events.append(event)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        self.tag_counts[low] = self.tag_counts.get(low, 0) + 1
        if low in {"script", "style", "noscript"}:
            self._skip += 1
        self.stack.append(low)
        if low == "a":
            values = {k.lower(): (v or "") for k, v in attrs}
            href = values.get("href")
            if href:
                absolute = urllib.parse.urljoin(self.base_url, href)
                canonical = council.canonical_url(self.base_url, absolute)
                if canonical:
                    self.official_link_count += 1
                    self._append({
                        "kind": "link",
                        "depth": len(self.stack),
                        "stack": self.stack[-6:],
                        "href": canonical,
                    })
                else:
                    self.external_link_count += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if self.stack:
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index] == low:
                    del self.stack[index:]
                    break

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = norm_text(data)
        if not text:
            return
        self._append({
            "kind": "text",
            "depth": len(self.stack),
            "stack": self.stack[-6:],
            "text": text[:500],
            "text_sha256": sha(text),
        })


def load_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {}
    return json.loads(STATE.read_text(encoding="utf-8"))


def target_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in state.get("latest_decisions") or [] if isinstance(row, dict)]
    rows.sort(key=lambda row: int(row.get("decision_number") or 0), reverse=True)
    return rows[:MAX_TARGETS]


def target_event_indexes(events: list[dict[str, Any]], row: dict[str, Any]) -> list[int]:
    title = norm_text(str(row.get("title") or "")).casefold()
    number = int(row.get("decision_number") or 0)
    needles = [
        title,
        f"hotarirea {number}",
        f"hotărârea {number}",
        f"hotararea {number}",
    ]
    indexes: list[int] = []
    for index, event in enumerate(events):
        if event.get("kind") != "text":
            continue
        text = norm_text(str(event.get("text") or "")).casefold()
        if any(needle and needle in text for needle in needles):
            indexes.append(index)
    return indexes[:3]


def sanitized_event(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("kind") == "link":
        url = str(event.get("href") or "")
        return {
            "kind": "link",
            "depth": event.get("depth"),
            "stack": event.get("stack"),
            "href_shape": href_shape(url),
        }
    text = norm_text(str(event.get("text") or ""))
    return {
        "kind": "text",
        "depth": event.get("depth"),
        "stack": event.get("stack"),
        "text_sha256": event.get("text_sha256"),
        "text_prefix": text[:180],
    }


def build() -> dict[str, Any]:
    state = load_state()
    source_url = str((state.get("source") or {}).get("url") or council.ADOPTED_VIEW)
    fetched = council.fetch(source_url, timeout=20)
    if not fetched.get("ok"):
        return {
            "schema_version": "1.0",
            "instance_id": "valcea",
            "product": "VÂLCEA CLAR DocManager structure diagnostic",
            "generated_at": datetime.now(TZ_RO).isoformat(timespec="seconds"),
            "status": "SOURCE_UNREACHABLE",
            "source_url": source_url,
            "error": fetched.get("error"),
            "publication_authority": "NONE",
        }

    final_url = str(fetched.get("url") or source_url)
    body = str(fetched.get("body") or "")
    parser = EventParser(final_url)
    parser.feed(body)

    targets: list[dict[str, Any]] = []
    for row in target_rows(state):
        indexes = target_event_indexes(parser.events, row)
        neighborhoods: list[dict[str, Any]] = []
        for index in indexes:
            start = max(0, index - WINDOW)
            end = min(len(parser.events), index + WINDOW + 1)
            events = [sanitized_event(event) for event in parser.events[start:end]]
            neighborhoods.append({
                "match_event_index": index,
                "window_start": start,
                "window_end": end,
                "events": events,
                "official_link_shapes_in_window": [
                    event["href_shape"] for event in events if event.get("kind") == "link"
                ],
            })
        title = norm_text(str(row.get("title") or ""))
        targets.append({
            "decision_number": int(row.get("decision_number") or 0),
            "decision_date": row.get("decision_date"),
            "title_sha256": sha(title),
            "title_prefix": title[:220],
            "matching_text_events": len(indexes),
            "neighborhoods": neighborhoods,
        })

    diagnostic = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR DocManager structure diagnostic",
        "generated_at": datetime.now(TZ_RO).isoformat(timespec="seconds"),
        "status": "PASS",
        "source_url": final_url,
        "source_sha256": fetched.get("sha256"),
        "publication_authority": "NONE",
        "bounds": {
            "max_parser_events": MAX_EVENTS,
            "target_limit": MAX_TARGETS,
            "event_window_radius": WINDOW,
            "scripts_styles_persisted": False,
            "headers_cookies_persisted": False,
            "full_html_persisted": False,
            "external_urls_persisted": False,
        },
        "structure": {
            "parser_events_captured": len(parser.events),
            "tag_counts": parser.tag_counts,
            "official_link_count": parser.official_link_count,
            "external_link_count_not_persisted": parser.external_link_count,
            "target_count": len(targets),
            "targets_with_text_event": sum(1 for row in targets if row["matching_text_events"]),
            "targets_with_nearby_official_link": sum(
                1 for row in targets
                if any(n["official_link_shapes_in_window"] for n in row["neighborhoods"])
            ),
        },
        "targets": targets,
        "policy": {
            "development_diagnostic_only": True,
            "may_promote_fact": False,
            "may_publish_story": False,
            "used_to_reduce_evidence_threshold": False,
        },
    }
    diagnostic["diagnostic_fingerprint_sha256"] = sha(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True))
    return diagnostic


def self_test() -> int:
    mock = """
    <html><body><table><tr><td><a href="/dm/2026/hotarari.nsf/ABC?OpenDocument">2026</a></td>
    <td>304</td><td>hotarirea 304 - 23 iulie 2026 - acordare autorizatie anuala de functionare pentru jocuri de noroc TEST SRL strada Test</td></tr></table></body></html>
    """
    parser = EventParser(council.ADOPTED_VIEW)
    parser.feed(mock)
    row = {
        "decision_number": 304,
        "decision_date": "2026-07-23",
        "title": "acordare autorizatie anuala de functionare pentru jocuri de noroc TEST SRL strada Test",
    }
    indexes = target_event_indexes(parser.events, row)
    assert indexes
    start = max(0, indexes[0] - WINDOW)
    end = min(len(parser.events), indexes[0] + WINDOW + 1)
    sanitized = [sanitized_event(event) for event in parser.events[start:end]]
    assert any(event.get("kind") == "link" for event in sanitized)
    assert all("href" not in event for event in sanitized if event.get("kind") == "link")
    print("VÂLCEA CLAR DocManager structure diagnostic self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = build()
    if args.check:
        assert doc.get("publication_authority") == "NONE"
        assert (doc.get("policy") or {}).get("may_publish_story") is False
        print(json.dumps({"status": doc.get("status"), "publication_authority": "NONE"}, ensure_ascii=False))
        return 0
    OUTPUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": doc.get("status"),
        "output": str(OUTPUT.relative_to(ROOT)),
        "structure": doc.get("structure"),
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
