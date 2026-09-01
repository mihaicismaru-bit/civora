#!/usr/bin/env python3
"""Bounded first-party Băbeni municipal announcement document references."""

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

SOURCE_URL = "https://www.orasbabeni.ro/anunturi/"
SOURCE_HOST = "www.orasbabeni.ro"
SOURCE_PATH = "/anunturi/"
USER_AGENT = "VALCEA-CLAR-Babeni-Municipal-Announcement-Documents/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 24
MIN_REFERENCES = 2
TARGET_YEAR = 2026
CONTENT_CONTRACT = "FIRST_PARTY_MUNICIPAL_ANNOUNCEMENT_DOCUMENT_REFERENCE_ONLY"

DISABLED_CAPABILITIES = [
    "document_body_fetch",
    "document_text_extraction",
    "person_or_personal_data_extraction",
    "legal_effect_or_current_validity_inference",
    "recruitment_outcome_inference",
    "project_completion_or_impact_inference",
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


class EventParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str, str | None]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a" or self._href is not None:
            return
        self._href = dict(attrs).get("href")
        self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        label = " ".join(part for part in self._anchor_parts if part).strip()
        self.events.append(("link", label, self._href))
        self._href = None
        self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        if self._href is not None:
            self._anchor_parts.append(value)
        else:
            self.events.append(("text", value, None))


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
    if parsed.path.rstrip("/") != SOURCE_PATH.rstrip("/"):
        raise ExternalInputError("unexpected source path")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("query and fragment are not allowed")


def validate_reference_url(href: str) -> str:
    absolute = urljoin(SOURCE_URL, href)
    parsed = urlsplit(absolute)
    if parsed.scheme != "https":
        raise ExternalInputError("document reference must use HTTPS")
    if parsed.username or parsed.password:
        raise ExternalInputError("document reference credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalInputError("invalid document reference port") from exc
    if port not in (None, 443):
        raise ExternalInputError("document reference non-default port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("document reference escaped official host")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("document reference query/fragment is not allowed")
    path = parsed.path
    prefix = f"/wp-content/uploads/{TARGET_YEAR}/"
    if not path.startswith(prefix):
        raise ExternalInputError("document reference escaped bounded current-year uploads path")
    if path.endswith("/") or "." not in path.rsplit("/", 1)[-1]:
        raise ExternalInputError("document reference is not a file path")
    return f"https://{SOURCE_HOST}{path}"


def fetch_source(url: str = SOURCE_URL) -> bytes:
    validate_source_url(url)
    conn = http.client.HTTPSConnection(SOURCE_HOST, 443, timeout=20)
    try:
        conn.request(
            "GET",
            SOURCE_PATH,
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


def classify_title(title: str) -> str:
    key = ascii_key(title)
    if any(token in key for token in ("concurs", "selectie", "rezultat", "post vacant", "cariera")):
        return "CAREER_RECRUITMENT_REFERENCE"
    if any(token in key for token in ("comunicat", "presa")):
        return "PRESS_COMMUNICATION_REFERENCE"
    if any(token in key for token in ("locuint", "nzeb", "cadastru", "asigurare")):
        return "HOUSING_PROPERTY_REFERENCE"
    if any(token in key for token in ("apia", "agricol", "erbicid")):
        return "AGRICULTURE_REFERENCE"
    return "GENERAL_MUNICIPAL_DOCUMENT_REFERENCE"


def extract_references(html_bytes: bytes) -> list[dict[str, str | int]]:
    try:
        source = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExternalInputError("source is not valid UTF-8") from exc

    parser = EventParser()
    parser.feed(source)
    parser.close()

    in_target_year = False
    saw_target_year = False
    references: dict[str, dict[str, str | int]] = {}

    for kind, value, href in parser.events:
        if kind == "text":
            normalized = ascii_key(value)
            if re.fullmatch(r"\d{4}", normalized):
                year = int(normalized)
                in_target_year = year == TARGET_YEAR
                saw_target_year = saw_target_year or in_target_year
            continue

        if not in_target_year or href is None:
            continue

        title = re.sub(r"\s+", " ", value).strip()
        if len(title) < 4:
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue

        references[reference_url] = {
            "year": TARGET_YEAR,
            "title": title[:280],
            "topic_class": classify_title(title),
            "url": reference_url,
        }
        if len(references) >= MAX_REFERENCES:
            break

    if not saw_target_year:
        raise ExternalInputError("current-year section not found")

    return sorted(references.values(), key=lambda item: str(item["url"]))


def build_result(html_bytes: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    validate_source_url(source_url)
    references = extract_references(html_bytes)
    if len(references) < MIN_REFERENCES:
        state = "HOLD"
        reason = "insufficient_current_year_first_party_document_references"
    else:
        state = "CLEAR"
        reason = "bounded_current_year_first_party_announcement_document_references"

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
            "The first-party Băbeni announcements index displayed these current-year "
            "document references at retrieval time only; referenced documents were not fetched."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return """<!doctype html><html><body>
    <nav><a href="/">Acasă</a><a href="/anunturi/">Anunțuri</a></nav>
    <h2>Anunțuri</h2>
    <h3>2026</h3>
    <p><a href="/wp-content/uploads/2026/07/Comunicat_CJVL.pdf">Comunicat_CJVL</a></p>
    <p><a href="https://www.orasbabeni.ro/wp-content/uploads/2026/01/Rezultatul-probei-de-selectie-concurs-secretar-dactilograf-Nr.-270-din-15-ianuarie-2026.pdf">Rezultatul probei de selectie concurs secretar dactilograf Nr. 270 din 15 ianuarie 2026</a></p>
    <h3>2025</h3>
    <p><a href="/wp-content/uploads/2025/07/vechi.pdf">Document vechi</a></p>
    <footer><a href="https://facebook.com/example">Facebook</a></footer>
    </body></html>""".encode("utf-8")


def self_test() -> None:
    result = build_result(sample_html())
    assert result["state"] == "CLEAR"
    assert result["reference_count"] == 2
    refs = result["references"]
    classes = {str(item["topic_class"]) for item in refs}
    assert "PRESS_COMMUNICATION_REFERENCE" in classes
    assert "CAREER_RECRUITMENT_REFERENCE" in classes
    assert all(int(item["year"]) == TARGET_YEAR for item in refs)

    duplicate = sample_html().replace(
        b"<h3>2025</h3>",
        b'<a href="/wp-content/uploads/2026/07/Comunicat_CJVL.pdf">Duplicat</a><h3>2025</h3>',
    )
    assert build_result(duplicate)["reference_count"] == 2

    off_host = sample_html().replace(
        b'href="/wp-content/uploads/2026/07/Comunicat_CJVL.pdf"',
        b'href="https://evil.example/wp-content/uploads/2026/07/Comunicat_CJVL.pdf"',
    )
    assert build_result(off_host)["state"] == "HOLD"
    assert build_result(off_host)["reference_count"] == 1

    wrong_year = sample_html().replace(b"<h3>2026</h3>", b"<h3>2024</h3>")
    try:
        build_result(wrong_year)
    except ExternalInputError:
        pass
    else:
        raise AssertionError("missing current-year section must fail closed")

    bad_urls = [
        "http://www.orasbabeni.ro/anunturi/",
        "https://orasbabeni.ro/anunturi/",
        "https://www.orasbabeni.ro/",
        "https://www.orasbabeni.ro/anunturi/?q=x",
        "https://evil.example/anunturi/",
        "https://www.orasbabeni.ro:444/anunturi/",
    ]
    for bad_url in bad_urls:
        try:
            validate_source_url(bad_url)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad source URL accepted: {bad_url}")

    bad_references = [
        "http://www.orasbabeni.ro/wp-content/uploads/2026/07/x.pdf",
        "https://evil.example/wp-content/uploads/2026/07/x.pdf",
        "https://www.orasbabeni.ro/wp-content/uploads/2025/07/x.pdf",
        "https://www.orasbabeni.ro/wp-content/uploads/2026/07/x.pdf?q=x",
        "https://www.orasbabeni.ro/anunturi/",
        "https://www.orasbabeni.ro/wp-content/uploads/2026/07/",
    ]
    for bad_reference in bad_references:
        try:
            validate_reference_url(bad_reference)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad document reference accepted: {bad_reference}")

    serialized = json.dumps(result, ensure_ascii=False)
    assert "facebook.com" not in serialized
    assert "document_body_fetch" in serialized
    assert "admis" not in serialized.casefold()
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
