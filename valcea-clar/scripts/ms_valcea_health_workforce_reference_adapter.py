#!/usr/bin/env python3
"""Bounded first-party Ministry of Health workforce references for VÂLCEA CLAR.

This adapter discovers Ministry of Health career references that explicitly name
Spitalul Județean de Urgență Vâlcea and, for a bounded subset, captures the exact
first-party detail page as additional newsroom evidence. Index/detail presence,
publication-date text and role/specialty language remain reference context only:
they do not authorize current vacancy status, deadlines, eligibility, salary,
staffing conclusions, service capacity or publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

INDEX_URL = "https://www.ms.ro/ro/minister/cariera-medici/"
ALLOWED_HOSTS = {"www.ms.ro", "ms.ro"}
ALLOWED_PATH_PREFIX = "/ro/minister/cariera-medici/"
MAX_PAGES = 6
MAX_REFERENCES = 16
MAX_DETAIL_FETCHES = 8
PARSER_VERSION = "MS_VALCEA_HEALTH_WORKFORCE_REFERENCE_V1"
SOURCE_FAMILY = "MS_HEALTH_WORKFORCE"
AUTHORITY_CLASS = "FIRST_PARTY_HEALTH_MINISTRY_CAREER_REFERENCE"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
USER_AGENT = "VALCEA-CLAR-source-intelligence/1.0 (+https://valceaclar.ro/)"

TOPIC_VACANCY = "HEALTH_WORKFORCE_VACANCY_REFERENCE"
TOPIC_RESULT = "HEALTH_WORKFORCE_RESULT_REFERENCE"
TOPIC_CORRECTION = "HEALTH_WORKFORCE_CORRECTION_REFERENCE"
TOPIC_OTHER = "HEALTH_WORKFORCE_OTHER_REFERENCE"

DETAIL_CAPTURED = "DETAIL_FIRST_PARTY_CAPTURED_NON_AUTHORIZING"
DETAIL_ROLE_CONTEXT = "EXPLICIT_DETAIL_ROLE_TEXT_RETAINED_NON_AUTHORIZING"
DETAIL_ROLE_UNRESOLVED = "DETAIL_PAGE_CAPTURED_ROLE_TEXT_UNRESOLVED"
DETAIL_FETCH_FAILED = "DETAIL_FETCH_FAILED_NON_AUTHORIZING"
DETAIL_NOT_FETCHED_BOUND = "DETAIL_NOT_FETCHED_BOUNDED"

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

STOP_DETAIL_MARKERS = (
    "distribuiti aceasta pagina",
    "ultimele postari",
    "lista completa",
    "contact",
)
ROLE_DETAIL_MARKERS = (
    "medic",
    "medici",
    "specialist",
    "specialisti",
    "rezident",
    "rezidenti",
    "post vacant",
    "posturi vacante",
    "specialitatea",
    "specialitate",
    "sectia",
    "sectie",
    "compartiment",
    "upu",
    "smurd",
)
ROMANIAN_MONTHS = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
)


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
    detail_fetch_state: str = DETAIL_NOT_FETCHED_BOUND
    detail_page_url: str | None = None
    detail_page_sha256: str | None = None
    detail_title: str | None = None
    publication_date_text_candidate: str | None = None
    detail_context_snippets: tuple[str, ...] = ()
    role_specialty_context_state: str | None = None
    detail_evidence_sha256: str | None = None
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


class BlockTextParser(HTMLParser):
    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in self.BLOCK_TAGS:
            return
        if self._depth == 0:
            self._parts = []
        self._depth += 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() not in self.BLOCK_TAGS or self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0:
            text = " ".join("".join(self._parts).split())
            if text:
                self.blocks.append(text)
            self._parts = []


def _normalize_text(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
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
    return urlunsplit(("https", host, parts.path, "", ""))


def _path_identity(url: str) -> str:
    return unquote(urlsplit(url).path).rstrip("/")


def _page_url(page: int) -> str:
    if page <= 1:
        return INDEX_URL
    return f"{INDEX_URL}?{urlencode({'page': page})}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _reference_hash(title: str, url: str, topic_class: str, source_sha256: str) -> str:
    basis = "\n".join((title, url, topic_class, source_sha256, PARSER_VERSION))
    return _sha256_text(basis)


def _extract_references(html_bytes: bytes, source_page_url: str) -> list[Reference]:
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


def _publication_date_candidate(blocks: list[str], title_index: int) -> str | None:
    month_pattern = "|".join(ROMANIAN_MONTHS)
    pattern = re.compile(rf"\b(?:[0-3]?\d)\s+(?:{month_pattern})\s+20\d{{2}}\b", re.IGNORECASE)
    for block in reversed(blocks[max(0, title_index - 4):title_index]):
        match = pattern.search(_normalize_text(block))
        if match:
            return " ".join(block.split())
    return None


def _detail_hash(
    detail_url: str,
    detail_sha256: str,
    detail_title: str,
    publication_date: str | None,
    snippets: tuple[str, ...],
) -> str:
    basis = json.dumps(
        {
            "detail_url": detail_url,
            "detail_sha256": detail_sha256,
            "detail_title": detail_title,
            "publication_date_text_candidate": publication_date,
            "detail_context_snippets": list(snippets),
            "parser_version": PARSER_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(basis)


def _extract_detail_context(html_bytes: bytes, detail_url: str, expected_title: str) -> dict[str, Any]:
    parser = BlockTextParser()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    blocks = parser.blocks

    expected_normalized = _normalize_text(expected_title)
    title_index: int | None = None
    for index, block in enumerate(blocks):
        normalized = _normalize_text(block)
        if normalized == expected_normalized or _is_valcea_hospital_title(block):
            title_index = index
            break
    if title_index is None:
        raise RuntimeError("DETAIL_HOSPITAL_IDENTITY_NOT_FOUND")

    detail_title = blocks[title_index]
    if not _is_valcea_hospital_title(detail_title):
        raise RuntimeError("DETAIL_HOSPITAL_IDENTITY_MISMATCH")

    body_blocks: list[str] = []
    for block in blocks[title_index + 1:]:
        normalized = _normalize_text(block)
        if any(normalized.startswith(marker) for marker in STOP_DETAIL_MARKERS):
            break
        if len(block) > 500:
            block = block[:500].rstrip()
        if block:
            body_blocks.append(block)
        if len(body_blocks) >= 24:
            break

    snippets: list[str] = []
    for block in body_blocks:
        normalized = _normalize_text(block)
        if not any(marker in normalized for marker in ROLE_DETAIL_MARKERS):
            continue
        compact = " ".join(block.split())
        if len(compact) < 8:
            continue
        if len(compact) > 240:
            compact = compact[:240].rstrip()
        if compact not in snippets:
            snippets.append(compact)
        if len(snippets) >= 8:
            break

    publication_date = _publication_date_candidate(blocks, title_index)
    detail_sha = _sha256_bytes(html_bytes)
    snippet_tuple = tuple(snippets)
    role_state = DETAIL_ROLE_CONTEXT if snippet_tuple else DETAIL_ROLE_UNRESOLVED
    return {
        "detail_fetch_state": DETAIL_CAPTURED,
        "detail_page_url": detail_url,
        "detail_page_sha256": detail_sha,
        "detail_title": detail_title,
        "publication_date_text_candidate": publication_date,
        "detail_context_snippets": snippet_tuple,
        "role_specialty_context_state": role_state,
        "detail_evidence_sha256": _detail_hash(
            detail_url,
            detail_sha,
            detail_title,
            publication_date,
            snippet_tuple,
        ),
    }


def _fetch(url: str, timeout: float) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:  # nosec B310: strict allowlist below
        final_url = response.geturl()
        parts = urlsplit(final_url)
        if parts.scheme.lower() != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
            raise RuntimeError("SOURCE_IDENTITY_REDIRECT_OUTSIDE_ALLOWLIST")
        if parts.username or parts.password or parts.port not in (None, 443):
            raise RuntimeError("SOURCE_IDENTITY_REDIRECT_AUTHORITY_INVALID")
        if not parts.path.startswith(ALLOWED_PATH_PREFIX):
            raise RuntimeError("SOURCE_IDENTITY_PATH_OUTSIDE_ALLOWLIST")
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("SOURCE_BODY_LIMIT_EXCEEDED")
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.casefold():
            raise RuntimeError("SOURCE_CONTENT_TYPE_NOT_HTML")
        return body, final_url


def _capture_detail(ref: Reference, timeout: float) -> tuple[Reference, dict[str, Any]]:
    try:
        body, final_url = _fetch(ref.url, timeout)
        if _path_identity(final_url) != _path_identity(ref.url):
            raise RuntimeError("DETAIL_IDENTITY_REDIRECT_MISMATCH")
        canonical_final = _canonical_reference_url(ref.url, final_url)
        if canonical_final is None:
            raise RuntimeError("DETAIL_IDENTITY_INVALID")
        context = _extract_detail_context(body, canonical_final, ref.title)
        enriched = replace(ref, **context)
        receipt = {
            "reference_url": ref.url,
            "final_url": canonical_final,
            "state": DETAIL_CAPTURED,
            "detail_page_sha256": context["detail_page_sha256"],
            "detail_evidence_sha256": context["detail_evidence_sha256"],
            "role_specialty_context_state": context["role_specialty_context_state"],
            "publication_date_text_candidate_present": bool(context["publication_date_text_candidate"]),
            "detail_context_snippet_count": len(context["detail_context_snippets"]),
        }
        return enriched, receipt
    except (HTTPError, URLError, TimeoutError, ssl.SSLError, RuntimeError) as exc:
        failed = replace(ref, detail_fetch_state=DETAIL_FETCH_FAILED)
        return failed, {
            "reference_url": ref.url,
            "state": DETAIL_FETCH_FAILED,
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }


def collect_live(
    max_pages: int = MAX_PAGES,
    max_detail_fetches: int = MAX_DETAIL_FETCHES,
    timeout: float = 20.0,
) -> dict:
    max_pages = max(1, min(int(max_pages), MAX_PAGES))
    max_detail_fetches = max(0, min(int(max_detail_fetches), MAX_DETAIL_FETCHES))
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    page_receipts: list[dict[str, Any]] = []
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
            "detail_receipts": [],
            "references": [],
            "reference_count": 0,
            "detail_attempt_count": 0,
            "detail_capture_count": 0,
            "detail_failure_count": 0,
            **NON_AUTHORIZING_FLAGS,
        }

    enriched: list[Reference] = []
    detail_receipts: list[dict[str, Any]] = []
    for index, ref in enumerate(collected[:MAX_REFERENCES]):
        if index >= max_detail_fetches:
            enriched.append(ref)
            continue
        detail_ref, detail_receipt = _capture_detail(ref, timeout)
        enriched.append(detail_ref)
        detail_receipts.append(detail_receipt)

    detail_capture_count = sum(1 for item in detail_receipts if item["state"] == DETAIL_CAPTURED)
    detail_failure_count = sum(1 for item in detail_receipts if item["state"] == DETAIL_FETCH_FAILED)

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
        "references": [asdict(ref) for ref in enriched],
        "reference_count": len(enriched),
        "detail_attempt_count": len(detail_receipts),
        "detail_capture_count": detail_capture_count,
        "detail_failure_count": detail_failure_count,
        "detail_coverage_note": "BOUNDED_FIRST_PARTY_DETAIL_CAPTURE_NOT_EXHAUSTIVE_NON_AUTHORIZING",
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

    detail_fixture = """
    <html><body>
      <p>20 August 2026</p>
      <h2>Anunt concurs - Spitalul Judetean de Urgenta Valcea</h2>
      <p>Concurs de ocupare a cinci posturi vacante de medic specialist medicina de urgenta</p>
      <p>Spitalul Judeţean de Urgenţă Vâlcea organizează concurs pentru 5 posturi de medici specialişti la UPU - SMURD.</p>
      <h6>Distribuiți această pagină</h6>
      <h2>Ultimele postări</h2>
      <p>Medic specialist cardiologie - Spitalul Județean Slatina</p>
    </body></html>
    """.encode("utf-8")
    detail_url = "https://www.ms.ro/ro/minister/cariera-medici/anunt-concurs-spitalul-judetean-de-urgenta-valcea-25/"
    detail = _extract_detail_context(detail_fixture, detail_url, "Anunt concurs - Spitalul Judetean de Urgenta Valcea")
    assert detail["detail_fetch_state"] == DETAIL_CAPTURED
    assert detail["publication_date_text_candidate"] == "20 August 2026"
    assert detail["role_specialty_context_state"] == DETAIL_ROLE_CONTEXT
    assert len(detail["detail_context_snippets"]) == 2
    assert all("Slatina" not in item for item in detail["detail_context_snippets"])
    assert re.fullmatch(r"[0-9a-f]{64}", detail["detail_page_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", detail["detail_evidence_sha256"])
    assert _path_identity(detail_url) == _path_identity(detail_url + "?utm_source=x#fragment")

    sample = {**NON_AUTHORIZING_FLAGS}
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

    attempts = payload.get("detail_attempt_count")
    captures = payload.get("detail_capture_count")
    failures = payload.get("detail_failure_count")
    if not isinstance(attempts, int) or not (0 <= attempts <= MAX_DETAIL_FETCHES):
        raise AssertionError("invalid detail_attempt_count")
    if not isinstance(captures, int) or not (0 <= captures <= attempts):
        raise AssertionError("invalid detail_capture_count")
    if not isinstance(failures, int) or failures != attempts - captures:
        raise AssertionError("invalid detail_failure_count")
    if require_reference and attempts and captures < 1:
        raise AssertionError("NO_BOUNDED_FIRST_PARTY_DETAIL_CAPTURE_OBSERVED")

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

        detail_state = ref.get("detail_fetch_state")
        if detail_state == DETAIL_CAPTURED:
            if _path_identity(ref["detail_page_url"]) != _path_identity(ref["url"]):
                raise AssertionError("detail identity does not match reference")
            if not _is_valcea_hospital_title(ref.get("detail_title", "")):
                raise AssertionError("detail title lost explicit Vâlcea hospital identity")
            for hash_key in ("detail_page_sha256", "detail_evidence_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", ref.get(hash_key, "")):
                    raise AssertionError(f"invalid {hash_key}")
            if ref.get("role_specialty_context_state") not in {DETAIL_ROLE_CONTEXT, DETAIL_ROLE_UNRESOLVED}:
                raise AssertionError("invalid role_specialty_context_state")
            if len(ref.get("detail_context_snippets", [])) > 8:
                raise AssertionError("detail snippet bound exceeded")
        elif detail_state not in {DETAIL_FETCH_FAILED, DETAIL_NOT_FETCHED_BOUND}:
            raise AssertionError("invalid detail_fetch_state")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--max-detail-fetches", type=int, default=MAX_DETAIL_FETCHES)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        self_test()
        return 0
    if not args.live_check:
        parser.error("choose --self-test or --live-check")

    payload = collect_live(
        max_pages=args.max_pages,
        max_detail_fetches=args.max_detail_fetches,
        timeout=args.timeout,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    try:
        _validate_live(payload, require_reference=args.require_reference)
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "MS Vâlcea health workforce live reference check: PASS "
        f"({payload['reference_count']} refs / {payload['detail_capture_count']} detail captures)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
