#!/usr/bin/env python3
"""Bounded first-party APAVIL scheduled water-interruption references."""

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
from urllib.parse import parse_qsl, urljoin, urlsplit

SOURCE_URL = "https://apavil.ro/?page_id=962"
SOURCE_HOST = "apavil.ro"
SOURCE_PATH = "/"
SOURCE_QUERY = "page_id=962"
USER_AGENT = "VALCEA-CLAR-APAVIL-Scheduled-Water-Interruptions/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 32
MIN_REFERENCES = 2
TARGET_YEAR = 2026
REFERENCE_PREFIX = f"/materiale/anunturi/{TARGET_YEAR}/"
CONTENT_CONTRACT = "FIRST_PARTY_SCHEDULED_WATER_INTERRUPTION_REFERENCE_ONLY"

DISABLED_CAPABILITIES = [
    "document_body_fetch",
    "pdf_text_extraction",
    "person_or_personal_data_extraction",
    "current_outage_state_inference",
    "service_restoration_inference",
    "current_service_availability_inference",
    "breaking_news_promotion",
    "persistence",
    "fact_kernel",
    "writer",
    "public_projection",
    "image_ingest",
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
        label = " ".join(self._parts).strip()
        self.links.append((label, self._href))
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


def ascii_key(value: str) -> str:
    value = html_lib.unescape(value)
    value = unicodedata.normalize("NFKD", value)
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
        raise ExternalInputError("non-default ports are not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("unexpected source host")
    if parsed.path != SOURCE_PATH:
        raise ExternalInputError("unexpected source path")
    if parsed.fragment:
        raise ExternalInputError("source fragment is not allowed")
    if parsed.query != SOURCE_QUERY:
        raise ExternalInputError("unexpected source query")
    if parse_qsl(parsed.query, keep_blank_values=True) != [("page_id", "962")]:
        raise ExternalInputError("source query is not exact")


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
        raise ExternalInputError("reference non-default port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("reference escaped official host")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("reference query or fragment is not allowed")
    path = parsed.path
    if not path.startswith(REFERENCE_PREFIX):
        raise ExternalInputError("reference escaped bounded current-year announcement path")
    filename = path.rsplit("/", 1)[-1]
    if not filename or not filename.casefold().endswith(".pdf"):
        raise ExternalInputError("reference is not a PDF announcement path")
    return f"https://{SOURCE_HOST}{path}"


def fetch_source(url: str = SOURCE_URL) -> bytes:
    validate_source_url(url)
    conn = http.client.HTTPSConnection(SOURCE_HOST, 443, timeout=20)
    try:
        conn.request(
            "GET",
            f"{SOURCE_PATH}?{SOURCE_QUERY}",
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
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


def is_interruption_title(title: str) -> bool:
    key = ascii_key(title)
    return ("intrerupere" in key or "intrerupe" in key) and "apa potabila" in key


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
        title = re.sub(r"\s+", " ", label).strip()
        if len(title) < 12 or not is_interruption_title(title):
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue
        references[reference_url] = {
            "year": TARGET_YEAR,
            "service": "POTABLE_WATER",
            "signal_type": "SCHEDULED_OR_ANNOUNCED_INTERRUPTION_REFERENCE",
            "title": title[:500],
            "url": reference_url,
            "current_state_authorized": False,
        }
        if len(references) >= MAX_REFERENCES:
            break

    return sorted(references.values(), key=lambda item: str(item["url"]), reverse=True)


def build_result(html_bytes: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    validate_source_url(source_url)
    references = extract_references(html_bytes)
    if len(references) < MIN_REFERENCES:
        state = "HOLD"
        reason = "insufficient_current_year_first_party_water_interruption_references"
    else:
        state = "CLEAR"
        reason = "bounded_current_year_first_party_water_interruption_references"

    evidence = json.dumps(references, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "state": state,
        "reason": reason,
        "source": {
            "url": SOURCE_URL,
            "host": SOURCE_HOST,
            "path": SOURCE_PATH,
            "query": SOURCE_QUERY,
            "sha256": sha256(html_bytes),
            "retrieval_policy": "HTTPS_ONLY_NO_REDIRECT_EXACT_HOST_PATH_QUERY",
        },
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": (
            "The APAVIL first-party scheduled-interruption index displayed these current-year "
            "water-interruption announcement references at retrieval time only. Linked PDFs were not fetched."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return """<!doctype html><html><body>
    <h1>Opriri programate</h1>
    <ul>
      <li><a href="/materiale/anunturi/2026/intrerupere_300826.pdf">
      Anunț întrerupere furnizare alimentare cu apa potabila a consumatorilor existenți din orașul Băbeni
      și a comunelor Budești și Galicea în intervalul 30.08.2026 ora 16:00 – 31.08.2026 ora 10:00
      </a></li>
      <li><a href="https://apavil.ro/materiale/anunturi/2026/intrerupere_100826.pdf">
      Anunț întrerupere furnizare alimentare cu apa potabila a consumatorilor existenți din municipiul
      Râmnicu Vâlcea în data de 10.08.2026, în intervalul 09:00 – 15:00
      </a></li>
      <li><a href="/materiale/anunturi/2025/intrerupere_2025.pdf">
      Anunț întrerupere furnizare apa potabila în anul 2025
      </a></li>
      <li><a href="https://example.org/materiale/anunturi/2026/x.pdf">
      Anunț întrerupere furnizare apa potabila test extern
      </a></li>
    </ul>
    </body></html>""".encode("utf-8")


def self_test() -> None:
    result = build_result(sample_html())
    assert result["state"] == "CLEAR"
    assert result["reference_count"] == 2
    refs = result["references"]
    assert all(int(item["year"]) == TARGET_YEAR for item in refs)
    assert all(item["service"] == "POTABLE_WATER" for item in refs)
    assert all(item["current_state_authorized"] is False for item in refs)

    duplicate = sample_html().replace(
        b"</ul>",
        b'<li><a href="/materiale/anunturi/2026/intrerupere_300826.pdf">'
        b'Anunt intrerupere furnizare apa potabila duplicat</a></li></ul>',
    )
    assert build_result(duplicate)["reference_count"] == 2

    one_valid = sample_html().replace(
        b"https://apavil.ro/materiale/anunturi/2026/intrerupere_100826.pdf",
        b"https://evil.example/materiale/anunturi/2026/intrerupere_100826.pdf",
    )
    assert build_result(one_valid)["state"] == "HOLD"
    assert build_result(one_valid)["reference_count"] == 1

    bad_urls = [
        "http://apavil.ro/?page_id=962",
        "https://www.apavil.ro/?page_id=962",
        "https://apavil.ro/",
        "https://apavil.ro/?page_id=961",
        "https://apavil.ro/?page_id=962&x=1",
        "https://apavil.ro:444/?page_id=962",
    ]
    for bad_url in bad_urls:
        try:
            validate_source_url(bad_url)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad source URL accepted: {bad_url}")

    bad_references = [
        "http://apavil.ro/materiale/anunturi/2026/x.pdf",
        "https://www.apavil.ro/materiale/anunturi/2026/x.pdf",
        "https://evil.example/materiale/anunturi/2026/x.pdf",
        "https://apavil.ro/materiale/anunturi/2025/x.pdf",
        "https://apavil.ro/materiale/anunturi/2026/x.docx",
        "https://apavil.ro/materiale/anunturi/2026/x.pdf?q=1",
    ]
    for bad_reference in bad_references:
        try:
            validate_reference_url(bad_reference)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad reference accepted: {bad_reference}")

    serialized = json.dumps(result, ensure_ascii=False)
    assert "document_body_fetch" in serialized
    assert "current_state_authorized" in serialized
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-html")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        if args.source_html:
            with open(args.source_html, "rb") as handle:
                html_bytes = handle.read(MAX_RESPONSE_BYTES + 1)
            if len(html_bytes) > MAX_RESPONSE_BYTES:
                raise ExternalInputError("source fixture exceeds byte limit")
        else:
            html_bytes = fetch_source()
        print(json.dumps(build_result(html_bytes), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ExternalInputError, OSError) as exc:
        print(json.dumps({"state": "HOLD", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
