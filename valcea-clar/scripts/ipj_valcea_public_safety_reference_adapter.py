#!/usr/bin/env python3
"""Bounded first-party IPJ Vâlcea public-safety references for VÂLCEA CLAR.

This adapter reads only allow-listed Inspectoratul de Poliție Județean Vâlcea
news/media index pages and emits newsroom reference candidates. An index entry
is discovery evidence, not proof that every material statement in the linked
article remains current or complete. This lane never turns police allegations,
procedural measures, incident counts or institutional language into a Fact
Kernel, breaking-news decision or publication authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SCHEMA = "IPJ_VALCEA_PUBLIC_SAFETY_REFERENCE_V1"
PARSER_VERSION = "IPJ_VALCEA_PUBLIC_SAFETY_REFERENCE_ADAPTER_2026_09_02"
SOURCE_FAMILY = "IPJ_VALCEA_PUBLIC_SAFETY"
AUTHORITY_CLASS = "FIRST_PARTY_COUNTY_POLICE_MEDIA_INDEX"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
ALLOWED_HOSTS = {"vl.politiaromana.ro"}
SOURCE_URLS = {
    "NEWS": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri",
    "COMMUNIQUES": "https://vl.politiaromana.ro/ro/stiri-si-media/comunicate",
    "BULLETINS": "https://vl.politiaromana.ro/ro/stiri-si-media/buletine-de-presa",
}
MAX_REFERENCES = 72
USER_AGENT = "VALCEA-CLAR-first-party-reference-check/1.0"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "incident_status_authorized": False,
    "suspect_status_authorized": False,
    "criminal_liability_authorized": False,
    "casualty_count_authorized": False,
    "sanction_count_authorized": False,
    "road_restriction_authorized": False,
    "investigation_status_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ROAD_SAFETY", ("rutier", "dn 7", "accident", "trafic", "viteza", "viteză", "conducea", "permis")),
    ("ECONOMIC_CRIME", ("evazi", "contrabanda", "contrabandă", "tutun", "economic", "fiscal", "comert ilicit", "comerț ilicit")),
    ("CRIME_INVESTIGATION", ("retinut", "reținut", "arestat", "furt", "talhar", "tâlhar", "violenta", "violență", "amenint", "ameninț", "infracti", "infracți", "perchez")),
    ("MISSING_WANTED", ("disparut", "dispărut", "cautat", "căutat", "urmarit", "urmărit")),
    ("PUBLIC_ORDER", ("siguranta publica", "siguranța publică", "ordine publica", "ordine publică", "razie")),
    ("PREVENTION", ("preven", "campanie", "recomand", "informare")),
)

GENERIC_ANCHOR_TEXT = {
    "citeste tot",
    "citeste mai mult",
    "pagina urmatoare",
    "pagina anterioara",
    "stiri",
    "comunicate",
    "buletine de presa",
}


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


@dataclass(frozen=True)
class Reference:
    title: str
    target_url: str
    source_kind: str
    topic_class: str
    source_page_url: str
    source_page_sha256: str
    evidence_sha256: str
    authority_class: str = AUTHORITY_CLASS
    observation_state: str = OBSERVATION_STATE
    parser_version: str = PARSER_VERSION


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.anchors: list[Anchor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = " ".join("".join(self._parts).split())
        if text:
            self.anchors.append(Anchor(self._href, text))
        self._href = None
        self._parts = []


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, ""))


def _topic(title: str) -> str:
    normalized = _normalize(title)
    for topic, needles in TOPIC_RULES:
        if any(_normalize(needle) in normalized for needle in needles):
            return topic
    return "PUBLIC_SAFETY_OTHER"


def _source_path(source_kind: str) -> str:
    return urlsplit(SOURCE_URLS[source_kind]).path.rstrip("/")


def _is_article_target(source_kind: str, target_url: str) -> bool:
    parsed = urlsplit(target_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return False
    base = _source_path(source_kind)
    path = parsed.path.rstrip("/")
    return path.startswith(base + "/") and path != base


def parse_source_page(source_kind: str, source_url: str, raw: bytes) -> list[Reference]:
    if source_kind not in SOURCE_URLS:
        raise ValueError("unknown_source_kind")
    page_hash = _sha256_bytes(raw)
    parser = AnchorParser()
    parser.feed(raw.decode("utf-8", errors="replace"))

    by_target: dict[str, Reference] = {}
    for anchor in parser.anchors:
        title = " ".join(anchor.text.split())
        normalized_title = _normalize(title)
        if not title or normalized_title in GENERIC_ANCHOR_TEXT:
            continue
        target = _canonical_url(urljoin(source_url, anchor.href))
        if not _is_article_target(source_kind, target):
            continue
        evidence_basis = json.dumps(
            {
                "source_family": SOURCE_FAMILY,
                "source_kind": source_kind,
                "source_page_url": source_url,
                "source_page_sha256": page_hash,
                "title": title,
                "target_url": target,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        candidate = Reference(
            title=title,
            target_url=target,
            source_kind=source_kind,
            topic_class=_topic(title),
            source_page_url=source_url,
            source_page_sha256=page_hash,
            evidence_sha256=_sha256_text(evidence_basis),
        )
        current = by_target.get(target)
        if current is None or len(candidate.title) > len(current.title):
            by_target[target] = candidate

    return list(by_target.values())


def _validate_final_source_url(expected_url: str, final_url: str) -> None:
    expected = urlsplit(_canonical_url(expected_url))
    final = urlsplit(_canonical_url(final_url))
    if final.scheme != "https":
        raise ValueError("source_redirect_downgraded_https")
    if final.hostname not in ALLOWED_HOSTS:
        raise ValueError("source_redirect_left_allowlist")
    if final.path.rstrip("/") != expected.path.rstrip("/"):
        raise ValueError("source_redirect_changed_resource_identity")


def _fetch_source(url: str, timeout: float = 20.0) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = response.geturl()
        _validate_final_source_url(url, final_url)
        return response.read(), final_url


def build_receipt(fetcher: Callable[[str], tuple[bytes, str]] = _fetch_source) -> dict[str, Any]:
    source_pages: list[dict[str, Any]] = []
    references: list[Reference] = []
    failures: list[dict[str, str]] = []

    for source_kind, source_url in SOURCE_URLS.items():
        try:
            raw, final_url = fetcher(source_url)
            _validate_final_source_url(source_url, final_url)
            page_hash = _sha256_bytes(raw)
            page_refs = parse_source_page(source_kind, source_url, raw)
            source_pages.append(
                {
                    "source_kind": source_kind,
                    "source_page_url": source_url,
                    "final_url": _canonical_url(final_url),
                    "source_page_sha256": page_hash,
                    "bytes": len(raw),
                    "reference_count": len(page_refs),
                    "status": "PASS",
                }
            )
            references.extend(page_refs)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            failures.append({"source_kind": source_kind, "source_page_url": source_url, "error": type(exc).__name__})

    deduped: dict[str, Reference] = {}
    for ref in references:
        current = deduped.get(ref.target_url)
        if current is None or len(ref.title) > len(current.title):
            deduped[ref.target_url] = ref
    selected = list(deduped.values())[:MAX_REFERENCES]

    digest_basis = "|".join(page["source_page_sha256"] for page in source_pages) + "|" + PARSER_VERSION
    status = "PASS" if len(source_pages) == len(SOURCE_URLS) and selected else "HOLD_SOURCE_FETCH_FAILED" if failures else "HOLD_NO_REFERENCES"
    topic_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for ref in selected:
        topic_counts[ref.topic_class] = topic_counts.get(ref.topic_class, 0) + 1
        source_kind_counts[ref.source_kind] = source_kind_counts.get(ref.source_kind, 0) + 1

    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "coverage_note": "BOUNDED_FIRST_PARTY_MEDIA_INDEX_DISCOVERY_NOT_EXHAUSTIVE",
        "status": status,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": _sha256_text(digest_basis)[:24],
        "source_page_count": len(source_pages),
        "reference_count": len(selected),
        "topic_counts": dict(sorted(topic_counts.items())),
        "source_kind_counts": dict(sorted(source_kind_counts.items())),
        "source_pages": source_pages,
        "references": [asdict(ref) for ref in selected],
        "failures": failures,
        "limitations": {
            "index_presence_is_not_article_fact_verification": True,
            "police_allegation_is_not_criminal_liability": True,
            "linked_detail_requires_separate_field_level_verification": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        **NON_AUTHORIZING_FLAGS,
    }


def self_test() -> int:
    fixture = b"""
    <html><body>
      <a href='/ro/stiri-si-media/stiri/actiune-pentru-siguranta-rutiera-pe-dn-7'>AC\xc8\x9aIUNE PENTRU SIGURAN\xc8\x9aA RUTIER\xc4\x82 PE DN 7</a>
      <a href='/ro/stiri-si-media/stiri/actiune-pentru-siguranta-rutiera-pe-dn-7'>Cite\xc8\x99te tot</a>
      <a href='/ro/stiri-si-media/stiri/retinut-pentru-furt'>RE\xc8\x9aINUT PENTRU FURT</a>
      <a href='https://example.invalid/story'>AC\xc8\x9aIUNE RUTIER\xc4\x82</a>
      <a href='/ro/stiri-si-media/comunicate/alta-pagina'>Alt\xc4\x83 pagin\xc4\x83</a>
    </body></html>
    """
    refs = parse_source_page("NEWS", SOURCE_URLS["NEWS"], fixture)
    if len(refs) != 2:
        raise AssertionError(refs)
    topics = {ref.topic_class for ref in refs}
    if topics != {"ROAD_SAFETY", "CRIME_INVESTIGATION"}:
        raise AssertionError(topics)
    if not all(ref.target_url.startswith(SOURCE_URLS["NEWS"] + "/") for ref in refs):
        raise AssertionError(refs)
    if not all(re.fullmatch(r"[0-9a-f]{64}", ref.evidence_sha256) for ref in refs):
        raise AssertionError("evidence hash missing")

    sample_pages = {
        url: (fixture.replace(b"/ro/stiri-si-media/stiri/", f"/ro/stiri-si-media/{'stiri' if kind == 'NEWS' else 'comunicate' if kind == 'COMMUNIQUES' else 'buletine-de-presa'}/".encode()), url)
        for kind, url in SOURCE_URLS.items()
    }

    def fake_fetch(url: str) -> tuple[bytes, str]:
        return sample_pages[url]

    receipt = build_receipt(fake_fetch)
    if receipt["status"] != "PASS" or receipt["source_page_count"] != 3:
        raise AssertionError(receipt)
    if receipt["material_fact_use"] or receipt["publication_authorized"] or receipt["fact_kernel_write_authorized"]:
        raise AssertionError("non-authorizing boundary weakened")
    if not receipt["limitations"]["police_allegation_is_not_criminal_liability"]:
        raise AssertionError("allegation boundary missing")
    print(json.dumps({"schema": SCHEMA, "self_test": "PASS", "references": receipt["reference_count"]}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded first-party IPJ Vâlcea public-safety reference adapter")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.live_check:
        parser.error("use --live-check or --self-test")

    receipt = build_receipt()
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    if receipt["status"] != "PASS":
        return 2
    if args.require_reference and receipt["reference_count"] < 1:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
