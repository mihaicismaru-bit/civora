#!/usr/bin/env python3
"""Bounded first-party Posturi.gov.ro references for VÂLCEA CLAR.

The county index is used only to discover public-sector job references for Vâlcea.
References are non-authorizing: they do not by themselves prove that a vacancy is
currently open or that any deadline, eligibility, salary, staffing, service-capacity
or other reader-facing material fact is current.

When the first-party detail summary explicitly names the publishing institution,
that identity is retained as evidence-bound newsroom context. Institution identity
does not authorize institution status, vacancy identity, staffing need, deduplication
or publication.
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
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

INDEX_URL = "https://posturi.gov.ro/judet/valcea/"
ALLOWED_HOSTS = {"posturi.gov.ro", "www.posturi.gov.ro"}
INDEX_PATH = "/judet/valcea/"
JOB_PATH_PREFIX = "/joburi/"
MAX_JOB_LINKS = 24
MAX_DETAILS = 16
PARSER_VERSION = "POSTURI_GOV_VALCEA_REFERENCE_V1"
SOURCE_FAMILY = "POSTURI_GOV_VALCEA"
AUTHORITY_CLASS = "FIRST_PARTY_GOVERNMENT_PUBLIC_JOBS_REFERENCE"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"
USER_AGENT = "VALCEA-CLAR-source-intelligence/1.0 (+https://valceaclar.ro/)"

TOPIC_HEALTH = "PUBLIC_JOBS_HEALTH_REFERENCE"
TOPIC_ADMIN = "PUBLIC_JOBS_ADMINISTRATION_REFERENCE"
TOPIC_EDUCATION = "PUBLIC_JOBS_EDUCATION_REFERENCE"
TOPIC_PUBLIC_SERVICE = "PUBLIC_JOBS_PUBLIC_SERVICE_REFERENCE"
TOPIC_OTHER = "PUBLIC_JOBS_OTHER_REFERENCE"

INSTITUTION_EXPLICIT = "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY"
INSTITUTION_UNRESOLVED = "UNRESOLVED_FROM_FIRST_PARTY_DETAIL_SUMMARY"
INSTITUTION_KEYWORDS = (
    "spital", "primaria", "liceul", "liceu", "scoala", "colegiul", "colegiu",
    "comuna", "directia", "serviciul", "oficiul", "muzeul", "muzeu",
    "biblioteca", "agentia", "inspectoratul", "universitatea", "universitate",
    "centrul", "centru", "casa judeteana", "consiliul judetean",
)

NON_AUTHORIZING_FLAGS = {
    "current_vacancy_authorized": False,
    "deadline_authorized": False,
    "eligibility_authorized": False,
    "salary_authorized": False,
    "staffing_shortage_authorized": False,
    "service_capacity_authorized": False,
    "institution_status_authorized": False,
    "same_vacancy_inference_authorized": False,
    "same_need_inference_authorized": False,
    "dedupe_authorized": False,
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
    institution_name: str | None
    institution_identity_state: str
    institution_evidence_sha256: str | None
    index_url: str
    index_sha256: str
    detail_sha256: str
    evidence_sha256: str
    parser_version: str = PARSER_VERSION
    source_family: str = SOURCE_FAMILY
    authority_class: str = AUTHORITY_CLASS
    observation_state: str = OBSERVATION_STATE


class LinkAndHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self._ignored_depth = 0
        self.anchors: list[Anchor] = []
        self.headings: list[str] = []
        self.text_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if lower == "a" and self._href is None:
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._anchor_parts = []
        elif lower == "h1" and not self._in_h1:
            self._in_h1 = True
            self._h1_parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.text_chunks.append(text)
        if self._href is not None:
            self._anchor_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if lower == "a" and self._href is not None:
            text = " ".join("".join(self._anchor_parts).split())
            self.anchors.append(Anchor(href=self._href, text=text))
            self._href = None
            self._anchor_parts = []
        elif lower == "h1" and self._in_h1:
            text = " ".join("".join(self._h1_parts).split())
            if text:
                self.headings.append(text)
            self._in_h1 = False
            self._h1_parts = []


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_job_url(base_url: str, href: str) -> str | None:
    candidate = urljoin(base_url, href)
    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        return None
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return None
    if parts.username or parts.password or parts.port not in (None, 443):
        return None
    if not parts.path.startswith(JOB_PATH_PREFIX):
        return None
    return urlunsplit(("https", host, parts.path, "", ""))


def _parse(html_bytes: bytes) -> LinkAndHeadingParser:
    parser = LinkAndHeadingParser()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    return parser


def _extract_job_urls(html_bytes: bytes, source_url: str) -> list[str]:
    parser = _parse(html_bytes)
    result: list[str] = []
    seen: set[str] = set()
    for anchor in parser.anchors:
        url = _canonical_job_url(source_url, anchor.href)
        if url is None or url in seen:
            continue
        seen.add(url)
        result.append(url)
        if len(result) >= MAX_JOB_LINKS:
            break
    return result


def _extract_title(html_bytes: bytes) -> str | None:
    parser = _parse(html_bytes)
    for heading in parser.headings:
        normalized = _normalize(heading)
        if normalized and normalized not in {"posturi gov ro", "posturi vacante"}:
            return heading
    return None


def _looks_like_institution(value: str) -> bool:
    normalized = _normalize(value)
    if not normalized or normalized in {"valcea", "ramnicu valcea"}:
        return False
    if len(value) > 220:
        return False
    return any(token in normalized for token in INSTITUTION_KEYWORDS)


def _extract_institution(html_bytes: bytes, title: str) -> tuple[str | None, str]:
    """Retain only an institution explicitly visible in the bounded page summary."""
    parser = _parse(html_bytes)
    title_norm = _normalize(title)
    chunks = parser.text_chunks[:120]
    start = 0
    for idx, chunk in enumerate(chunks):
        if _normalize(chunk) == title_norm:
            start = idx + 1
            break

    summary: list[str] = []
    for chunk in chunks[start:start + 32]:
        normalized = _normalize(chunk)
        if normalized in {"despre acest post", "despre post"}:
            break
        summary.append(chunk)

    for chunk in summary[:16]:
        if _looks_like_institution(chunk):
            return " ".join(chunk.split()), INSTITUTION_EXPLICIT
    return None, INSTITUTION_UNRESOLVED


def _classify(title: str, detail_text: str) -> str:
    text = _normalize(title + " " + detail_text[:16000])
    if any(token in text for token in (
        "spital", "medic", "medical", "asistent medical", "infirmier", "sanitar", "farmacist",
    )):
        return TOPIC_HEALTH
    if any(token in text for token in (
        "primaria", "consiliul local", "consiliul judetean", "prefectura", "serviciul public",
    )):
        return TOPIC_ADMIN
    if any(token in text for token in (
        "scoala", "liceu", "gradinita", "universit", "profesor", "educatie",
    )):
        return TOPIC_EDUCATION
    if any(token in text for token in (
        "apa", "transport", "salubrit", "bibliotec", "muzeu", "cultura", "directia",
    )):
        return TOPIC_PUBLIC_SERVICE
    return TOPIC_OTHER


def _institution_evidence_hash(name: str, url: str, detail_sha: str) -> str:
    return _sha256("\n".join((name, url, detail_sha, PARSER_VERSION, INSTITUTION_EXPLICIT)).encode("utf-8"))


def _evidence_hash(
    title: str,
    url: str,
    topic: str,
    institution_name: str | None,
    institution_state: str,
    institution_hash: str | None,
    index_sha: str,
    detail_sha: str,
) -> str:
    basis = "\n".join((
        title, url, topic, institution_name or "", institution_state, institution_hash or "",
        index_sha, detail_sha, PARSER_VERSION,
    )).encode("utf-8")
    return _sha256(basis)


def _fetch(url: str, *, expected: str, timeout: float) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:  # nosec B310: strict identity checks below
        final_url = response.geturl()
        parts = urlsplit(final_url)
        if parts.scheme.lower() != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
            raise RuntimeError("SOURCE_IDENTITY_REDIRECT_OUTSIDE_ALLOWLIST")
        if expected == "index" and parts.path.rstrip("/") != INDEX_PATH.rstrip("/"):
            raise RuntimeError("SOURCE_INDEX_PATH_DRIFT")
        if expected == "job" and not parts.path.startswith(JOB_PATH_PREFIX):
            raise RuntimeError("SOURCE_JOB_PATH_DRIFT")
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.casefold():
            raise RuntimeError("SOURCE_CONTENT_TYPE_NOT_HTML")
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("SOURCE_BODY_LIMIT_EXCEEDED")
        return body, final_url


def collect_live(max_details: int = MAX_DETAILS, timeout: float = 20.0) -> dict:
    max_details = max(1, min(int(max_details), MAX_DETAILS))
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        index_body, final_index = _fetch(INDEX_URL, expected="index", timeout=timeout)
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
            "references": [],
            "reference_count": 0,
            **NON_AUTHORIZING_FLAGS,
        }

    index_sha = _sha256(index_body)
    job_urls = _extract_job_urls(index_body, final_index)
    references: list[Reference] = []
    detail_errors: list[dict] = []

    for job_url in job_urls[:max_details]:
        try:
            detail_body, final_job = _fetch(job_url, expected="job", timeout=timeout)
            text = detail_body.decode("utf-8", errors="replace")
            if "valcea" not in _normalize(text[:80000]):
                detail_errors.append({"url": job_url, "error": "DETAIL_LOST_VALCEA_SIGNAL"})
                continue
            title = _extract_title(detail_body)
            if not title:
                detail_errors.append({"url": job_url, "error": "DETAIL_TITLE_NOT_FOUND"})
                continue
            detail_sha = _sha256(detail_body)
            topic = _classify(title, text)
            institution_name, institution_state = _extract_institution(detail_body, title)
            institution_hash = (
                _institution_evidence_hash(institution_name, final_job, detail_sha)
                if institution_name is not None else None
            )
            references.append(
                Reference(
                    title=title,
                    url=final_job,
                    topic_class=topic,
                    institution_name=institution_name,
                    institution_identity_state=institution_state,
                    institution_evidence_sha256=institution_hash,
                    index_url=final_index,
                    index_sha256=index_sha,
                    detail_sha256=detail_sha,
                    evidence_sha256=_evidence_hash(
                        title, final_job, topic, institution_name, institution_state,
                        institution_hash, index_sha, detail_sha,
                    ),
                )
            )
        except (HTTPError, URLError, TimeoutError, ssl.SSLError, RuntimeError) as exc:
            detail_errors.append({"url": job_url, "error_type": type(exc).__name__, "error": str(exc)[:300]})

    payload = {
        "schema": PARSER_VERSION,
        "status": "PASS",
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": fetched_at,
        "index_url": final_index,
        "index_sha256": index_sha,
        "job_links_discovered": len(job_urls),
        "details_attempted": min(len(job_urls), max_details),
        "detail_errors": detail_errors,
        "references": [asdict(ref) for ref in references],
        "reference_count": len(references),
        "institution_identity_contract": "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY_ONLY",
        "coverage_note": "BOUNDED_COUNTY_INDEX_REFERENCE_DISCOVERY_NOT_EXHAUSTIVE",
        **NON_AUTHORIZING_FLAGS,
    }
    stable = json.dumps(
        {key: value for key, value in payload.items() if key != "fetched_at"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["run_id"] = _sha256(stable)[:24]
    return payload


def _assert_non_authorizing(payload: dict) -> None:
    for key, expected in NON_AUTHORIZING_FLAGS.items():
        if payload.get(key) is not expected:
            raise AssertionError(f"authorization boundary drift: {key}")


def self_test() -> None:
    fixture = b'''<html><body>
    <a href="/joburi/medic-specialist/">Detalii</a>
    <a href="https://posturi.gov.ro/joburi/inginer-pedolog/">Detalii</a>
    <a href="https://evil.example/joburi/nope/">Detalii</a>
    <a href="http://posturi.gov.ro/joburi/no-http/">Detalii</a>
    </body></html>'''
    urls = _extract_job_urls(fixture, INDEX_URL)
    assert urls == [
        "https://posturi.gov.ro/joburi/medic-specialist/",
        "https://posturi.gov.ro/joburi/inginer-pedolog/",
    ]

    detail = b'''<html><body><h1>6 posturi de asistent medical generalist</h1>
    <div>Spitalul Judetean de Urgenta Valcea</div><div>Valcea</div>
    <div>Permanent</div><h2>Despre acest post</h2>
    <p>Spitalul Judetean de Urgenta Valcea organizeaza concurs.</p></body></html>'''
    title = _extract_title(detail)
    assert title == "6 posturi de asistent medical generalist"
    institution, state = _extract_institution(detail, title)
    assert institution == "Spitalul Judetean de Urgenta Valcea"
    assert state == INSTITUTION_EXPLICIT
    assert _classify("medic specialist", detail.decode()) == TOPIC_HEALTH

    ambiguous = b'''<html><body><h1>Medic specialist pneumolog</h1>
    <div>Valcea</div><div>Permanent</div><h2>Despre acest post</h2>
    <p>Proba se desfasoara la Spitalul de Pneumoftiziologie.</p></body></html>'''
    assert _extract_institution(ambiguous, "Medic specialist pneumolog") == (None, INSTITUTION_UNRESOLVED)

    assert _classify("inspector", "Primaria Municipiului Ramnicu Valcea") == TOPIC_ADMIN
    assert _classify("profesor", "Liceu tehnologic") == TOPIC_EDUCATION
    assert _classify("sofer", "operator transport public") == TOPIC_PUBLIC_SERVICE
    assert _canonical_job_url(INDEX_URL, "http://posturi.gov.ro/joburi/x/") is None
    assert _canonical_job_url(INDEX_URL, "https://posturi.gov.ro/judet/dolj/") is None
    _assert_non_authorizing(dict(NON_AUTHORIZING_FLAGS))
    print("Posturi.gov.ro Vâlcea reference adapter self-test: PASS")


def _validate_live(payload: dict, require_reference: bool) -> None:
    if payload.get("status") != "PASS":
        raise AssertionError(f"source acquisition not healthy: {payload.get('status')} {payload.get('error', '')}")
    if not re.fullmatch(r"[0-9a-f]{64}", payload.get("index_sha256", "")):
        raise AssertionError("invalid index hash")
    if not (0 <= payload.get("job_links_discovered", -1) <= MAX_JOB_LINKS):
        raise AssertionError("invalid job link count")
    count = payload.get("reference_count")
    if not isinstance(count, int) or not (0 <= count <= MAX_DETAILS):
        raise AssertionError("invalid reference count")
    if require_reference and count < 1:
        raise AssertionError("NO_CURRENT_BOUNDED_VALCEA_PUBLIC_JOB_REFERENCE_OBSERVED")
    if payload.get("institution_identity_contract") != "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY_ONLY":
        raise AssertionError("institution identity contract drift")
    _assert_non_authorizing(payload)

    allowed_topics = {TOPIC_HEALTH, TOPIC_ADMIN, TOPIC_EDUCATION, TOPIC_PUBLIC_SERVICE, TOPIC_OTHER}
    allowed_institution_states = {INSTITUTION_EXPLICIT, INSTITUTION_UNRESOLVED}
    for ref in payload.get("references", []):
        parts = urlsplit(ref["url"])
        if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
            raise AssertionError("reference escaped host allowlist")
        if not parts.path.startswith(JOB_PATH_PREFIX):
            raise AssertionError("reference escaped job path")
        if ref.get("topic_class") not in allowed_topics:
            raise AssertionError("unknown topic class")
        if ref.get("institution_identity_state") not in allowed_institution_states:
            raise AssertionError("unknown institution identity state")
        if ref["institution_identity_state"] == INSTITUTION_EXPLICIT:
            if not ref.get("institution_name") or not _looks_like_institution(ref["institution_name"]):
                raise AssertionError("explicit institution identity missing or invalid")
            if not re.fullmatch(r"[0-9a-f]{64}", ref.get("institution_evidence_sha256", "")):
                raise AssertionError("invalid institution evidence hash")
        else:
            if ref.get("institution_name") is not None or ref.get("institution_evidence_sha256") is not None:
                raise AssertionError("unresolved institution leaked asserted identity")
        for hash_key in ("index_sha256", "detail_sha256", "evidence_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", ref.get(hash_key, "")):
                raise AssertionError(f"invalid {hash_key}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--max-details", type=int, default=MAX_DETAILS)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        self_test()
        return 0
    if not args.live_check:
        parser.error("choose --self-test or --live-check")

    payload = collect_live(max_details=args.max_details, timeout=args.timeout)
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
    print(
        "Posturi.gov.ro Vâlcea live reference check: PASS "
        f"({payload['reference_count']} refs; "
        f"{sum(1 for r in payload['references'] if r['institution_identity_state'] == INSTITUTION_EXPLICIT)} "
        "explicit institutions)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
