#!/usr/bin/env python3
"""Bounded first-party Ministry of Health workforce references for VÂLCEA CLAR.

This adapter discovers only Ministry of Health career references that explicitly name
Spitalul Județean de Urgență Vâlcea. It is deliberately reference-only: index/detail
presence is not evidence that a vacancy is currently open or that any deadline,
eligibility, salary, staffing level, service capacity, treatment availability or
other material fact is current.
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
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

INDEX_URL = "https://www.ms.ro/ro/minister/cariera-medici/"
ALLOWED_HOSTS = {"www.ms.ro", "ms.ro"}
ALLOWED_PATH_PREFIX = "/ro/minister/cariera-medici/"
MAX_PAGES = 6
MAX_REFERENCES = 16
PARSER_VERSION = "MS_VALCEA_HEALTH_WORKFORCE_REFERENCE_V1"
SOURCE_FAMILY = "MS_HEALTH_WORKFORCE"
AUTHORITY_CLASS = "FIRST_PARTY_HEALTH_MINISTRY_CAREER_REFERENCE"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
USER_AGENT = "VALCEA-CLAR-source-intelligence/1.0 (+https://valceaclar.ro/)"

TOPIC_VACANCY = "HEALTH_WORKFORCE_VACANCY_REFERENCE"
TOPIC_RESULT = "HEALTH_WORKFORCE_RESULT_REFERENCE"
TOPIC_CORRECTION = "HEALTH_WORKFORCE_CORRECTION_REFERENCE"
TOPIC_OTHER = "HEALTH_WORKFORCE_OTHER_REFERENCE"

NON_AUTHORIZING_FLAGS = {
    "current_vacancy_authorized": False,
    "deadline_authorized": False,
    "eligibility_authorized": False,
    "salary_authorized": False,
    "staffing_shortage_authorized": False,
    "staffing_level_authorized": False,
    "service_capacity_authorized": False,
    "treatment_availability_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
}


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


@dataclass(frozen=True)
class Reference:
    title: str
    url: str
    topic_class: str
    source_page_url: str
    source_page_sha256: str
    evidence_sha256: str
    parser_version: str = PARSER_VERSION
    source_family: str = SOURCE_FAMILY
    authority_class: str = AUTHORITY_CLASS
    observation_state: str = OBSERVATION_STATE


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.anchors: list[Anchor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        values = dict(attrs)
        href = values.get("href")
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
        self.anchors.append(Anchor(href=self._href, text=text))
        self._href = None
        self._parts = []


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("ţ", "t").replace("ş", "s")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _is_valcea_hospital_title(title: str) -> bool:
    normalized = _normalize_text(title)
    full_name = "spitalul judetean de urgenta valcea"
    compact_name = "spital judetean de urgenta valcea"
    return full_name in normalized or compact_name in normalized or "sju valcea" in normalized


def _classify(title: str) -> str:
    normalized = _normalize_text(title)
    if any(token in normalized for token in ("rectific", "corect", "erata")):
        return TOPIC_CORRECTION
    if any(token in normalized for token in ("rezultat", "rezultate", "solutionare contest")):
        return TOPIC_RESULT
    if any(token in normalized for token in ("concurs", "post vacant", "posturi vacante", "angaj")):
        return TOPIC_VACANCY
    return TOPIC_OTHER


def _canonical_reference_url(base_url: str, href: str) -> str | None:
    candidate = urljoin(base_url, href)
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        return None
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return None
    if parts.username or parts.password or parts.port not in (None, 443):
        return None
    if not parts.path.startswith(ALLOWED_PATH_PREFIX):
        return None
    # Detail identity is path-only; query/fragment values do not authorize identity.
    return urlunsplit(("https", host, parts.path, "", ""))


def _page_url(page: int) -> str:
    if page <= 1:
        return INDEX_URL
    return f"{INDEX_URL}?{urlencode({'page': page})}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reference_hash(title: str, url: str, topic_class: str, source_sha256: str) -> str:
    basis = "\n".join((title, url, topic_class, source_sha256, PARSER_VERSION)).encode("utf-8")
    return _sha256_bytes(basis)


def _extract_references(html_bytes: bytes, source_page_url: str) -> list[Reference]:
    try:
        html_text = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html_text = html_bytes.decode("utf-8", errors="replace")
    parser = AnchorParser()
    parser.feed(html_text)
    source_hash = _sha256_bytes(html_bytes)
    references: list[Reference] = []
    for anchor in parser.anchors:
        if not anchor.text or not _is_valcea_hospital_title(anchor.text):
            continue
        canonical_url = _canonical_reference_url(source_page_url, anchor.href)
        if canonical_url is None:
            continue
        topic = _classify(anchor.text)
        references.append(
            Reference(
                title=anchor.text,
                url=canonical_url,
                topic_class=topic,
                source_page_url=source_page_url,
                source_page_sha256=source_hash,
                evidence_sha256=_reference_hash(anchor.text, canonical_url, topic, source_hash),
            )
        )
    return references


def _fetch(url: str, timeout: float) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:  # nosec B310: strict allowlist below
        final_url = response.geturl()
        parts = urlsplit(final_url)
        if parts.scheme.lower() != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
            raise RuntimeError("SOURCE_IDENTITY_REDIRECT_OUTSIDE_ALLOWLIST")
        if not parts.path.startswith(ALLOWED_PATH_PREFIX):
            raise RuntimeError("SOURCE_IDENTITY_PATH_OUTSIDE_ALLOWLIST")
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("SOURCE_BODY_LIMIT_EXCEEDED")
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.casefold():
            raise RuntimeError("SOURCE_CONTENT_TYPE_NOT_HTML")
        return body, final_url


def collect_live(max_pages: int = MAX_PAGES, timeout: float = 20.0) -> dict:
    max_pages = max(1, min(int(max_pages), MAX_PAGES))
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    page_receipts: list[dict] = []
    collected: list[Reference] = []
    seen_urls: set[str] = set()

    try:
        for page in range(1, max_pages + 1):
            requested_url = _page_url(page)
            body, final_url = _fetch(requested_url, timeout)
            refs = _extract_references(body, final_url)
            page_receipts.append(
                {
                    "page": page,
                    "requested_url": requested_url,
                    "final_url": final_url,
                    "source_sha256": _sha256_bytes(body),
                    "reference_candidates": len(refs),
                }
            )
            for ref in refs:
                if ref.url in seen_urls:
                    continue
                seen_urls.add(ref.url)
                collected.append(ref)
                if len(collected) >= MAX_REFERENCES:
                    break
            if len(collected) >= MAX_REFERENCES:
                break
    except (HTTPError, URLError, TimeoutError, ssl.SSLError, RuntimeError) as exc:
        return {
            "schema": PARSER_VERSION,
            "status": "HOLD_SOURCE_FETCH_FAILED",
            "source_family": SOURCE_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            "observation_state": OBSERVATION_STATE,
            "fetched_at": fetched_at,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "page_receipts": page_receipts,
            "references": [],
            "reference_count": 0,
            **NON_AUTHORIZING_FLAGS,
        }

    payload = {
        "schema": PARSER_VERSION,
        "status": "PASS",
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": fetched_at,
        "index_url": INDEX_URL,
        "pages_fetched": len(page_receipts),
        "page_receipts": page_receipts,
        "references": [asdict(ref) for ref in collected[:MAX_REFERENCES]],
        "reference_count": min(len(collected), MAX_REFERENCES),
        "coverage_note": "BOUNDED_FIRST_PARTY_REFERENCE_DISCOVERY_NOT_EXHAUSTIVE",
        **NON_AUTHORIZING_FLAGS,
    }
    stable_basis = json.dumps(
        {key: value for key, value in payload.items() if key != "fetched_at"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["run_id"] = _sha256_bytes(stable_basis)[:24]
    return payload


def _assert_non_authorizing(payload: dict) -> None:
    for key, expected in NON_AUTHORIZING_FLAGS.items():
        if payload.get(key) is not expected:
            raise AssertionError(f"authorization boundary drift: {key}")


def self_test() -> None:
    fixture = """
    <html><body>
      <a href="/ro/minister/cariera-medici/anunt-concurs-spitalul-judetean-de-urgenta-valcea-24/">
        Anunț concurs - Spitalul Județean de Urgență Vâlcea
      </a>
      <a href="/ro/minister/cariera-medici/rezultate-spitalul-judetean-de-urgenta-valcea/">
        Rezultate concurs - Spitalul Judetean de Urgenta Valcea
      </a>
      <a href="/ro/minister/cariera-medici/rectificare-spitalul-judetean-de-urgenta-valcea/">
        Rectificare - Spitalul Judetean de Urgenta Valcea
      </a>
      <a href="https://evil.example/ro/minister/cariera-medici/anunt-spitalul-judetean-de-urgenta-valcea/">
        Anunt concurs - Spitalul Judetean de Urgenta Valcea
      </a>
      <a href="/ro/minister/cariera-medici/anunt-spitalul-judetean-de-urgenta-slatina/">
        Anunt concurs - Spitalul Judetean de Urgenta Slatina
      </a>
    </body></html>
    """.encode("utf-8")
    refs = _extract_references(fixture, INDEX_URL)
    assert len(refs) == 3, refs
    assert {ref.topic_class for ref in refs} == {TOPIC_VACANCY, TOPIC_RESULT, TOPIC_CORRECTION}
    assert all(urlsplit(ref.url).hostname in ALLOWED_HOSTS for ref in refs)
    assert all(ref.url.startswith("https://") for ref in refs)
    assert all(ref.source_page_sha256 == _sha256_bytes(fixture) for ref in refs)
    assert len({ref.evidence_sha256 for ref in refs}) == 3
    assert _canonical_reference_url(INDEX_URL, "http://www.ms.ro/ro/minister/cariera-medici/x/") is None
    assert _canonical_reference_url(INDEX_URL, "https://www.ms.ro/ro/pacienti/x/") is None
    assert _is_valcea_hospital_title("SJU Vâlcea")
    assert not _is_valcea_hospital_title("Spitalul Județean de Urgență Slatina")
    assert _page_url(2).endswith("?page=2")

    sample = {
        "current_vacancy_authorized": False,
        "deadline_authorized": False,
        "eligibility_authorized": False,
        "salary_authorized": False,
        "staffing_shortage_authorized": False,
        "staffing_level_authorized": False,
        "service_capacity_authorized": False,
        "treatment_availability_authorized": False,
        "breaking_authorized": False,
        "fact_kernel_write_authorized": False,
        "editorial_writer_authorized": False,
        "publication_authorized": False,
        "distribution_authorized": False,
    }
    _assert_non_authorizing(sample)
    print("MS Vâlcea health workforce reference adapter self-test: PASS")


def _validate_live(payload: dict, require_reference: bool) -> None:
    if payload.get("status") != "PASS":
        raise AssertionError(f"source acquisition not healthy: {payload.get('status')} {payload.get('error', '')}")
    if not (1 <= payload.get("pages_fetched", 0) <= MAX_PAGES):
        raise AssertionError("invalid pages_fetched")
    count = payload.get("reference_count")
    if not isinstance(count, int) or not (0 <= count <= MAX_REFERENCES):
        raise AssertionError("invalid reference_count")
    if require_reference and count < 1:
        raise AssertionError("NO_CURRENT_BOUNDED_SJU_VALCEA_REFERENCE_OBSERVED")
    _assert_non_authorizing(payload)
    for ref in payload.get("references", []):
        parts = urlsplit(ref["url"])
        if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
            raise AssertionError("reference escaped first-party allowlist")
        if not parts.path.startswith(ALLOWED_PATH_PREFIX):
            raise AssertionError("reference escaped career path")
        if not _is_valcea_hospital_title(ref["title"]):
            raise AssertionError("reference lost explicit Vâlcea hospital identity")
        for hash_key in ("source_page_sha256", "evidence_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", ref.get(hash_key, "")):
                raise AssertionError(f"invalid {hash_key}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        self_test()
        return 0
    if not args.live_check:
        parser.error("choose --self-test or --live-check")

    payload = collect_live(max_pages=args.max_pages, timeout=args.timeout)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    try:
        _validate_live(payload, require_reference=args.require_reference)
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"MS Vâlcea health workforce live reference check: PASS ({payload['reference_count']} refs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
