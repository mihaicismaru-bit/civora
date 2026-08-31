#!/usr/bin/env python3
"""Bounded first-party Drăgășani municipal public-service directory references.

This adapter intentionally treats the municipality contact surface as directory
presence evidence only. It does not make reader-facing claims about current
availability, opening hours, emergency status, staffing, jurisdiction, or legal
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import http.client
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urlsplit

SOURCE_URL = "https://www.primariadragasani.ro/informatii-publice/contact"
SOURCE_HOST = "www.primariadragasani.ro"
SOURCE_PATH = "/informatii-publice/contact"
USER_AGENT = "VALCEA-CLAR-Dragasani-Public-Service-Directory/1.0"
MAX_RESPONSE_BYTES = 1_500_000

CONTENT_CONTRACT = "FIRST_PARTY_MUNICIPAL_SERVICE_DIRECTORY_REFERENCE_ONLY"
DISABLED_CAPABILITIES = [
    "person_extraction",
    "phone_email_address_extraction",
    "opening_hours_claims",
    "service_availability_claims",
    "emergency_status_claims",
    "jurisdiction_or_legal_authority_inference",
    "document_body_fetch",
    "breaking_news_promotion",
    "persistence",
    "fact_kernel",
    "writer",
    "public_projection",
    "image_ingest",
    "inferred_photo_rights",
]

SERVICE_LABELS = {
    "primaria municipiului dragasani": "MUNICIPAL_ADMINISTRATION",
    "secretariat primarie": "MUNICIPAL_ADMINISTRATION",
    "directia asistenta sociala": "SOCIAL_ASSISTANCE",
    "directia de asistenta sociala": "SOCIAL_ASSISTANCE",
    "directia servicii publice": "PUBLIC_SERVICES",
    "serviciul de evidenta a populatiei": "POPULATION_RECORDS",
    "evidenta populatiei, starea civila": "POPULATION_RECORDS",
    "evidenta populatiei starea civila": "POPULATION_RECORDS",
    "politia locala": "LOCAL_POLICE",
    "politia locala dispecerat": "LOCAL_POLICE",
    "casa de cultura": "CULTURE",
    "biblioteca municipala": "LIBRARY",
    "administratia pietei": "MARKET",
    "piata municipala": "MARKET",
    "protectia civila": "CIVIL_PROTECTION",
    "protectia civila situatii de urgenta": "CIVIL_PROTECTION",
}

CANONICAL_LABELS = {
    "MUNICIPAL_ADMINISTRATION": "Primăria Municipiului Drăgășani",
    "SOCIAL_ASSISTANCE": "Direcția de Asistență Socială",
    "PUBLIC_SERVICES": "Direcția Servicii Publice",
    "POPULATION_RECORDS": "Serviciul de Evidență a Populației",
    "LOCAL_POLICE": "Poliția Locală",
    "CULTURE": "Casa de Cultură",
    "LIBRARY": "Biblioteca Municipală",
    "MARKET": "Piața Municipală",
    "CIVIL_PROTECTION": "Protecție Civilă",
}

CORE_TYPES = {"MUNICIPAL_ADMINISTRATION", "PUBLIC_SERVICES", "LOCAL_POLICE"}


class ExternalInputError(RuntimeError):
    pass


class TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ascii_key(value: str) -> str:
    value = html_lib.unescape(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("ș", "s").replace("ş", "s").replace("ț", "t").replace("ţ", "t")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _validate_source_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ExternalInputError("source must use HTTPS")
    if parsed.username or parsed.password:
        raise ExternalInputError("credentials are not allowed")
    if parsed.port not in (None, 443):
        raise ExternalInputError("non-default ports are not allowed")
    if parsed.hostname != SOURCE_HOST:
        raise ExternalInputError("unexpected source host")
    if parsed.path.rstrip("/") != SOURCE_PATH:
        raise ExternalInputError("unexpected source path")
    if parsed.query or parsed.fragment:
        raise ExternalInputError("query and fragment are not allowed")


def fetch_source(url: str = SOURCE_URL) -> bytes:
    _validate_source_url(url)
    conn = http.client.HTTPSConnection(SOURCE_HOST, 443, timeout=20)
    try:
        conn.request("GET", SOURCE_PATH, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        response = conn.getresponse()
        if response.status != 200:
            raise ExternalInputError(f"unexpected HTTP status: {response.status}")
        content_type = response.getheader("Content-Type", "").lower()
        if "text/html" not in content_type:
            raise ExternalInputError("source is not HTML")
        location = response.getheader("Location")
        if location:
            raise ExternalInputError("redirect response is not allowed")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ExternalInputError("source response exceeds byte limit")
        return body
    finally:
        conn.close()


def _extract_text(html_bytes: bytes) -> str:
    try:
        source = html_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExternalInputError("source is not valid UTF-8") from exc
    parser = TextCollector()
    parser.feed(source)
    parser.close()
    return "\n".join(parser.parts)


def _detect_services(text: str) -> list[dict[str, str]]:
    # The public contact page may render labels and contact values together.
    # We only recognize a small allowlist of service labels and intentionally
    # discard every adjacent value (phones, emails, people, addresses, hours).
    normalized = _ascii_key(text)
    hits: dict[str, str] = {}
    for label, service_type in SERVICE_LABELS.items():
        if label in normalized:
            hits[service_type] = CANONICAL_LABELS[service_type]
    return [
        {"service_type": service_type, "service_name": hits[service_type]}
        for service_type in sorted(hits)
    ]


def build_result(html_bytes: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    _validate_source_url(source_url)
    text = _extract_text(html_bytes)
    references = _detect_services(text)
    found_types = {str(item["service_type"]) for item in references}
    missing_core = sorted(CORE_TYPES - found_types)

    if len(references) < 4:
        state = "HOLD"
        reason = "fewer_than_four_allowlisted_service_units"
    elif missing_core:
        state = "HOLD"
        reason = "missing_core_service_types:" + ",".join(missing_core)
    else:
        state = "CLEAR"
        reason = "bounded_first_party_directory_presence_references"

    source_sha = _sha256(html_bytes)
    evidence_seed = json.dumps(references, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "state": state,
        "reason": reason,
        "source": {
            "url": SOURCE_URL,
            "host": SOURCE_HOST,
            "path": SOURCE_PATH,
            "sha256": source_sha,
            "retrieval_policy": "HTTPS_ONLY_NO_REDIRECT_EXACT_HOST_PATH",
        },
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": "The first-party municipality contact surface listed these allowlisted service units at retrieval time only.",
        "references": references,
        "reference_count": len(references),
        "evidence_sha256": _sha256(evidence_seed),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def _sample_html(*, omit: Iterable[str] = (), duplicate: bool = False) -> bytes:
    omit_set = set(omit)
    labels = [
        "Primăria Municipiului Drăgășani",
        "Direcția de Asistență Socială",
        "Direcția Servicii Publice",
        "Serviciul de Evidență a Populației",
        "Poliția Locală (dispecerat)",
        "Casa de Cultură",
        "Biblioteca Municipală",
        "Piața Municipală",
        "Protecție Civilă, situații de urgență",
    ]
    kept = [label for label in labels if _ascii_key(label) not in omit_set]
    if duplicate and kept:
        kept.append(kept[0])
    rows = "".join(f"<li>{html_lib.escape(label)}: 0250 000 000</li>" for label in kept)
    return ("<html><body><h1>Contact</h1><p>Primar: Exemplu Persoană</p><ul>" + rows + "</ul>"
            "<p>dragasani@example.invalid</p><p>Luni - Vineri 08:00-16:00</p></body></html>").encode("utf-8")


def self_test() -> None:
    normal = build_result(_sample_html())
    assert normal["state"] == "CLEAR"
    assert normal["reference_count"] == 9
    serialized = json.dumps(normal, ensure_ascii=False)
    assert "0250 000 000" not in serialized
    assert "Exemplu Persoană" not in serialized
    assert "example.invalid" not in serialized
    assert "08:00" not in serialized

    duplicate = build_result(_sample_html(duplicate=True))
    assert duplicate["reference_count"] == 9

    missing_core = build_result(_sample_html(omit={"politia locala dispecerat"}))
    assert missing_core["state"] == "HOLD"
    assert "LOCAL_POLICE" in str(missing_core["reason"])

    sparse = build_result(b"<html><body>Biblioteca Municipală</body></html>")
    assert sparse["state"] == "HOLD"

    bad_urls = [
        "http://www.primariadragasani.ro/informatii-publice/contact",
        "https://primariadragasani.ro/informatii-publice/contact",
        "https://www.primariadragasani.ro/",
        "https://www.primariadragasani.ro/informatii-publice/contact?q=x",
        "https://evil.example/informatii-publice/contact",
    ]
    for bad in bad_urls:
        try:
            _validate_source_url(bad)
        except ExternalInputError:
            pass
        else:
            raise AssertionError(f"bad URL accepted: {bad}")

    assert DISABLED_CAPABILITIES
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-html", help="Read a captured first-party HTML page instead of live fetch")
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
