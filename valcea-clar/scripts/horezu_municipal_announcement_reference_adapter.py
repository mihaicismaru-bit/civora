#!/usr/bin/env python3
"""Bounded first-party Horezu municipal announcement index references."""

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

SOURCE_URL = "https://www.orasul-horezu.ro/anunturi"
SOURCE_HOST = "www.orasul-horezu.ro"
SOURCE_PATH = "/anunturi"
USER_AGENT = "VALCEA-CLAR-Horezu-Municipal-Announcements/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 32
TARGET_YEAR = 2026
CONTENT_CONTRACT = "FIRST_PARTY_MUNICIPAL_ANNOUNCEMENT_INDEX_REFERENCE_ONLY"

MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}

DISABLED_CAPABILITIES = [
    "announcement_body_fetch",
    "downloadable_document_fetch",
    "person_or_personal_data_extraction",
    "legal_effect_or_current_validity_inference",
    "event_currentness_inference",
    "road_closure_currentness_inference",
    "service_availability_inference",
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
    if parsed.path.rstrip("/") != SOURCE_PATH:
        raise ExternalInputError("unexpected source path")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("query and fragment are not allowed")


def validate_reference_url(href: str) -> str:
    absolute = urljoin(SOURCE_URL, href)
    parsed = urlsplit(absolute)
    if parsed.scheme != "https":
        raise ExternalInputError("announcement reference must use HTTPS")
    if parsed.username or parsed.password:
        raise ExternalInputError("announcement reference credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalInputError("invalid announcement reference port") from exc
    if port not in (None, 443):
        raise ExternalInputError("announcement reference non-default port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("announcement reference escaped official host")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("announcement reference query/fragment is not allowed")
    path = parsed.path.rstrip("/") or "/"
    if path == "/" or path == SOURCE_PATH:
        raise ExternalInputError("announcement reference path is not an article path")
    if path.startswith("/sites/") or path.startswith("/admin") or path.startswith("/user"):
        raise ExternalInputError("announcement reference is not a bounded article path")
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


def parse_romanian_date(value: str) -> str | None:
    normalized = ascii_key(value)
    match = re.fullmatch(r"([a-z]+)\s+(\d{1,2})\s+(\d{4})", normalized)
    if not match:
        return None
    month_name, day_raw, year_raw = match.groups()
    month = MONTHS.get(month_name)
    if month is None:
        return None
    day = int(day_raw)
    year = int(year_raw)
    if year != TARGET_YEAR or not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def classify_title(title: str) -> str:
    key = ascii_key(title)
    if any(token in key for token in ("drum", "circulatie", "biciclist", "cnair", "zgomot", "parcare")):
        return "ROAD_TRAFFIC_REFERENCE"
    if any(token in key for token in ("mediu", "incadrare", "pug", "urbanism")):
        return "ENVIRONMENT_PLANNING_REFERENCE"
    if any(token in key for token in ("spital", "ambulatoriu", "sanatate")):
        return "HEALTH_INFRASTRUCTURE_REFERENCE"
    if any(token in key for token in ("curs", "formare", "training")):
        return "TRAINING_REFERENCE"
    if any(token in key for token in ("biserica", "cultura", "muzeu", "festival", "eveniment")):
        return "CULTURE_HERITAGE_REFERENCE"
    if any(token in key for token in ("locuint", "vulnerabil", "social")):
        return "HOUSING_SOCIAL_REFERENCE"
    return "GENERAL_MUNICIPAL_ANNOUNCEMENT_REFERENCE"


def extract_references(html_bytes: bytes) -> list[dict[str, str]]:
    try:
        source = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExternalInputError("source is not valid UTF-8") from exc

    parser = EventParser()
    parser.feed(source)
    parser.close()

    latest_date: str | None = None
    references: dict[str, dict[str, str]] = {}
    for kind, value, href in parser.events:
        if kind == "text":
            parsed_date = parse_romanian_date(value)
            if parsed_date:
                latest_date = parsed_date
            continue

        if latest_date is None or href is None:
            continue
        title = re.sub(r"\s+", " ", value).strip()
        if len(title) < 4:
            continue
        if ascii_key(title) in {"descarca", "anunturi", "proiecte", "contact", "facebook"}:
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue
        references[reference_url] = {
            "announcement_date": latest_date,
            "title": title[:280],
            "topic_class": classify_title(title),
            "url": reference_url,
        }
        latest_date = None
        if len(references) >= MAX_REFERENCES:
            break

    return sorted(
        references.values(),
        key=lambda item: (item["announcement_date"], item["url"]),
        reverse=True,
    )


def build_result(html_bytes: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    validate_source_url(source_url)
    references = extract_references(html_bytes)
    if len(references) < 3:
        state = "HOLD"
        reason = "fewer_than_three_current_year_announcement_references"
    else:
        state = "CLEAR"
        reason = "bounded_first_party_current_year_announcement_index_references"

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
            "The first-party Horezu municipal announcements index displayed these dated "
            "article references at retrieval time only."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return """<!doctype html><html><body>
    <nav><a href=\"/\">Acasă</a><a href=\"/anunturi\">Anunțuri</a></nav>
    <div>General</div><div>august 27, 2026</div>
    <h2><a href=\"/anunt-inchidere-drum-vf-roman\">Anunț închidere drum spre Vf lui Roman</a></h2>
    <div>General</div><div>august 24, 2026</div>
    <h2><a href=\"https://www.orasul-horezu.ro/anunt-public-mediu-pug\">Anunț public mediu PUG</a></h2>
    <div>General</div><div>iunie 24, 2026</div>
    <h2><a href=\"/extindere-ambulatoriu-spital-horezu\">Anunț presă extindere ambulatoriu Spitalul Orășenesc Horezu</a></h2>
    <footer><a href=\"https://www.facebook.com/example\">Facebook</a></footer>
    </body></html>""".encode("utf-8")


def self_test() -> None:
    result = build_result(sample_html())
    assert result["state"] == "CLEAR"
    assert result["reference_count"] == 3
    references = result["references"]
    assert references[0]["announcement_date"] == "2026-08-27"
    assert references[0]["topic_class"] == "ROAD_TRAFFIC_REFERENCE"
    assert references[1]["topic_class"] == "ENVIRONMENT_PLANNING_REFERENCE"
    assert references[2]["topic_class"] == "HEALTH_INFRASTRUCTURE_REFERENCE"

    duplicate = sample_html().replace(
        b"</body>",
        b'<div>august 27, 2026</div><a href="/anunt-inchidere-drum-vf-roman">Duplicat</a></body>',
    )
    deduped = build_result(duplicate)
    assert deduped["reference_count"] == 3

    stale = sample_html().replace(b"2026", b"2025")
    assert build_result(stale)["state"] == "HOLD"

    off_host = sample_html().replace(
        b'href="/anunt-inchidere-drum-vf-roman"',
        b'href="https://evil.example/anunt-inchidere-drum-vf-roman"',
    )
    assert build_result(off_host)["reference_count"] == 2
    assert build_result(off_host)["state"] == "HOLD"

    bad_urls = [
        "http://www.orasul-horezu.ro/anunturi",
        "https://orasul-horezu.ro/anunturi",
        "https://www.orasul-horezu.ro/",
        "https://www.orasul-horezu.ro/anunturi?q=x",
        "https://evil.example/anunturi",
        "https://www.orasul-horezu.ro:444/anunturi",
    ]
    for bad_url in bad_urls:
        try:
            validate_source_url(bad_url)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad source URL accepted: {bad_url}")

    bad_references = [
        "http://www.orasul-horezu.ro/anunt-x",
        "https://evil.example/anunt-x",
        "https://www.orasul-horezu.ro/anunt-x?q=x",
        "https://www.orasul-horezu.ro/sites/default/files/x.pdf",
        "https://www.orasul-horezu.ro/anunturi",
    ]
    for bad_reference in bad_references:
        try:
            validate_reference_url(bad_reference)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad announcement reference accepted: {bad_reference}")

    serialized = json.dumps(result, ensure_ascii=False)
    assert "facebook.com" not in serialized
    assert "document_body_fetch" not in serialized
    assert "announcement_body_fetch" in serialized
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
