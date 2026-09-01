#!/usr/bin/env python3
"""Bounded first-party ETA Bus rider/service announcement references."""

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

SOURCE_URL = "https://eta-bus.ro/comunicate"
SOURCE_HOST = "eta-bus.ro"
SOURCE_PATH = "/comunicate"
USER_AGENT = "VALCEA-CLAR-ETA-Bus-Service-Announcements/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 24
MIN_REFERENCES = 2
REFERENCE_PREFIX = "/comunicate/"
CONTENT_CONTRACT = "FIRST_PARTY_TRANSIT_SERVICE_ANNOUNCEMENT_REFERENCE_ONLY"

RIDER_SIGNAL_TERMS = (
    "aplicatie",
    "avl",
    "panou",
    "tarif",
    "bilet",
    "abonament",
    "calator",
    "transport",
    "traseu",
    "statie",
    "program circulatie",
    "program de circulatie",
    "circulatie autobuz",
    "orar",
)

DISABLED_CAPABILITIES = [
    "article_body_fetch",
    "attachment_fetch",
    "person_or_personal_data_extraction",
    "publication_date_inference",
    "current_service_state_inference",
    "current_disruption_inference",
    "service_restoration_inference",
    "realtime_arrival_inference",
    "fare_currentness_inference",
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
        raise ExternalInputError("reference non-default port is not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("reference escaped official host")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("reference query or fragment is not allowed")
    path = parsed.path
    if not path.startswith(REFERENCE_PREFIX):
        raise ExternalInputError("reference escaped communications path")
    suffix = path[len(REFERENCE_PREFIX):].strip("/")
    if not suffix or "/" in suffix or suffix in {".", ".."} or ".." in suffix:
        raise ExternalInputError("reference is not a bounded communication slug")
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


def is_rider_service_title(title: str) -> bool:
    key = ascii_key(title)
    return any(term in key for term in RIDER_SIGNAL_TERMS)


def classify_title(title: str) -> str:
    key = ascii_key(title)
    if any(term in key for term in ("aplicatie", "avl", "panou")):
        return "RIDER_INFORMATION_SYSTEM"
    if any(term in key for term in ("tarif", "bilet", "abonament", "calator")):
        return "FARE_OR_TICKETING"
    if any(term in key for term in ("traseu", "statie", "program", "circulatie", "orar")):
        return "ROUTE_OR_SCHEDULE"
    if "transport" in key:
        return "TRANSIT_SERVICE_INFORMATION"
    return "GENERAL_RIDER_INFORMATION"


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
        if len(title) < 5 or not is_rider_service_title(title):
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue
        references[reference_url] = {
            "service": "LOCAL_PUBLIC_TRANSIT",
            "signal_type": "RIDER_SERVICE_ANNOUNCEMENT_REFERENCE",
            "category": classify_title(title),
            "title": title[:300],
            "url": reference_url,
            "publication_date_authorized": False,
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
        reason = "insufficient_first_party_rider_service_announcement_references"
    else:
        state = "CLEAR"
        reason = "bounded_first_party_rider_service_announcement_references"

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
            "The ETA Bus first-party communications index displayed these rider/service references at retrieval "
            "time only. Article bodies and attachments were not fetched, and index presence does not establish "
            "publication date, current service state, active disruption, current fare, or restoration status."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return """<!doctype html><html><body>
    <h1>Comunicate</h1>
    <h3><a href="/comunicate/comunicat-aplicatie-skayo-avl/">Comunicat aplicație Skayo AVL</a></h3>
    <h3><a href="https://eta-bus.ro/comunicate/tarife-01-02-2026/">Tarife de transport valabile</a></h3>
    <h3><a href="/comunicate/calatorii-gratuite-locuitori-municipiu">Calatorii gratuite locuitori municipiu</a></h3>
    <h3><a href="/comunicate/anunt-vanzare-autovehicul">Anunț vânzare autovehicul</a></h3>
    <h3><a href="https://new.eta-bus.ro/files/abonamente.pdf">Anunț abonamente extern</a></h3>
    </body></html>""".encode("utf-8")


def self_test() -> None:
    result = build_result(sample_html())
    assert result["state"] == "CLEAR"
    assert result["reference_count"] == 3
    refs = result["references"]
    assert all(item["service"] == "LOCAL_PUBLIC_TRANSIT" for item in refs)
    assert all(item["current_state_authorized"] is False for item in refs)
    assert all(item["publication_date_authorized"] is False for item in refs)
    assert {item["category"] for item in refs} == {
        "RIDER_INFORMATION_SYSTEM",
        "FARE_OR_TICKETING",
    }

    duplicate = sample_html().replace(
        b"</body>",
        b'<a href="/comunicate/comunicat-aplicatie-skayo-avl/">Aplicatie AVL duplicat</a></body>',
    )
    assert build_result(duplicate)["reference_count"] == 3

    one_valid = b"""<!doctype html><html><body>
    <a href="/comunicate/program-circulatie">Program circulatie autobuze</a>
    <a href="https://evil.example/comunicate/tarife">Tarife transport</a>
    </body></html>"""
    held = build_result(one_valid)
    assert held["state"] == "HOLD"
    assert held["reference_count"] == 1

    bad_urls = [
        "http://eta-bus.ro/comunicate",
        "https://www.eta-bus.ro/comunicate",
        "https://eta-bus.ro/comunicate/",
        "https://eta-bus.ro/",
        "https://eta-bus.ro/comunicate?q=1",
        "https://eta-bus.ro:444/comunicate",
    ]
    for bad_url in bad_urls:
        try:
            validate_source_url(bad_url)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad source URL accepted: {bad_url}")

    bad_references = [
        "http://eta-bus.ro/comunicate/program",
        "https://www.eta-bus.ro/comunicate/program",
        "https://new.eta-bus.ro/comunicate/program",
        "https://evil.example/comunicate/program",
        "https://eta-bus.ro/aga/program",
        "https://eta-bus.ro/comunicate/../contact",
        "https://eta-bus.ro/comunicate/program?q=1",
    ]
    for bad_reference in bad_references:
        try:
            validate_reference_url(bad_reference)
        except ExternalInputError:
            continue
        raise AssertionError(f"bad reference accepted: {bad_reference}")

    serialized = json.dumps(result, ensure_ascii=False)
    assert "article_body_fetch" in serialized
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
