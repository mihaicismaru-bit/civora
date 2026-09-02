#!/usr/bin/env python3
"""Bounded first-party ISU Vâlcea emergency references for VÂLCEA CLAR.

This adapter reads only allow-listed Inspectoratul pentru Situații de Urgență
"General Magheru" al județului Vâlcea media indexes and emits newsroom
reference candidates. Index presence is discovery evidence only. It does not
prove casualty counts, incident status, causes, road restrictions, service
availability or any other material fact in a linked article, and it never
writes Fact Kernels, invokes the Editorial Writer or authorizes publication.
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

SCHEMA = "ISU_VALCEA_EMERGENCY_REFERENCE_V1"
PARSER_VERSION = "ISU_VALCEA_EMERGENCY_REFERENCE_ADAPTER_2026_09_02"
SOURCE_FAMILY = "ISU_VALCEA_EMERGENCY"
AUTHORITY_CLASS = "FIRST_PARTY_COUNTY_EMERGENCY_MEDIA_INDEX"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
ALLOWED_HOSTS = {"isuvl.igsu.ro"}
SOURCE_URLS = {
    "LOCAL_NEWS": "https://isuvl.igsu.ro/stiri-locale",
    "COMMUNIQUES": "https://isuvl.igsu.ro/comunicate-de-presa",
}
MAX_REFERENCES = 64
USER_AGENT = "VALCEA-CLAR-first-party-emergency-reference-check/1.0"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "incident_status_authorized": False,
    "incident_cause_authorized": False,
    "casualty_count_authorized": False,
    "intervention_count_authorized": False,
    "road_restriction_authorized": False,
    "weather_warning_authorized": False,
    "shelter_capacity_authorized": False,
    "medical_service_availability_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ROAD_RESCUE", ("accident rutier", "descarcer", "autocar", "microbuz", "colizi", "rutier")),
    ("FIRE", ("incendiu", "ardere", "vegetatie uscata", "vegetatie uscată", "fum", "exploz")),
    ("WEATHER_HAZARD", ("inund", "viitur", "furtun", "vant", "vânt", "cod rosu", "cod roșu", "cod portocaliu", "canicula", "caniculă", "ger")),
    ("MEDICAL_EMERGENCY", ("smurd", "prim ajutor", "medical", "persoană asistată", "persoana asistata")),
    ("CIVIL_PROTECTION", ("adapost", "adăpost", "protectie civila", "protecție civilă", "alarmare", "sirena", "sirene")),
    ("PREVENTION", ("preven", "recomand", "informare", "campanie", "reguli de comportare")),
)

GENERIC_ANCHOR_TEXT = {
    "citeste mai mult",
    "citește mai mult",
    "detalii",
    "urmatoarea",
    "următoarea",
    "anterioara",
    "anterioară",
    "stiri locale",
    "știri locale",
    "comunicate de presa",
    "comunicate de presă",
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
    return "EMERGENCY_OTHER"


def _source_path(source_kind: str) -> str:
    return urlsplit(SOURCE_URLS[source_kind]).path.rstrip("/")


def _is_article_target(source_kind: str, target_url: str) -> bool:
    parsed = urlsplit(target_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return False
    if parsed.username or parsed.password or parsed.port not in (None, 443):
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
        if not title or normalized_title in {_normalize(item) for item in GENERIC_ANCHOR_TEXT}:
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
    if final.username or final.password or final.port not in (None, 443):
        raise ValueError("source_redirect_identity_invalid")
    if final.path.rstrip("/") != expected.path.rstrip("/"):
        raise ValueError("source_redirect_changed_resource_identity")


def _fetch_source(url: str, timeout: float = 20.0) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = response.geturl()
        _validate_final_source_url(url, final_url)
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"source_http_status:{status}")
        body = response.read(3_000_001)
        if not body or len(body) > 3_000_000:
            raise RuntimeError("source_body_empty_or_too_large")
        return body, final_url


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
        except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError, OSError) as exc:
            failures.append({
                "source_kind": source_kind,
                "source_page_url": source_url,
                "error": f"{type(exc).__name__}:{exc}",
            })

    deduped: dict[str, Reference] = {}
    for ref in references:
        current = deduped.get(ref.target_url)
        if current is None or len(ref.title) > len(current.title):
            deduped[ref.target_url] = ref
    selected = list(deduped.values())[:MAX_REFERENCES]

    digest_basis = "|".join(page["source_page_sha256"] for page in source_pages) + "|" + PARSER_VERSION
    if len(source_pages) != len(SOURCE_URLS):
        status = "HOLD_SOURCE_FETCH_FAILED"
    elif not selected:
        status = "HOLD_NO_REFERENCES"
    else:
        status = "PASS"

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
        "coverage_note": "BOUNDED_FIRST_PARTY_EMERGENCY_MEDIA_INDEX_DISCOVERY_NOT_EXHAUSTIVE",
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
            "casualty_or_intervention_counts_require_detail_verification": True,
            "incident_cause_requires_detail_or_independent_verification": True,
            "current_restrictions_and_warnings_require_separate_current_verification": True,
            "linked_detail_requires_separate_field_level_verification": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        **NON_AUTHORIZING_FLAGS,
    }


def self_test() -> int:
    fixture = """
    <html><body>
      <a href='/stiri-locale/accident-rutier-urmat-de-incendiu-100'>Accident rutier urmat de incendiu în Băile Olănești</a>
      <a href='/stiri-locale/incendiu-gospodarie-101'>Incendiu izbucnit la o gospodărie din Copăceni</a>
      <a href='/stiri-locale/incendiu-gospodarie-101'>Citește mai mult</a>
      <a href='https://example.invalid/story'>Incendiu extern</a>
      <a href='/comunicate-de-presa/alta-pagina-5'>Altă secțiune</a>
    </body></html>
    """.encode("utf-8")
    refs = parse_source_page("LOCAL_NEWS", SOURCE_URLS["LOCAL_NEWS"], fixture)
    if len(refs) != 2:
        raise AssertionError(refs)
    topics = {ref.topic_class for ref in refs}
    if topics != {"ROAD_RESCUE", "FIRE"}:
        raise AssertionError(topics)
    if not all(ref.target_url.startswith(SOURCE_URLS["LOCAL_NEWS"] + "/") for ref in refs):
        raise AssertionError(refs)
    if not all(re.fullmatch(r"[0-9a-f]{64}", ref.evidence_sha256) for ref in refs):
        raise AssertionError("evidence hash missing")

    local_fixture = fixture
    comm_fixture = fixture.replace(b"/stiri-locale/", b"/comunicate-de-presa/")
    sample_pages = {
        SOURCE_URLS["LOCAL_NEWS"]: (local_fixture, SOURCE_URLS["LOCAL_NEWS"]),
        SOURCE_URLS["COMMUNIQUES"]: (comm_fixture, SOURCE_URLS["COMMUNIQUES"]),
    }

    def fake_fetch(url: str) -> tuple[bytes, str]:
        return sample_pages[url]

    receipt = build_receipt(fake_fetch)
    if receipt["status"] != "PASS" or receipt["source_page_count"] != 2:
        raise AssertionError(receipt)
    if receipt["material_fact_use"] or receipt["publication_authorized"] or receipt["fact_kernel_write_authorized"]:
        raise AssertionError("non-authorizing boundary weakened")
    if not receipt["limitations"]["casualty_or_intervention_counts_require_detail_verification"]:
        raise AssertionError("count verification boundary missing")
    print(json.dumps({"schema": SCHEMA, "self_test": "PASS", "references": receipt["reference_count"]}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded first-party ISU Vâlcea emergency reference adapter")
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
