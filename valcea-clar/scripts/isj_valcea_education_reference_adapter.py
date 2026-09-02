#!/usr/bin/env python3
"""Bounded first-party ISJ Vâlcea education references for VÂLCEA CLAR.

The adapter reads only a small allow-listed set of official Inspectoratul Școlar
Județean Vâlcea index pages and emits newsroom reference candidates. It does not
interpret a listed item as current admission capacity, an active vacancy, an exam
result, a deadline, an eligibility rule, a school-status fact or publication-ready
news. Linked documents are discovery targets only unless a later first-party
verification layer validates their contents and material fields.
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
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SCHEMA = "ISJ_VALCEA_EDUCATION_REFERENCE_V1"
PARSER_VERSION = "ISJ_VALCEA_EDUCATION_REFERENCE_ADAPTER_2026_09_02"
SOURCE_FAMILY = "ISJ_VALCEA_EDUCATION"
AUTHORITY_CLASS = "FIRST_PARTY_COUNTY_EDUCATION_AUTHORITY_INDEX"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
ALLOWED_SOURCE_HOSTS = {"isjvalcea.ro", "www.isjvalcea.ro"}
SOURCE_URLS = (
    "https://www.isjvalcea.ro/",
    "https://www.isjvalcea.ro/nout%C4%83%C8%9Bi",
)
MAX_REFERENCES = 64

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "admission_capacity_authorized": False,
    "exam_result_authorized": False,
    "current_vacancy_authorized": False,
    "deadline_authorized": False,
    "eligibility_authorized": False,
    "school_status_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ADMISSIONS", ("admitere", "inscriere", "înscriere", "locuri libere", "liceu", "prescolar", "preșcolar", "primar")),
    ("EXAMS_RESULTS", ("definitivat", "titularizare", "rezultate", "rezultate finale", "contestatii", "contestații", "proba scrisa", "proba scrisă")),
    ("STAFFING_MANAGEMENT", ("director", "directori", "functie vacanta", "funcții vacante", "post vacant", "posturi vacante", "mobilitate", "resurse umane")),
    ("SCHOOL_PROGRAMMES", ("masa sanatoasa", "masă sănătoasă", "programul national", "programul național", "recred")),
    ("SCHOOL_NETWORK", ("cartografia scolara", "cartografia școlară", "unitati de invatamant", "unități de învățământ", "gradinite", "grădinițe")),
    ("TEACHING_CAREER", ("gradatii de merit", "gradații de merit", "grad didactic", "inspectii scolare", "inspecții școlare")),
)


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


@dataclass(frozen=True)
class Reference:
    title: str
    target_url: str
    target_host: str
    target_is_first_party: bool
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


def _topic(title: str) -> str | None:
    norm = _normalize(title)
    for topic, markers in TOPIC_RULES:
        if any(_normalize(marker) in norm for marker in markers):
            return topic
    return None


def _canonical_source_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_SOURCE_HOSTS:
        raise ValueError("source_url_not_allowlisted")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("source_url_identity_invalid")
    host = (parts.hostname or "").lower()
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def _canonical_target_url(base_url: str, href: str) -> str | None:
    joined = urljoin(base_url, href.strip())
    parts = urlsplit(joined)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if parts.port not in (None, 443):
        return None
    # Discovery may point to an external document host, but authority is never
    # transferred from the first-party ISJ index by this adapter.
    return urlunsplit(("https", parts.hostname.lower(), parts.path, parts.query, ""))


def _extract_references(body: bytes, source_page_url: str) -> list[Reference]:
    parser = AnchorParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    source_sha = _sha256_bytes(body)
    refs: list[Reference] = []
    seen: set[tuple[str, str]] = set()
    for anchor in parser.anchors:
        topic = _topic(anchor.text)
        if topic is None:
            continue
        target = _canonical_target_url(source_page_url, anchor.href)
        if target is None:
            continue
        key = (_normalize(anchor.text), target)
        if key in seen:
            continue
        seen.add(key)
        host = (urlsplit(target).hostname or "").lower()
        evidence = _sha256_text("\n".join((anchor.text, target, topic, source_page_url, source_sha, PARSER_VERSION)))
        refs.append(Reference(
            title=anchor.text,
            target_url=target,
            target_host=host,
            target_is_first_party=host in ALLOWED_SOURCE_HOSTS,
            topic_class=topic,
            source_page_url=source_page_url,
            source_page_sha256=source_sha,
            evidence_sha256=evidence,
        ))
        if len(refs) >= MAX_REFERENCES:
            break
    return refs


def _fetch(url: str, timeout: float = 20.0) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": "CIVORA-Valcea-Clar-Source-Reference/1.0"})
    context = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=context) as response:
        final_url = _canonical_source_url(response.geturl())
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"source_http_status:{status}")
        body = response.read(2_000_001)
        if not body or len(body) > 2_000_000:
            raise RuntimeError("source_body_empty_or_too_large")
        return body, final_url


def build_live_receipt(require_reference: bool = False) -> dict[str, Any]:
    refs: list[Reference] = []
    pages: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for source_url in SOURCE_URLS:
        canonical = _canonical_source_url(source_url)
        body, final_url = _fetch(canonical)
        page_refs = _extract_references(body, final_url)
        pages.append({
            "source_page_url": final_url,
            "source_page_sha256": _sha256_bytes(body),
            "reference_count": len(page_refs),
        })
        for ref in page_refs:
            if ref.evidence_sha256 not in seen_evidence:
                seen_evidence.add(ref.evidence_sha256)
                refs.append(ref)
            if len(refs) >= MAX_REFERENCES:
                break
        if len(refs) >= MAX_REFERENCES:
            break

    if require_reference and not refs:
        raise RuntimeError("no_bounded_education_reference_found")

    topic_counts: dict[str, int] = {}
    first_party_targets = 0
    for ref in refs:
        topic_counts[ref.topic_class] = topic_counts.get(ref.topic_class, 0) + 1
        first_party_targets += int(ref.target_is_first_party)

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS",
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_note": "BOUNDED_FIRST_PARTY_INDEX_DISCOVERY_NOT_EXHAUSTIVE",
        "source_page_count": len(pages),
        "reference_count": len(refs),
        "first_party_target_count": first_party_targets,
        "external_document_discovery_count": len(refs) - first_party_targets,
        "topic_counts": dict(sorted(topic_counts.items())),
        "source_pages": pages,
        "references": [asdict(ref) for ref in refs],
        "interpretation": (
            "OFFICIAL_ISJ_INDEX_PRESENCE_IS_DISCOVERY_CONTEXT_ONLY;"
            "LINKED_DOCUMENT_CONTENT_AND_CURRENTNESS_REQUIRE_SEPARATE_VERIFICATION"
        ),
        **NON_AUTHORIZING_FLAGS,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    html = """
    <html><body>
      <a href='/docs/locuri.pdf'>Locuri libere pentru etapa a II-a de admitere in liceu 2026</a>
      <a href='https://drive.google.com/file/d/example/view'>Rezultate Finale DEFINITIVAT 2026</a>
      <a href='/contact'>Contact</a>
      <a href='http://evil.example/item'>Titularizare 2026</a>
    </body></html>
    """.encode()
    refs = _extract_references(html, "https://www.isjvalcea.ro/nout%C4%83%C8%9Bi")
    assert len(refs) == 2
    assert refs[0].topic_class == "ADMISSIONS"
    assert refs[0].target_is_first_party is True
    assert refs[1].topic_class == "EXAMS_RESULTS"
    assert refs[1].target_host == "drive.google.com"
    assert refs[1].target_is_first_party is False
    assert re.fullmatch(r"[0-9a-f]{64}", refs[0].evidence_sha256)
    try:
        _canonical_source_url("https://example.com/noutati")
    except ValueError:
        pass
    else:
        raise AssertionError("foreign source host must fail closed")
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    print("ISJ Vâlcea education reference self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")

    try:
        payload = build_live_receipt(require_reference=args.require_reference)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"HOLD_SOURCE_FETCH_FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
