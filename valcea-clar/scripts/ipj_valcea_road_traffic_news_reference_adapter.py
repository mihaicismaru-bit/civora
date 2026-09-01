#!/usr/bin/env python3
"""Bounded first-party IPJ Vâlcea road-traffic news references for VÂLCEA CLAR."""

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

SOURCE_URL = "https://vl.politiaromana.ro/ro/stiri-si-media/stiri"
SOURCE_HOST = "vl.politiaromana.ro"
SOURCE_PATH = "/ro/stiri-si-media/stiri"
USER_AGENT = "VALCEA-CLAR-IPJ-Valcea-Road-Traffic-News-References/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REFERENCES = 24
MIN_REFERENCES = 3
REFERENCE_RE = re.compile(r"^/ro/stiri-si-media/stiri/[a-z0-9-]+/?$")
CONTENT_CONTRACT = "FIRST_PARTY_POLICE_ROAD_TRAFFIC_NEWS_INDEX_REFERENCE_ONLY"

ROAD_TRAFFIC_TOKENS = (
    "rutier",
    "trafic",
    "circulatie",
    "accident",
    "dn 7",
    "dn7",
    "drum national",
    "sofer",
    "conducator auto",
    "viteza",
    "alcool",
    "permis",
)

DISABLED_CAPABILITIES = [
    "article_body_fetch",
    "attachment_fetch",
    "media_fetch",
    "image_ingest",
    "incident_detail_extraction",
    "person_or_personal_data_extraction",
    "active_incident_inference",
    "active_traffic_disruption_inference",
    "current_road_state_inference",
    "current_enforcement_operation_inference",
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
        raise ExternalInputError("reference escaped bounded police-news path")
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


def is_road_traffic_title(title: str) -> bool:
    key = ascii_key(title)
    return any(token in key for token in ROAD_TRAFFIC_TOKENS)


def classify_title(title: str) -> str:
    key = ascii_key(title)
    if "accident" in key:
        return "ROAD_ACCIDENT_REFERENCE"
    if any(token in key for token in ("trafic", "circulatie", "restrict")):
        return "TRAFFIC_DISRUPTION_REFERENCE"
    if any(token in key for token in ("actiune", "siguranta rutiera", "preven")):
        return "ROAD_SAFETY_OPERATION_REFERENCE"
    if any(token in key for token in ("rutier", "viteza", "alcool", "permis", "sofer", "conducator auto")):
        return "ROAD_ENFORCEMENT_REFERENCE"
    return "ROAD_TRAFFIC_INFORMATION"


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
        if not title or len(title) > 500 or not is_road_traffic_title(title):
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue
        references.setdefault(
            reference_url,
            {
                "service": "ROAD_TRAFFIC_PUBLIC_SAFETY",
                "source_kind": "IPJ_VALCEA_NEWS_INDEX",
                "signal_type": classify_title(title),
                "title": title[:300],
                "url": reference_url,
                "index_presence_authorized": True,
                "current_state_authorized": False,
                "active_incident_authorized": False,
                "active_traffic_disruption_authorized": False,
                "current_enforcement_operation_authorized": False,
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
        reason = "insufficient_first_party_road_traffic_news_references"
    else:
        state = "CLEAR"
        reason = "bounded_first_party_road_traffic_news_references"

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
            "The official IPJ Valcea news index displayed these road-traffic-related references at retrieval time only. "
            "Article bodies, attachments and media were not fetched. Index presence and coarse title classification do "
            "not establish a currently active incident, traffic disruption, road condition, enforcement operation, or "
            "continuing validity."
        ),
        "reference_count": len(references),
        "references": references,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_html() -> bytes:
    return """<!doctype html><html><body>
    <a href="/ro/stiri-si-media/stiri/actiune-pentru-cresterea-sigurantei-rutiere-pe-dn-7">ACȚIUNE PENTRU CREȘTEREA SIGURANȚEI RUTIERE PE DN 7</a>
    <a href="/ro/stiri-si-media/stiri/accident-rutier-mortal-pe-dn-71787721723">ACCIDENT RUTIER MORTAL PE DN 7</a>
    <a href="/ro/stiri-si-media/stiri/depistat-de-politistii-biroului-rutier">DEPISTAT DE POLIȚIȘTII BIROULUI RUTIER</a>
    <a href="/ro/stiri-si-media/stiri/retinut-pentru-24-de-ore">REȚINUT PENTRU 24 DE ORE</a>
    <a href="/ro/stiri-si-media/stiri/actiune-pentru-cresterea-sigurantei-rutiere-pe-dn-7">duplicat rutier</a>
    <a href="https://example.com/ro/stiri-si-media/stiri/accident-rutier">ACCIDENT RUTIER</a>
    <a href="/ro/stiri-si-media/stiri/accident-rutier?live=1">ACCIDENT RUTIER query escape</a>
    </body></html>""".encode("utf-8")


def run_self_test() -> None:
    validate_source_url(SOURCE_URL)
    for bad in (
        "http://vl.politiaromana.ro/ro/stiri-si-media/stiri",
        "https://www.vl.politiaromana.ro/ro/stiri-si-media/stiri",
        "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/",
        "https://vl.politiaromana.ro/ro/stiri-si-media/stiri?page=2",
        "https://vl.politiaromana.ro@evil.example/ro/stiri-si-media/stiri",
    ):
        try:
            validate_source_url(bad)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"source URL unexpectedly accepted: {bad}")

    good = validate_reference_url("/ro/stiri-si-media/stiri/actiune-pentru-siguranta-rutiera-pe-dn-7")
    assert good == "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/actiune-pentru-siguranta-rutiera-pe-dn-7"
    for bad_href in (
        "https://example.com/ro/stiri-si-media/stiri/accident-rutier",
        "/ro/stiri-si-media/stiri/accident-rutier?live=1",
        "/ro/stiri-si-media/stiri/accident-rutier#now",
        "/ro/stiri-si-media/comunicate/accident-rutier",
        "/ro/stiri-si-media/stiri/",
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
    assert all(item["active_traffic_disruption_authorized"] is False for item in references)
    assert all(item["current_enforcement_operation_authorized"] is False for item in references)
    assert all(item["article_body_authorized"] is False for item in references)
    kinds = {str(item["signal_type"]) for item in references}
    assert "ROAD_SAFETY_OPERATION_REFERENCE" in kinds
    assert "ROAD_ACCIDENT_REFERENCE" in kinds
    assert "ROAD_ENFORCEMENT_REFERENCE" in kinds

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
            "reason": "first_party_road_traffic_news_fetch_or_validation_failed",
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
