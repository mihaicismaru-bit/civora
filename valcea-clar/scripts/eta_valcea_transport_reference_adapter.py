#!/usr/bin/env python3
"""Bounded first-party ETA Râmnicu Vâlcea transport-service references.

The adapter reads only the allow-listed ETA S.A. communications index and emits
newsroom reference candidates for local public-transport intelligence. Index
presence is discovery evidence only: it never proves that a route, timetable,
fare, disruption, entitlement or real-time arrival is current, and it never
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

SCHEMA = "ETA_VALCEA_TRANSPORT_REFERENCE_V1"
PARSER_VERSION = "ETA_VALCEA_TRANSPORT_REFERENCE_ADAPTER_2026_09_02"
SOURCE_FAMILY = "ETA_VALCEA_PUBLIC_TRANSPORT"
AUTHORITY_CLASS = "FIRST_PARTY_LOCAL_PUBLIC_TRANSPORT_OPERATOR_INDEX"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
SOURCE_KIND = "COMMUNIQUES"
SOURCE_URL = "https://eta-bus.ro/comunicate"
ALLOWED_HOSTS = {"eta-bus.ro", "www.eta-bus.ro"}
MAX_REFERENCES = 48
USER_AGENT = "VALCEA-CLAR-first-party-public-transport-reference-check/1.0"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "route_service_current_authorized": False,
    "timetable_current_authorized": False,
    "fare_current_authorized": False,
    "ticketing_current_authorized": False,
    "passenger_entitlement_current_authorized": False,
    "service_disruption_current_authorized": False,
    "realtime_arrival_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ROUTE_CHANGE", (
        "deviere traseu", "devierea traseului", "redirectionarea", "redirecționarea",
        "traseu modificat", "trasee modificate", "statie temporara", "stație temporară",
    )),
    ("SERVICE_DISRUPTION", (
        "intrerup", "întrerup", "suspend", "nu vor circula", "anomalii", "indisponibil",
        "upgrade", "mentenanta", "mentenanță", "skayo", "aplicatie", "aplicație",
    )),
    ("EVENT_TRANSPORT", (
        "raliul", "festival", "concert", "eveniment", "we love music", "deep forest",
        "transport special", "program de circulatie", "program de circulație",
    )),
    ("PASSENGER_ENTITLEMENT", (
        "elev", "student", "pensionar", "gratuit", "gratuitate", "62 ani",
    )),
    ("FARE_TICKETING", (
        "tarif", "bilet", "abonament", "24pay", "24 pay", "card bancar", "validator",
        "titlu de calatorie", "titlu de călătorie",
    )),
    ("ACCESSIBILITY", (
        "dizabil", "deficiente", "deficiențe", "accesibil", "nevazator", "nevăzător",
    )),
)

GENERIC_ANCHOR_TEXT = {
    "citeste mai mult", "citește mai mult", "descarca", "descarcă", "detalii",
    "comunicate", "urmatoarea", "următoarea", "anterioara", "anterioară",
}

ADMIN_EXCLUDE_TERMS = (
    "vanzare", "vânzare", "licitatie", "licitație", "achizitie servicii", "achiziție servicii",
    "angajare", "recrutare",
)


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


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split()).strip()
    cleaned = re.sub(r"^(?:citește|citeste)\s+mai\s+mult\s*[„\"']?", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ”“\"'").strip()


def _topic(title: str) -> str:
    normalized = _normalize(title)
    for topic, needles in TOPIC_RULES:
        if any(_normalize(needle) in normalized for needle in needles):
            return topic
    return "OPERATOR_OTHER"


def _is_admin_only(title: str) -> bool:
    normalized = _normalize(title)
    return any(_normalize(term) in normalized for term in ADMIN_EXCLUDE_TERMS)


def _is_article_target(target_url: str) -> bool:
    parsed = urlsplit(target_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return False
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    path = parsed.path.rstrip("/")
    if path == "/comunicate" or not path.startswith("/comunicate/"):
        return False
    suffix = path[len("/comunicate/"):]
    if not suffix or suffix.startswith("page/"):
        return False
    if re.fullmatch(r"\d{4}", suffix):
        return False
    return True


def parse_source_page(source_url: str, raw: bytes) -> list[Reference]:
    page_hash = _sha256_bytes(raw)
    parser = AnchorParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    generic = {_normalize(item) for item in GENERIC_ANCHOR_TEXT}

    by_target: dict[str, Reference] = {}
    for anchor in parser.anchors:
        raw_title = " ".join(anchor.text.split())
        if not raw_title or _normalize(raw_title) in generic:
            continue
        title = _clean_title(raw_title)
        if not title or _normalize(title) in generic or _is_admin_only(title):
            continue
        target = _canonical_url(urljoin(source_url, anchor.href))
        if not _is_article_target(target):
            continue
        evidence_basis = json.dumps(
            {
                "source_family": SOURCE_FAMILY,
                "source_kind": SOURCE_KIND,
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
            source_kind=SOURCE_KIND,
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
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = response.geturl()
        _validate_final_source_url(url, final_url)
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"source_http_status:{status}")
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.casefold():
            raise RuntimeError(f"source_content_type_unexpected:{content_type}")
        body = response.read(3_000_001)
        if not body or len(body) > 3_000_000:
            raise RuntimeError("source_body_empty_or_too_large")
        normalized = _normalize(body[:200_000].decode("utf-8", errors="replace"))
        if "checking your browser" in normalized or "just a moment" in normalized:
            raise RuntimeError("source_interstitial_detected")
        return body, final_url


def build_receipt(fetcher: Callable[[str], tuple[bytes, str]] = _fetch_source) -> dict[str, Any]:
    source_pages: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    references: list[Reference] = []

    try:
        raw, final_url = fetcher(SOURCE_URL)
        _validate_final_source_url(SOURCE_URL, final_url)
        page_hash = _sha256_bytes(raw)
        references = parse_source_page(SOURCE_URL, raw)
        source_pages.append(
            {
                "source_kind": SOURCE_KIND,
                "source_page_url": SOURCE_URL,
                "final_url": _canonical_url(final_url),
                "source_page_sha256": page_hash,
                "bytes": len(raw),
                "reference_count": len(references),
                "status": "PASS",
            }
        )
    except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError, OSError) as exc:
        failures.append(
            {
                "source_kind": SOURCE_KIND,
                "source_page_url": SOURCE_URL,
                "error": f"{type(exc).__name__}:{exc}",
            }
        )

    selected = references[:MAX_REFERENCES]
    if len(source_pages) != 1:
        status = "HOLD_SOURCE_FETCH_FAILED"
    elif not selected:
        status = "HOLD_NO_REFERENCES"
    else:
        status = "PASS"

    topic_counts: dict[str, int] = {}
    for ref in selected:
        topic_counts[ref.topic_class] = topic_counts.get(ref.topic_class, 0) + 1

    digest_basis = "|".join(page["source_page_sha256"] for page in source_pages) + "|" + PARSER_VERSION
    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "coverage_note": "BOUNDED_FIRST_PARTY_PUBLIC_TRANSPORT_OPERATOR_COMMUNICATIONS_DISCOVERY_NOT_EXHAUSTIVE",
        "status": status,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": _sha256_text(digest_basis)[:24],
        "source_page_count": len(source_pages),
        "reference_count": len(selected),
        "topic_counts": dict(sorted(topic_counts.items())),
        "source_pages": source_pages,
        "references": [asdict(ref) for ref in selected],
        "failures": failures,
        "limitations": {
            "index_presence_is_not_detail_fact_verification": True,
            "current_routes_and_timetables_require_detail_or_live_verification": True,
            "fares_and_ticketing_require_current_detail_verification": True,
            "passenger_entitlements_require_current_detail_verification": True,
            "service_disruptions_require_current_detail_verification": True,
            "realtime_arrivals_require_separate_live_source": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        **NON_AUTHORIZING_FLAGS,
    }


def self_test() -> int:
    fixture = """
    <html><body>
      <a href="/comunicate/deviere-traseu-linia-5">Deviere traseu - Linia 5</a>
      <a href="/comunicate/tarife-01-02-2026">Tarife de transport valabile începând cu 01/02/2026</a>
      <a href="/comunicate/anunt-elevi">Anunț privind eliberarea abonamentelor pentru elevi</a>
      <a href="/comunicate/anunt-elevi">Citește mai mult</a>
      <a href="/comunicate/skayo">Citește mai mult „Comunicat aplicație Skayo AVL”</a>
      <a href="/comunicate/anunt-vanzare">Anunț vânzare autovehicul</a>
      <a href="/comunicate/page/2">Următoarea</a>
      <a href="/comunicate/2025">Comunicate 2025</a>
      <a href="https://new.eta-bus.ro/files/doc.pdf">Document extern</a>
      <a href="https://example.invalid/story">Extern</a>
    </body></html>
    """.encode("utf-8")
    refs = parse_source_page(SOURCE_URL, fixture)
    if len(refs) != 4:
        raise AssertionError(refs)
    topics = {ref.topic_class for ref in refs}
    if topics != {"ROUTE_CHANGE", "FARE_TICKETING", "PASSENGER_ENTITLEMENT", "SERVICE_DISRUPTION"}:
        raise AssertionError(topics)
    titles = {ref.title for ref in refs}
    if "Comunicat aplicație Skayo AVL" not in titles:
        raise AssertionError(titles)
    if any("vânzare" in ref.title.casefold() or "vanzare" in ref.title.casefold() for ref in refs):
        raise AssertionError("administrative sales notice leaked into mobility references")
    if not all(ref.target_url.startswith("https://eta-bus.ro/comunicate/") for ref in refs):
        raise AssertionError(refs)
    if not all(re.fullmatch(r"[0-9a-f]{64}", ref.evidence_sha256) for ref in refs):
        raise AssertionError("evidence hash missing")

    def fake_fetch(url: str) -> tuple[bytes, str]:
        if url != SOURCE_URL:
            raise AssertionError(url)
        return fixture, SOURCE_URL

    receipt = build_receipt(fake_fetch)
    if receipt["status"] != "PASS" or receipt["source_page_count"] != 1:
        raise AssertionError(receipt)
    if receipt["reference_count"] != 4:
        raise AssertionError(receipt)
    if receipt["material_fact_use"] or receipt["publication_authorized"]:
        raise AssertionError("non-authorizing boundary weakened")
    if receipt["timetable_current_authorized"] or receipt["fare_current_authorized"]:
        raise AssertionError("current service boundary weakened")

    def bad_redirect(_: str) -> tuple[bytes, str]:
        return fixture, "https://example.invalid/comunicate"

    held = build_receipt(bad_redirect)
    if held["status"] != "HOLD_SOURCE_FETCH_FAILED":
        raise AssertionError(held)

    print("ETA Vâlcea transport reference adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.live_check:
        parser.error("choose --self-test or --live-check")

    receipt = build_receipt()
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    if receipt["status"] != "PASS":
        return 2
    if args.require_reference and receipt["reference_count"] < 1:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
