#!/usr/bin/env python3
"""Bounded first-party ISU Vâlcea press-release index references for VÂLCEA CLAR."""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import http.client
import json
import re
import sys
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SOURCE_URL = "https://isuvl.igsu.ro/comunicate-de-presa"
SOURCE_HOST = "isuvl.igsu.ro"
SOURCE_PATH = "/comunicate-de-presa"
USER_AGENT = "VALCEA-CLAR-ISU-Valcea-Press-Release-References/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 32
MIN_REFERENCES = 3
REFERENCE_RE = re.compile(r"^/comunicate-de-presa/[a-z0-9-]+-\d+/?$")
CONTENT_CONTRACT = "FIRST_PARTY_EMERGENCY_PRESS_RELEASE_INDEX_REFERENCE_ONLY"

DISABLED_CAPABILITIES = [
    "article_body_fetch",
    "attachment_fetch",
    "media_fetch",
    "image_ingest",
    "incident_detail_extraction",
    "person_or_personal_data_extraction",
    "active_incident_inference",
    "active_warning_inference",
    "service_currentness_inference",
    "breaking_news_promotion",
    "fact_kernel",
    "writer",
    "persistence",
    "public_projection",
    "inferred_photo_rights",
]


class ExternalInputError(RuntimeError):
    pass


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a" or self._href is not None:
            return
        href = dict(attrs).get("href")
        if href is None:
            return
        self._href = href
        self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        self.links.append((" ".join(self._parts).strip(), self._href))
        self._href = None
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is None:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self._parts.append(value)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def ascii_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", normalize_text(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def validate_source_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ExternalInputError("source must use HTTPS")
    if parsed.username or parsed.password:
        raise ExternalInputError("credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalInputError("invalid source port") from exc
    if port not in (None, 443):
        raise ExternalInputError("non-default source port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("unexpected source host")
    if parsed.path != SOURCE_PATH:
        raise ExternalInputError("unexpected source path")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("source query or fragment is not allowed")


def validate_reference_url(href: str) -> str:
    absolute = urljoin(SOURCE_URL, href)
    parsed = urlsplit(absolute)
    if parsed.scheme != "https":
        raise ExternalInputError("reference must use HTTPS")
    if parsed.username or parsed.password:
        raise ExternalInputError("reference credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalInputError("invalid reference port") from exc
    if port not in (None, 443):
        raise ExternalInputError("non-default reference port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("reference escaped official host")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("reference query or fragment is not allowed")
    if not REFERENCE_RE.fullmatch(parsed.path):
        raise ExternalInputError("reference escaped bounded press-release path")
    return f"https://{SOURCE_HOST}{parsed.path.rstrip('/')}"


def fetch_source(url: str = SOURCE_URL) -> bytes:
    validate_source_url(url)
    conn = http.client.HTTPSConnection(SOURCE_HOST, 443, timeout=20)
    try:
        conn.request(
            "GET",
            SOURCE_PATH,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                "Accept-Encoding": "identity",
            },
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ExternalInputError(f"unexpected HTTP status: {response.status}")
        if response.getheader("Location"):
            raise ExternalInputError("redirect response is not allowed")
        if "text/html" not in response.getheader("Content-Type", "").lower():
            raise ExternalInputError("source is not HTML")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ExternalInputError("source response exceeds byte limit")
        return body
    finally:
        conn.close()


def classify_title(title: str) -> str:
    key = ascii_key(title)
    if "adapost" in key or "protectiei civile" in key or "protectie civila" in key:
        return "CIVIL_PROTECTION"
    if any(token in key for token in ("avertizare", "cod galben", "cod portocaliu", "cod rosu")):
        return "PUBLIC_WARNING_REFERENCE"
    if any(token in key for token in ("prevent", "masuri dispuse", "siguranta")):
        return "PREVENTION_INFORMATION"
    if any(token in key for token in ("misiunile pompierilor", "pompier", "salvator")):
        return "FIRE_RESCUE_INFORMATION"
    return "GENERAL_EMERGENCY_INFORMATION"


def extract_references(html_bytes: bytes) -> list[dict[str, object]]:
    try:
        source = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExternalInputError("source is not valid UTF-8") from exc

    parser = AnchorParser()
    parser.feed(source)
    parser.close()

    references: dict[str, dict[str, object]] = {}
    for label, href in parser.links:
        title = normalize_text(label)
        if not title or len(title) > 500:
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue
        references.setdefault(
            reference_url,
            {
                "service": "EMERGENCY_SERVICES",
                "source_kind": "ISU_PRESS_RELEASE_INDEX",
                "signal_type": classify_title(title),
                "title": title[:300],
                "url": reference_url,
                "index_presence_authorized": True,
                "current_state_authorized": False,
                "active_incident_authorized": False,
                "active_warning_authorized": False,
                "article_body_authorized": False,
            },
        )
        if len(references) >= MAX_REFERENCES:
            break

    return list(references.values())


def build_result(html_bytes: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    validate_source_url(source_url)
    references = extract_references(html_bytes)
    if len(references) < MIN_REFERENCES:
        state = "HOLD"
        reason = "insufficient_first_party_press_release_index_references"
    else:
        state = "CLEAR"
        reason = "bounded_first_party_press_release_index_references"

    evidence = json.dumps(references, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "state": state,
        "reason": reason,
        "source": {
            "url": SOURCE_URL,
            "host": SOURCE_HOST,
            "path": SOURCE_PATH,
            "sha256": sha256(html_bytes),
            "retrieval_policy": "HTTPS_ONLY_NO_REDIRECT_EXACT_HOST_PATH",
        },
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": (
            "The official ISU Valcea press-release index displayed these references at retrieval time only. "
            "Article bodies, attachments and media were not fetched. Index presence and coarse title classification "
            "do not establish an active incident, active warning, current service state, or continuing validity."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return """<!doctype html><html><body>
    <a href="/comunicate-de-presa/misiunile-pompierilor-valceni-in-ultimele-48-de-ore-760">Misiunile pompierilor vâlceni în ultimele 48 de ore</a>
    <a href="/comunicate-de-presa/situatia-fondului-de-adapostire-de-la-nivelul-judetului-valcea-761">Situația fondului de adăpostire de la nivelul județului Vâlcea</a>
    <a href="/comunicate-de-presa/masuri-dispuse-pentru-siguranta-cetatenilor-762">Măsuri dispuse pentru siguranța cetățenilor</a>
    <a href="/comunicate-de-presa/misiunile-pompierilor-valceni-in-ultimele-48-de-ore-760">duplicat</a>
    <a href="https://example.com/comunicate-de-presa/escaped-99">escaped host</a>
    <a href="/comunicate-de-presa/invalid">missing id</a>
    <a href="/comunicate-de-presa/test-99?live=1">query escape</a>
    </body></html>""".encode("utf-8")


def run_self_test() -> None:
    validate_source_url(SOURCE_URL)
    for bad in (
        "http://isuvl.igsu.ro/comunicate-de-presa",
        "https://www.isuvl.igsu.ro/comunicate-de-presa",
        "https://isuvl.igsu.ro/comunicate-de-presa/",
        "https://isuvl.igsu.ro/comunicate-de-presa?q=1",
        "https://isuvl.igsu.ro@evil.example/comunicate-de-presa",
    ):
        try:
            validate_source_url(bad)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"source URL unexpectedly accepted: {bad}")

    good = validate_reference_url("/comunicate-de-presa/test-comunicat-123")
    assert good == "https://isuvl.igsu.ro/comunicate-de-presa/test-comunicat-123"
    for bad_href in (
        "https://example.com/comunicate-de-presa/test-1",
        "/comunicate-de-presa/test-1?live=1",
        "/comunicate-de-presa/test-1#now",
        "/comunicate-de-presa/test",
        "/stiri-locale/test-1",
    ):
        try:
            validate_reference_url(bad_href)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"reference unexpectedly accepted: {bad_href}")

    references = extract_references(sample_html())
    assert len(references) == 3, references
    assert all(item["current_state_authorized"] is False for item in references)
    assert all(item["active_incident_authorized"] is False for item in references)
    assert all(item["active_warning_authorized"] is False for item in references)
    assert all(item["article_body_authorized"] is False for item in references)
    kinds = {str(item["signal_type"]) for item in references}
    assert "FIRE_RESCUE_INFORMATION" in kinds
    assert "CIVIL_PROTECTION" in kinds
    assert "PREVENTION_INFORMATION" in kinds

    result = build_result(sample_html())
    assert result["state"] == "CLEAR", result
    assert result["reference_count"] == 3, result
    assert result["content_contract"] == CONTENT_CONTRACT

    hold = build_result(b"<html><body><a href='/other'>other</a></body></html>")
    assert hold["state"] == "HOLD", hold
    assert "article_body_fetch" in hold["disabled_capabilities"]
    print("self-test: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0

    try:
        html_bytes = fetch_source()
        result = build_result(html_bytes)
    except (ExternalInputError, OSError, http.client.HTTPException) as exc:
        result = {
            "state": "HOLD",
            "reason": "first_party_press_release_index_fetch_or_validation_failed",
            "error": str(exc),
            "source": {"url": SOURCE_URL, "host": SOURCE_HOST, "path": SOURCE_PATH},
            "content_contract": CONTENT_CONTRACT,
            "reference_count": 0,
            "references": [],
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }

    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result["state"] == "CLEAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
