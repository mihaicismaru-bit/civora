#!/usr/bin/env python3
"""Bounded first-party ETA Bus route-directory references for VÂLCEA CLAR."""

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

SOURCE_URL = "https://eta-bus.ro/trasee"
SOURCE_HOST = "eta-bus.ro"
SOURCE_PATH = "/trasee"
USER_AGENT = "VALCEA-CLAR-ETA-Bus-Route-Directory/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 32
MIN_REFERENCES = 8
REFERENCE_PREFIX = "/t/"
CONTENT_CONTRACT = "FIRST_PARTY_TRANSIT_ROUTE_DIRECTORY_REFERENCE_ONLY"
ROUTE_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")

DISABLED_CAPABILITIES = [
    "route_page_fetch",
    "station_page_fetch",
    "schedule_body_ingest",
    "timetable_currentness_inference",
    "service_currentness_inference",
    "active_disruption_inference",
    "realtime_arrival_inference",
    "route_geometry_inference",
    "stop_sequence_inference",
    "person_or_personal_data_extraction",
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


def normalize_text(value: str) -> str:
    value = html_lib.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def ascii_key(value: str) -> str:
    value = normalize_text(value)
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
        raise ExternalInputError("non-default source port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("unexpected source host")
    if parsed.path != SOURCE_PATH:
        raise ExternalInputError("unexpected source path")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("source query or fragment is not allowed")


def validate_route_reference_url(href: str) -> tuple[str, str]:
    absolute = urljoin(SOURCE_URL, href)
    parsed = urlsplit(absolute)
    if parsed.scheme != "https":
        raise ExternalInputError("route reference must use HTTPS")
    if parsed.username or parsed.password:
        raise ExternalInputError("route reference credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalInputError("invalid route reference port") from exc
    if port not in (None, 443):
        raise ExternalInputError("non-default route reference port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("route reference escaped official host")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("route reference query or fragment is not allowed")
    if not parsed.path.startswith(REFERENCE_PREFIX):
        raise ExternalInputError("route reference escaped route path")
    code = parsed.path[len(REFERENCE_PREFIX) :].strip("/")
    if "/" in code or not ROUTE_CODE_RE.fullmatch(code):
        raise ExternalInputError("route reference is not a bounded route code")
    canonical_code = code.upper()
    return f"https://{SOURCE_HOST}{REFERENCE_PREFIX}{canonical_code}", canonical_code


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


def label_matches_route_code(title: str, route_code: str) -> bool:
    key = ascii_key(title)
    return key == route_code.casefold() or key.startswith(route_code.casefold() + " ")


def route_description(title: str, route_code: str) -> str:
    normalized = normalize_text(title)
    match = re.match(r"^\s*" + re.escape(route_code) + r"\s*(.*)$", normalized, flags=re.IGNORECASE)
    if not match:
        return normalized[:300]
    description = match.group(1).strip(" -–—")
    return description[:300]


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
            reference_url, route_code = validate_route_reference_url(href)
        except ExternalInputError:
            continue
        if not label_matches_route_code(title, route_code):
            continue
        references[route_code] = {
            "service": "LOCAL_PUBLIC_TRANSIT",
            "signal_type": "ROUTE_DIRECTORY_REFERENCE",
            "route_code": route_code,
            "route_description": route_description(title, route_code),
            "title": title[:300],
            "url": reference_url,
            "schedule_currentness_authorized": False,
            "current_service_state_authorized": False,
            "realtime_authorized": False,
        }
        if len(references) >= MAX_REFERENCES:
            break

    return sorted(references.values(), key=lambda item: str(item["route_code"]))


def build_result(html_bytes: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    validate_source_url(source_url)
    references = extract_references(html_bytes)
    if len(references) < MIN_REFERENCES:
        state = "HOLD"
        reason = "insufficient_first_party_route_directory_references"
    else:
        state = "CLEAR"
        reason = "bounded_first_party_route_directory_references"

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
            "The ETA Bus first-party route directory displayed these route references at retrieval time only. "
            "Route pages, station pages and timetable bodies were not fetched, and directory presence does not "
            "establish current service, current timetable validity, active disruption, stop sequence, geometry, "
            "or realtime arrival state."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return b"""<!doctype html><html><body>
    <a href=\"/t/1\">1 Shopping City - Colonie</a>
    <a href=\"/t/3\">3 Dispecerat Nord - Vladesti</a>
    <a href=\"/t/5\">5 Dispecerat Nord - Metnef</a>
    <a href=\"/t/5A\">5A Dispecerat Nord - Metnef (1 Mai)</a>
    <a href=\"/t/6\">6 Dispecerat Hermes - Cresa Goranu</a>
    <a href=\"/t/6V\">6V Cresa Goranu - Uzina Mecanica</a>
    <a href=\"/t/8S\">8S Dispecerat Nord - Pesticide</a>
    <a href=\"/t/B\">B Dispecerat Nord - Buda</a>
    <a href=\"/t/P\">P Shopping City - Poenari</a>
    <a href=\"https://example.com/t/7\">7 escaped host</a>
    <a href=\"/t/7?live=1\">7 query escape</a>
    <a href=\"/t/../admin\">admin</a>
    <a href=\"/s/127\">Mall</a>
    </body></html>"""


def run_self_test() -> None:
    validate_source_url(SOURCE_URL)
    for bad in (
        "http://eta-bus.ro/trasee",
        "https://www.eta-bus.ro/trasee",
        "https://eta-bus.ro/trasee/",
        "https://eta-bus.ro/trasee?q=1",
        "https://eta-bus.ro@evil.example/trasee",
    ):
        try:
            validate_source_url(bad)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"source URL unexpectedly accepted: {bad}")

    good_url, good_code = validate_route_reference_url("/t/5a")
    assert good_url == "https://eta-bus.ro/t/5A"
    assert good_code == "5A"
    for bad_href in (
        "https://example.com/t/1",
        "/t/1?live=1",
        "/t/1#now",
        "/t/../admin",
        "/s/1",
        "/t/this-code-is-too-long",
    ):
        try:
            validate_route_reference_url(bad_href)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"route reference unexpectedly accepted: {bad_href}")

    references = extract_references(sample_html())
    codes = {str(item["route_code"]) for item in references}
    assert codes == {"1", "3", "5", "5A", "6", "6V", "8S", "B", "P"}, references
    assert all(item["schedule_currentness_authorized"] is False for item in references)
    assert all(item["current_service_state_authorized"] is False for item in references)
    assert all(item["realtime_authorized"] is False for item in references)
    result = build_result(sample_html())
    assert result["state"] == "CLEAR", result
    assert result["reference_count"] == 9, result
    assert result["content_contract"] == CONTENT_CONTRACT
    assert "route_page_fetch" in result["disabled_capabilities"]
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
            "reason": "first_party_route_directory_fetch_or_validation_failed",
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
