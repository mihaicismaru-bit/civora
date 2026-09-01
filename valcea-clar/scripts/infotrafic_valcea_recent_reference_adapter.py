#!/usr/bin/env python3
"""Bounded recent first-party INFOTRAFIC references explicitly naming Vâlcea."""

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

SOURCE_URL = "https://politiaromana.ro/ro/info-trafic"
SOURCE_HOST = "politiaromana.ro"
SOURCE_PATH = "/ro/info-trafic"
USER_AGENT = "VALCEA-CLAR-INFOTRAFIC-Valcea-Recent-References/1.0"
MAX_RESPONSE_BYTES = 2_000_000
MAX_SCAN_PAGES = 6
MAX_REFERENCES = 24
MIN_INDEX_REFERENCES = 20
REFERENCE_RE = re.compile(r"^/ro/info-trafic/[a-z0-9-]+/?$")
CONTENT_CONTRACT = "FIRST_PARTY_INFOTRAFIC_RECENT_VALCEA_REFERENCE_ONLY"

DISABLED_CAPABILITIES = [
    "article_body_fetch",
    "attachment_fetch",
    "media_fetch",
    "image_ingest",
    "incident_detail_extraction",
    "person_or_personal_data_extraction",
    "active_status_inference",
    "active_incident_inference",
    "active_traffic_disruption_inference",
    "current_road_state_inference",
    "absence_means_no_valcea_alert",
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


def page_path(page_number: int) -> str:
    if not 1 <= page_number <= MAX_SCAN_PAGES:
        raise ExternalInputError("page number escaped bounded scan window")
    if page_number == 1:
        return SOURCE_PATH
    return f"{SOURCE_PATH}&page={page_number}"


def page_url(page_number: int) -> str:
    return f"https://{SOURCE_HOST}{page_path(page_number)}"


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
        raise ExternalInputError("reference escaped bounded INFOTRAFIC article path")
    return f"https://{SOURCE_HOST}{parsed.path.rstrip('/')}"


def fetch_page(page_number: int) -> bytes:
    path = page_path(page_number)
    conn = http.client.HTTPSConnection(SOURCE_HOST, 443, timeout=20)
    try:
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
                "Accept-Encoding": "identity",
            },
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ExternalInputError(f"unexpected HTTP status on page {page_number}: {response.status}")
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
    if any(token in key for token in ("trafic oprit", "trafic blocat", "circulatie oprita", "circulatie intrerupta", "trafic intrerupt")):
        return "TRAFFIC_STOPPAGE_REFERENCE"
    if any(token in key for token in ("trafic restrictionat", "trafic ingreunat", "trafic alternativ", "trafic dirijat", "circulatie restrictionata", "circulatie alternativa")):
        return "TRAFFIC_RESTRICTION_REFERENCE"
    if "accident" in key:
        return "ROAD_ACCIDENT_REFERENCE"
    if "transport" in key and "agabaritic" in key:
        return "OVERSIZE_TRANSPORT_REFERENCE"
    return "ROAD_TRAFFIC_INFORMATION"


def parse_page(page_number: int, html_bytes: bytes) -> tuple[list[tuple[str, str]], int]:
    try:
        source = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExternalInputError("source is not valid UTF-8") from exc
    if "INFOTRAFIC" not in source.upper():
        raise ExternalInputError(f"INFOTRAFIC marker missing on page {page_number}")

    parser = AnchorParser()
    parser.feed(source)
    parser.close()

    all_index_refs: dict[str, str] = {}
    valcea_refs: list[tuple[str, str]] = []
    for label, href in parser.links:
        title = normalize_text(label)
        if not title or len(title) > 500:
            continue
        try:
            reference_url = validate_reference_url(href)
        except ExternalInputError:
            continue
        all_index_refs.setdefault(reference_url, title)
        if "valcea" in ascii_key(title):
            valcea_refs.append((title, reference_url))

    return valcea_refs, len(all_index_refs)


def build_result(pages: list[tuple[int, bytes]]) -> dict[str, object]:
    validate_source_url(SOURCE_URL)
    if not pages or [number for number, _ in pages] != list(range(1, len(pages) + 1)):
        raise ExternalInputError("pages must form a contiguous scan beginning at page 1")
    if len(pages) > MAX_SCAN_PAGES:
        raise ExternalInputError("scan exceeded bounded page limit")

    references: dict[str, dict[str, object]] = {}
    observed_index_reference_count = 0
    page_evidence: list[dict[str, object]] = []

    for page_number, html_bytes in pages:
        valcea_refs, generic_count = parse_page(page_number, html_bytes)
        observed_index_reference_count += generic_count
        page_evidence.append(
            {
                "page": page_number,
                "url": page_url(page_number),
                "sha256": sha256(html_bytes),
                "observed_index_reference_count": generic_count,
            }
        )
        for title, reference_url in valcea_refs:
            references.setdefault(
                reference_url,
                {
                    "service": "ROAD_TRAFFIC_PUBLIC_SAFETY",
                    "source_kind": "POLITIA_ROMANA_INFOTRAFIC_RECENT_INDEX",
                    "signal_type": classify_title(title),
                    "title": title[:300],
                    "url": reference_url,
                    "observed_on_index_page": page_number,
                    "index_presence_authorized": True,
                    "current_state_authorized": False,
                    "active_status_authorized": False,
                    "active_incident_authorized": False,
                    "active_traffic_disruption_authorized": False,
                    "article_body_authorized": False,
                },
            )
            if len(references) >= MAX_REFERENCES:
                break
        if len(references) >= MAX_REFERENCES:
            break

    if observed_index_reference_count < MIN_INDEX_REFERENCES:
        state = "HOLD"
        reason = "insufficient_first_party_infotrafic_index_structure"
    else:
        state = "CLEAR"
        reason = "bounded_recent_first_party_infotrafic_valcea_reference_scan"

    reference_list = list(references.values())
    evidence = json.dumps(reference_list, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "state": state,
        "reason": reason,
        "source": {
            "url": SOURCE_URL,
            "host": SOURCE_HOST,
            "path": SOURCE_PATH,
            "retrieval_policy": "HTTPS_ONLY_NO_REDIRECT_EXACT_HOST_BOUNDED_RECENT_PAGES",
            "scan_is_exhaustive": False,
            "pages": page_evidence,
        },
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": (
            "The official Politia Romana INFOTRAFIC recent index pages displayed these references whose visible titles "
            "explicitly named Valcea at retrieval time. Article bodies, attachments and media were not fetched. Index "
            "presence does not establish active status, a currently active incident or disruption, current road state, "
            "or the absence of other Valcea alerts outside the bounded scan window."
        ),
        "scanned_page_count": len(pages),
        "observed_index_reference_count": observed_index_reference_count,
        "reference_count": len(reference_list),
        "references": reference_list,
        "evidence_sha256": sha256(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def sample_page(page_number: int, *, include_valcea: bool = False) -> bytes:
    valcea = ""
    if include_valcea:
        valcea = '<a href="/ro/info-trafic/judetul-valcea-trafic-oprit-pe-dn-71788000001">JUDEȚUL VÂLCEA: TRAFIC OPRIT PE DN 7</a>'
    generic = "".join(
        f'<a href="/ro/info-trafic/judetul-test-{page_number}-{idx}">JUDEȚUL TEST: TRAFIC ÎNGREUNAT PE DN {idx}</a>'
        for idx in range(1, 6)
    )
    return f"<!doctype html><html><body>INFOTRAFIC {valcea}{generic}</body></html>".encode("utf-8")


def run_self_test() -> None:
    validate_source_url(SOURCE_URL)
    for bad in (
        "http://politiaromana.ro/ro/info-trafic",
        "https://www.politiaromana.ro/ro/info-trafic",
        "https://politiaromana.ro/ro/info-trafic/",
        "https://politiaromana.ro/ro/info-trafic?page=2",
        "https://politiaromana.ro@evil.example/ro/info-trafic",
    ):
        try:
            validate_source_url(bad)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"source URL unexpectedly accepted: {bad}")

    assert page_path(1) == "/ro/info-trafic"
    assert page_path(2) == "/ro/info-trafic&page=2"
    try:
        page_path(MAX_SCAN_PAGES + 1)
    except ExternalInputError:
        pass
    else:
        raise AssertionError("page scan escaped bounded limit")

    good = validate_reference_url("/ro/info-trafic/judetul-valcea-trafic-oprit-pe-dn-71788000001")
    assert good == "https://politiaromana.ro/ro/info-trafic/judetul-valcea-trafic-oprit-pe-dn-71788000001"
    for bad_href in (
        "https://example.com/ro/info-trafic/judetul-valcea-trafic-oprit",
        "/ro/info-trafic/judetul-valcea-trafic-oprit?live=1",
        "/ro/info-trafic/judetul-valcea-trafic-oprit#now",
        "/ro/stiri/judetul-valcea-trafic-oprit",
        "/ro/info-trafic/",
    ):
        try:
            validate_reference_url(bad_href)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"reference unexpectedly accepted: {bad_href}")

    pages = [(idx, sample_page(idx, include_valcea=idx == 2)) for idx in range(1, 5)]
    result = build_result(pages)
    assert result["state"] == "CLEAR", result
    assert result["observed_index_reference_count"] >= MIN_INDEX_REFERENCES, result
    assert result["reference_count"] == 1, result
    reference = result["references"][0]
    assert reference["signal_type"] == "TRAFFIC_STOPPAGE_REFERENCE", reference
    assert reference["current_state_authorized"] is False
    assert reference["active_status_authorized"] is False
    assert reference["active_incident_authorized"] is False
    assert reference["active_traffic_disruption_authorized"] is False
    assert reference["article_body_authorized"] is False

    no_valcea = build_result([(idx, sample_page(idx)) for idx in range(1, 5)])
    assert no_valcea["state"] == "CLEAR", no_valcea
    assert no_valcea["reference_count"] == 0, no_valcea
    assert "absence_means_no_valcea_alert" in no_valcea["disabled_capabilities"]

    hold = build_result([(1, b"<html><body>INFOTRAFIC</body></html>")])
    assert hold["state"] == "HOLD", hold
    print("self-test: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0

    try:
        pages = [(page_number, fetch_page(page_number)) for page_number in range(1, MAX_SCAN_PAGES + 1)]
        result = build_result(pages)
    except (ExternalInputError, OSError, http.client.HTTPException) as exc:
        result = {
            "state": "HOLD",
            "reason": "first_party_infotrafic_fetch_or_validation_failed",
            "error": str(exc),
            "source": {"url": SOURCE_URL, "host": SOURCE_HOST, "path": SOURCE_PATH},
            "content_contract": CONTENT_CONTRACT,
            "scanned_page_count": 0,
            "observed_index_reference_count": 0,
            "reference_count": 0,
            "references": [],
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }

    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result["state"] == "CLEAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
