#!/usr/bin/env python3
"""VÂLCEA CLAR Council Fact Kernel v1.1.

This is a narrow resolver upgrade over council_fact_kernel_v1. The evidence
model, story semantics and 100% document-coverage promotion rule remain owned by
v1. v1.1 only broadens how an attachment can be found inside an *already exact*
DocManager decision page.

Lotus/DocManager pages sometimes expose `$FILE/*.htm` attachments outside a
normal clickable <a href>, for example in iframe/object/embed attributes or
quoted JavaScript strings. This wrapper extracts those candidates while keeping
all of the original safety boundaries:
- exact register-row -> intermediate document resolution remains v1 logic;
- every child must canonicalize to the official dm.primariavl.ro host;
- every child must stay inside /dm/2026/hotarari.nsf;
- only `$FILE` HTML attachments are followed;
- the child document must still pass v1 semantic verification;
- partial coverage remains candidate_hold and can never be promoted.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
from typing import Any

import council_fact_kernel as v1
import council_watch_rm_valcea as council

RESOLVER_ID = "council_fact_kernel_v1_1"
MAX_CHILD_CANDIDATES = 12

# Attributes cover normal embedded viewers. The quoted-string pass covers Lotus
# JavaScript such as window.open('.../$FILE/file.htm') and encoded variants.
ATTR_VALUE_RE = re.compile(
    r"(?:href|src|data|action|value)\s*=\s*([\"'])(.*?)\1",
    re.I | re.S,
)
QUOTED_VALUE_RE = re.compile(r"([\"'])(.*?)\1", re.S)


def _decode_candidate(value: str) -> str:
    value = html.unescape(str(value or "").strip())
    # Lotus output can percent-encode `$FILE` and spaces once or twice. Two
    # bounded passes are sufficient and avoid an unbounded decoding loop.
    for _ in range(2):
        decoded = urllib.parse.unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def _official_file_candidate(page_url: str, raw: str) -> str | None:
    decoded = _decode_candidate(raw)
    if "$file" not in decoded.casefold():
        return None
    # Canonicalization is delegated to the existing strict host/path guard.
    canonical = council.canonical_url(page_url, decoded)
    if not canonical:
        return None
    low = urllib.parse.unquote(canonical).casefold()
    path = urllib.parse.urlparse(low).path
    if "$file" not in low or not path.endswith((".htm", ".html")):
        return None
    return canonical


def embedded_official_html_links(page_url: str, body: str) -> list[str]:
    """Extract bounded official `$FILE` HTML children outside normal anchors."""
    candidates: list[str] = []
    seen: set[str] = set()

    def admit(raw: str) -> None:
        url = _official_file_candidate(page_url, raw)
        if url and url not in seen:
            seen.add(url)
            candidates.append(url)

    text = html.unescape(str(body or ""))
    for match in ATTR_VALUE_RE.finditer(text):
        admit(match.group(2))
    for match in QUOTED_VALUE_RE.finditer(text):
        value = match.group(2)
        decoded = _decode_candidate(value)
        if "$file" in decoded.casefold():
            admit(value)
    return candidates[:MAX_CHILD_CANDIDATES]


def _candidate_children(page_url: str, body: str) -> list[str]:
    children: list[str] = []
    seen: set[str] = set()

    def admit(url: str) -> None:
        canonical = _official_file_candidate(page_url, url)
        if canonical and canonical not in seen:
            seen.add(canonical)
            children.append(canonical)

    # Preserve every candidate that the stable anchor parser already accepted.
    for link in council.parse_links(page_url, body):
        admit(str(link.get("url") or ""))
    # Add only the embedded/raw forms missing from v1.
    for url in embedded_official_html_links(page_url, body):
        admit(url)
    return children[:MAX_CHILD_CANDIDATES]


def verify_document(row: dict[str, Any], url: str) -> dict[str, Any]:
    result = council.fetch(url, timeout=18)
    base = {
        "decision_number": int(row.get("decision_number") or 0),
        "decision_date": row.get("decision_date"),
        "title": row.get("title"),
        "candidate_url": url,
        "error": result.get("error"),
        "resolver_id": RESOLVER_ID,
    }

    semantic = v1._semantic_document(url, result)
    if semantic:
        return {
            **base,
            **semantic,
            "verified": True,
            "reason": "PASS",
            "child_candidates_examined": 0,
        }

    child_urls: list[str] = []
    if result.get("ok"):
        child_urls = _candidate_children(
            str(result.get("url") or url),
            str(result.get("body") or ""),
        )
        for child_url in child_urls:
            child = council.fetch(child_url, timeout=18)
            semantic = v1._semantic_document(child_url, child)
            if semantic:
                return {
                    **base,
                    **semantic,
                    "verified": True,
                    "reason": "PASS_VIA_OFFICIAL_ATTACHMENT_V1_1",
                    "child_candidates_examined": len(child_urls),
                    "child_candidate_urls": child_urls,
                }

    return {
        **base,
        "url": str(result.get("url") or url),
        "http_status": result.get("status"),
        "source_sha256": result.get("sha256"),
        "verified": False,
        "reason": "OFFICIAL_DOCUMENT_UNREACHABLE" if not result.get("ok") else "OFFICIAL_DOCUMENT_SEMANTICS_INCOMPLETE",
        "child_candidates_examined": len(child_urls),
        "child_candidate_urls": child_urls,
    }


def install() -> None:
    # The v1 builder calls its module-level verify_document from worker threads.
    # Rebinding only that function leaves all evidence/promotion logic intact.
    v1.verify_document = verify_document


def self_test() -> int:
    assert v1.self_test() == 0
    page = "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn/ABC?OpenDocument"
    iframe = (
        '<iframe src="/dm/2026/hotarari.nsf/x/abc/$FILE/'
        'hotarirea%20302%20-%2023%20iulie%202026%20-%20test.htm"></iframe>'
    )
    js = (
        "<script>window.open('/dm/2026/hotarari.nsf/x/def/%24FILE/"
        "hotarirea%20301%20-%2023%20iulie%202026%20-%20test.html')</script>"
    )
    external = '<iframe src="https://evil.example/$FILE/fake.htm"></iframe>'
    links = embedded_official_html_links(page, iframe + js + external)
    assert len(links) == 2
    assert all(urllib.parse.urlparse(url).hostname == council.OFFICIAL_HOST for url in links)
    assert any("302" in urllib.parse.unquote(url) for url in links)
    assert any("301" in urllib.parse.unquote(url) for url in links)
    assert not any("evil.example" in url for url in links)

    # Ordinary anchors are still retained by the combined child resolver.
    anchor = (
        '<a href="/dm/2026/hotarari.nsf/x/ghi/$FILE/'
        'hotarirea%20300%20-%2023%20iulie%202026%20-%20test.htm">document</a>'
    )
    combined = _candidate_children(page, anchor + iframe)
    assert len(combined) == 2
    print("VÂLCEA CLAR Council Fact Kernel v1.1 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    install()
    doc = v1.build_registry(live=args.live)
    # Preserve the schema but make resolver provenance explicit.
    doc["resolver_id"] = RESOLVER_ID
    doc.setdefault("policy", {})["embedded_docmanager_attachment_resolution"] = True
    doc["registry_fingerprint_sha256"] = v1.digest({"facts": doc.get("facts") or [], "policy": doc["policy"]})

    if args.check:
        assert (doc.get("policy") or {}).get("partial_document_coverage_publishable") is False
        assert (doc.get("policy") or {}).get("annual_authorization_is_new_venue") is False
        assert doc.get("resolver_id") == RESOLVER_ID
        for fact in doc.get("facts") or []:
            provenance = fact.get("kernel_provenance") or {}
            if fact.get("status") == "verified":
                assert provenance.get("evidence_complete") is True
                assert float(provenance.get("coverage") or 0) == 1.0
        print(json.dumps({"status": "PASS", **doc["stats"], "resolver_id": RESOLVER_ID}, ensure_ascii=False))
        return 0

    v1.OUTPUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", **doc["stats"], "resolver_id": RESOLVER_ID, "output": str(v1.OUTPUT.relative_to(v1.ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
